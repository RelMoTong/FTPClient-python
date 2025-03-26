import os
import time
import uuid
import logging
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from queue import Queue

from common.config import Config
from common.exceptions import (
    ConnectionError, AuthenticationError, FileTransferError, QueueError
)
from common.utils import format_size, get_file_md5, get_file_crc32
from common.protocol import TransferMode, ConnectionMode
from client.ftp_client import FTPClient
from client.transfer_queue import (
    TransferQueue, TransferTask, TaskType, TaskStatus, TaskPriority
)

logger = logging.getLogger(__name__)

class FTPClientPool:
    """FTP客户端连接池"""
    
    def __init__(self, host, port, username, password, pool_size=3, 
                 enable_ssl=False, timeout=30, passive_mode=True):
        """
        初始化FTP客户端连接池
        
        Args:
            host: 服务器主机
            port: 服务器端口
            username: 用户名
            password: 密码
            pool_size: 连接池大小
            enable_ssl: 是否启用SSL
            timeout: 超时时间
            passive_mode: 是否使用被动模式
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.enable_ssl = enable_ssl
        self.timeout = timeout
        self.passive_mode = passive_mode
        
        # 初始化连接池
        self._pool = Queue(maxsize=pool_size)
        self._pool_size = pool_size
        self._lock = threading.RLock()
        self._clients_in_use = {}  # {client_id: client}
        
        # 预先创建连接
        for _ in range(pool_size):
            client = self._create_client()
            if client:
                self._pool.put(client)
    
    def _create_client(self):
        """创建并配置一个新的FTP客户端"""
        try:
            client = FTPClient(
                host=self.host,
                port=self.port,
                timeout=self.timeout,
                enable_ssl=self.enable_ssl
            )
            
            # 设置连接模式
            mode = ConnectionMode.PASSIVE if self.passive_mode else ConnectionMode.ACTIVE
            client.set_connection_mode(mode)
            
            # 连接并登录
            client.connect()
            client.login(self.username, self.password)
            
            logger.debug(f"创建了一个新的FTP客户端连接: {id(client)}")
            return client
            
        except (ConnectionError, AuthenticationError) as e:
            logger.error(f"创建FTP客户端连接失败: {str(e)}")
            return None
    
    def get_client(self):
        """
        从连接池获取一个FTP客户端
        
        Returns:
            FTPClient: FTP客户端
        """
        client = None
        
        try:
            # 首先尝试从池中获取
            client = self._pool.get(block=False)
            
            # 检查连接是否有效
            if not self._check_client(client):
                client = self._create_client()
                
        except Exception:
            # 如果池为空，则创建新客户端
            client = self._create_client()
        
        if client:
            # 标记为已使用
            with self._lock:
                client_id = id(client)
                self._clients_in_use[client_id] = client
            
            return client
        
        raise ConnectionError("无法获取FTP客户端连接")
    
    def _check_client(self, client):
        """检查客户端连接是否有效"""
        if not client:
            return False
            
        try:
            # 尝试发送NOOP命令检查连接
            client._send_command("NOOP")
            client._read_response()
            return True
        except Exception:
            logger.debug(f"FTP客户端连接已失效: {id(client)}")
            return False
    
    def release_client(self, client):
        """
        释放客户端回连接池
        
        Args:
            client: FTP客户端
        """
        if client:
            client_id = id(client)
            
            with self._lock:
                if client_id in self._clients_in_use:
                    self._clients_in_use.pop(client_id)
                    
                    # 检查客户端是否仍然有效
                    if self._check_client(client):
                        try:
                            self._pool.put(client, block=False)
                            return
                        except Exception:
                            pass
            
            # 如果无法放回池中或无效，则关闭连接
            try:
                client.quit()
            except Exception:
                pass
    
    def close_all(self):
        """关闭所有连接"""
        # 关闭使用中的连接
        with self._lock:
            for client in self._clients_in_use.values():
                try:
                    client.quit()
                except Exception:
                    pass
            self._clients_in_use.clear()
        
        # 关闭池中的连接
        while not self._pool.empty():
            try:
                client = self._pool.get(block=False)
                try:
                    client.quit()
                except Exception:
                    pass
            except Exception:
                pass
        
        logger.info("已关闭所有FTP客户端连接")

class FTPQueueManager(TransferQueue):
    """FTP队列管理器，处理FTP任务队列"""
    
    def __init__(self, client_pool, max_concurrent_tasks=3, auto_retry=True):
        """
        初始化FTP队列管理器
        
        Args:
            client_pool: FTP客户端连接池
            max_concurrent_tasks: 最大并发任务数
            auto_retry: 是否自动重试
        """
        super().__init__(max_concurrent_tasks=max_concurrent_tasks, auto_retry=auto_retry)
        self.client_pool = client_pool
    
    def _get_task_handler(self, task_type):
        """
        获取任务处理方法
        
        Args:
            task_type: 任务类型
            
        Returns:
            handler: 处理方法
        """
        handlers = {
            TaskType.UPLOAD: self._handle_upload,
            TaskType.DOWNLOAD: self._handle_download,
            TaskType.DELETE: self._handle_delete,
            TaskType.RENAME: self._handle_rename,
            TaskType.MKDIR: self._handle_mkdir,
            TaskType.RMDIR: self._handle_rmdir,
            TaskType.LIST: self._handle_list,
        }
        
        handler = handlers.get(task_type)
        if not handler:
            raise ValueError(f"未知的任务类型: {task_type}")
            
        return handler
    
    def _handle_upload(self, task):
        """处理上传任务"""
        local_path, remote_path = task.args
        mode = task.kwargs.get('mode')
        resume = task.kwargs.get('resume', False)
        verify = task.kwargs.get('verify', False)
        
        # 获取客户端
        client = self.client_pool.get_client()
        
        try:
            # 设置进度回调
            def progress_callback(transferred, total, elapsed):
                task.update_progress(transferred, total, elapsed)
                
            client.set_progress_callback(progress_callback)
            
            # 执行上传
            success, size, elapsed = client.upload(
                local_path, 
                remote_path, 
                mode=mode, 
                resume=resume, 
                verify=verify
            )
            
            result = {
                'success': success,
                'size': size,
                'elapsed': elapsed,
                'speed': size / elapsed if elapsed > 0 else 0,
                'remote_path': remote_path
            }
            
            # 如果要验证，计算并存储校验和
            if verify:
                local_md5 = get_file_md5(local_path)
                local_crc32 = get_file_crc32(local_path)
                result['local_md5'] = local_md5
                result['local_crc32'] = local_crc32
                # 服务器可能不支持MD5/CRC32命令，所以这里不获取远程校验和
                
            return result
            
        finally:
            # 释放客户端
            self.client_pool.release_client(client)
    
    def _handle_download(self, task):
        """处理下载任务"""
        remote_path, local_path = task.args
        mode = task.kwargs.get('mode')
        resume = task.kwargs.get('resume', False)
        verify = task.kwargs.get('verify', False)
        
        # 获取客户端
        client = self.client_pool.get_client()
        
        try:
            # 设置进度回调
            def progress_callback(transferred, total, elapsed):
                task.update_progress(transferred, total, elapsed)
                
            client.set_progress_callback(progress_callback)
            
            # 执行下载
            success, size, elapsed = client.download(
                remote_path, 
                local_path, 
                mode=mode, 
                resume=resume, 
                verify=verify
            )
            
            result = {
                'success': success,
                'size': size,
                'elapsed': elapsed,
                'speed': size / elapsed if elapsed > 0 else 0,
                'local_path': local_path
            }
            
            # 如果要验证，计算并存储校验和
            if verify and os.path.exists(local_path):
                local_md5 = get_file_md5(local_path)
                local_crc32 = get_file_crc32(local_path)
                result['local_md5'] = local_md5
                result['local_crc32'] = local_crc32
                
            return result
            
        finally:
            # 释放客户端
            self.client_pool.release_client(client)
    
    def _handle_delete(self, task):
        """处理删除任务"""
        remote_path = task.args[0]
        
        # 获取客户端
        client = self.client_pool.get_client()
        
        try:
            # 执行删除
            success = client.delete(remote_path)
            
            return {'success': success, 'remote_path': remote_path}
            
        finally:
            # 释放客户端
            self.client_pool.release_client(client)
    
    def _handle_rename(self, task):
        """处理重命名任务"""
        from_path, to_path = task.args
        
        # 获取客户端
        client = self.client_pool.get_client()
        
        try:
            # 执行重命名
            success = client.rename(from_path, to_path)
            
            return {'success': success, 'from_path': from_path, 'to_path': to_path}
            
        finally:
            # 释放客户端
            self.client_pool.release_client(client)
    
    def _handle_mkdir(self, task):
        """处理创建目录任务"""
        remote_path = task.args[0]
        
        # 获取客户端
        client = self.client_pool.get_client()
        
        try:
            # 执行创建目录
            result = client.mkd(remote_path)
            
            return {'success': True, 'remote_path': result}
            
        finally:
            # 释放客户端
            self.client_pool.release_client(client)
    
    def _handle_rmdir(self, task):
        """处理删除目录任务"""
        remote_path = task.args[0]
        
        # 获取客户端
        client = self.client_pool.get_client()
        
        try:
            # 执行删除目录
            success = client.rmd(remote_path)
            
            return {'success': success, 'remote_path': remote_path}
            
        finally:
            # 释放客户端
            self.client_pool.release_client(client)
    
    def _handle_list(self, task):
        """处理列表任务"""
        remote_path = task.args[0] if task.args else None
        use_mlsd = task.kwargs.get('use_mlsd', False)
        
        # 获取客户端
        client = self.client_pool.get_client()
        
        try:
            # 执行列表
            if use_mlsd:
                listing = client.mlsd(remote_path)
            else:
                listing = client.list(remote_path)
            
            return {'success': True, 'remote_path': remote_path, 'listing': listing}
            
        finally:
            # 释放客户端
            self.client_pool.release_client(client)

class AdvancedFTPClient:
    """高级FTP客户端，支持并发传输和队列管理"""
    
    def __init__(self, config_path=None, max_concurrent_tasks=3):
        """
        初始化高级FTP客户端
        
        Args:
            config_path: 配置文件路径
            max_concurrent_tasks: 最大并发任务数
        """
        # 加载配置
        if config_path:
            self.config = Config(config_path)
        else:
            # 使用默认配置
            default_config_path = os.path.join("e:", "Python", "NewFTP", "config", "client_config.json")
            self.config = Config(default_config_path)
        
        # 初始化属性
        self.max_concurrent_tasks = max_concurrent_tasks
        self.client_pool = None
        self.queue_manager = None
        self.connected = False
    
    def connect(self, host=None, port=None, username=None, password=None,
               enable_ssl=None, passive_mode=None, timeout=None):
        """
        连接到FTP服务器
        
        Args:
            host: 服务器主机
            port: 服务器端口
            username: 用户名
            password: 密码
            enable_ssl: 是否启用SSL
            passive_mode: 是否使用被动模式
            timeout: 超时时间
        
        Returns:
            bool: 是否成功连接
        """
        # 使用参数或配置
        host = host or self.config.get('default_host')
        port = port or self.config.get('default_port', 21)
        username = username or self.config.get('default_username', 'anonymous')
        password = password or self.config.get('default_password', '')
        enable_ssl = enable_ssl if enable_ssl is not None else self.config.get('enable_ssl', False)
        passive_mode = passive_mode if passive_mode is not None else self.config.get('passive_mode', True)
        timeout = timeout or self.config.get('timeout', 30)
        
        try:
            # 创建客户端连接池
            self.client_pool = FTPClientPool(
                host=host,
                port=port,
                username=username,
                password=password,
                pool_size=self.max_concurrent_tasks,
                enable_ssl=enable_ssl,
                timeout=timeout,
                passive_mode=passive_mode
            )
            
            # 创建队列管理器
            self.queue_manager = FTPQueueManager(
                client_pool=self.client_pool,
                max_concurrent_tasks=self.max_concurrent_tasks,
                auto_retry=self.config.get('auto_retry', True)
            )
            
            self.connected = True
            logger.info(f"已连接到FTP服务器 {host}:{port}")
            return True
            
        except Exception as e:
            logger.error(f"连接FTP服务器失败: {str(e)}")
            self.connected = False
            
            if self.client_pool:
                self.client_pool.close_all()
                self.client_pool = None
                
            if self.queue_manager:
                self.queue_manager.shutdown(wait=False)
                self.queue_manager = None
                
            raise
    
    def disconnect(self):
        """断开连接"""
        if self.client_pool:
            self.client_pool.close_all()
            self.client_pool = None
            
        if self.queue_manager:
            self.queue_manager.shutdown(wait=True)
            self.queue_manager = None
            
        self.connected = False
        logger.info("已断开FTP连接")
    
    def _check_connected(self):
        """检查是否已连接"""
        if not self.connected or not self.queue_manager or not self.client_pool:
            raise ConnectionError("未连接到FTP服务器")
    
    def upload(self, local_path, remote_path=None, mode=None, 
              resume=False, verify=False, priority=TaskPriority.NORMAL,
              on_progress=None, on_complete=None, on_error=None):
        """
        上传文件
        
        Args:
            local_path: 本地文件路径
            remote_path: 远程文件路径，默认使用本地文件名
            mode: 传输模式（ASCII或BINARY），默认自动检测
            resume: 是否断点续传
            verify: 是否验证文件完整性
            priority: 任务优先级
            on_progress: 进度回调函数
            on_complete: 完成回调函数
            on_error: 错误回调函数
            
        Returns:
            task_id: 任务ID
        """
        self._check_connected()
        
        # 检查本地文件
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"本地文件不存在: {local_path}")
            
        if not os.path.isfile(local_path):
            raise ValueError(f"本地路径不是文件: {local_path}")
        
        # 如果未指定远程路径，则使用本地文件名
        if not remote_path:
            remote_path = os.path.basename(local_path)
        
        # 添加到队列
        task_id = self.queue_manager.add_task(
            TaskType.UPLOAD,
            local_path,
            remote_path,
            priority=priority,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
            mode=mode,
            resume=resume,
            verify=verify
        )
        
        return task_id
    
    def download(self, remote_path, local_path=None, mode=None,
                resume=False, verify=False, priority=TaskPriority.NORMAL,
                on_progress=None, on_complete=None, on_error=None):
        """
        下载文件
        
        Args:
            remote_path: 远程文件路径
            local_path: 本地保存路径，默认使用远程文件名
            mode: 传输模式（ASCII或BINARY），默认自动检测
            resume: 是否断点续传
            verify: 是否验证文件完整性
            priority: 任务优先级
            on_progress: 进度回调函数
            on_complete: 完成回调函数
            on_error: 错误回调函数
            
        Returns:
            task_id: 任务ID
        """
        self._check_connected()
        
        # 如果未指定本地路径，则使用远程文件名
        if not local_path:
            local_path = os.path.basename(remote_path)
        
        # 确保本地目录存在
        local_dir = os.path.dirname(local_path)
        if local_dir and not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)
        
        # 添加到队列
        task_id = self.queue_manager.add_task(
            TaskType.DOWNLOAD,
            remote_path,
            local_path,
            priority=priority,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
            mode=mode,
            resume=resume,
            verify=verify
        )
        
        return task_id
    
    def delete(self, remote_path, priority=TaskPriority.NORMAL,
              on_complete=None, on_error=None):
        """
        删除远程文件
        
        Args:
            remote_path: 远程文件路径
            priority: 任务优先级
            on_complete: 完成回调函数
            on_error: 错误回调函数
            
        Returns:
            task_id: 任务ID
        """
        self._check_connected()
        
        # 添加到队列
        task_id = self.queue_manager.add_task(
            TaskType.DELETE,
            remote_path,
            priority=priority,
            on_complete=on_complete,
            on_error=on_error
        )
        
        return task_id
    
    def rename(self, from_path, to_path, priority=TaskPriority.NORMAL,
              on_complete=None, on_error=None):
        """
        重命名远程文件
        
        Args:
            from_path: 原文件路径
            to_path: 新文件路径
            priority: 任务优先级
            on_complete: 完成回调函数
            on_error: 错误回调函数
            
        Returns:
            task_id: 任务ID
        """
        self._check_connected()
        
        # 添加到队列
        task_id = self.queue_manager.add_task(
            TaskType.RENAME,
            from_path,
            to_path,
            priority=priority,
            on_complete=on_complete,
            on_error=on_error
        )
        
        return task_id
    
    def mkdir(self, remote_path, priority=TaskPriority.NORMAL,
             on_complete=None, on_error=None):
        """
        创建远程目录
        
        Args:
            remote_path: 远程目录路径
            priority: 任务优先级
            on_complete: 完成回调函数
            on_error: 错误回调函数
            
        Returns:
            task_id: 任务ID
        """
        self._check_connected()
        
        # 添加到队列
        task_id = self.queue_manager.add_task(
            TaskType.MKDIR,
            remote_path,
            priority=priority,
            on_complete=on_complete,
            on_error=on_error
        )
        
        return task_id
    
    def rmdir(self, remote_path, priority=TaskPriority.NORMAL,
             on_complete=None, on_error=None):
        """
        删除远程目录
        
        Args:
            remote_path: 远程目录路径
            priority: 任务优先级
            on_complete: 完成回调函数
            on_error: 错误回调函数
            
        Returns:
            task_id: 任务ID
        """
        self._check_connected()
        
        # 添加到队列
        task_id = self.queue_manager.add_task(
            TaskType.RMDIR,
            remote_path,
            priority=priority,
            on_complete=on_complete,
            on_error=on_error
        )
        
        return task_id
    
    def list_directory(self, remote_path=None, use_mlsd=False, 
                     priority=TaskPriority.NORMAL,
                     on_complete=None, on_error=None):
        """
        列出远程目录内容
        
        Args:
            remote_path: 远程目录路径，默认为当前目录
            use_mlsd: 是否使用MLSD命令
            priority: 任务优先级
            on_complete: 完成回调函数
            on_error: 错误回调函数
            
        Returns:
            task_id: 任务ID
        """
        self._check_connected()
        
        # 添加到队列
        task_id = self.queue_manager.add_task(
            TaskType.LIST,
            remote_path,
            priority=priority,
            on_complete=on_complete,
            on_error=on_error,
            use_mlsd=use_mlsd
        )
        
        return task_id
    
    def get_task_status(self, task_id):
        """
        获取任务状态
        
        Args:
            task_id: 任务ID
            
        Returns:
            task: 任务对象或None
        """
        self._check_connected()
        return self.queue_manager.get_task_status(task_id)
    
    def cancel_task(self, task_id):
        """
        取消任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            bool: 是否成功取消
        """
        self._check_connected()
        return self.queue_manager.cancel_task(task_id)
    
    def get_all_tasks(self):
        """
        获取所有任务状态
        
        Returns:
            dict: 所有任务状态
        """
        self._check_connected()
        return self.queue_manager.get_all_tasks()
    
    def wait_for_task(self, task_id, timeout=None):
        """
        等待任务完成
        
        Args:
            task_id: 任务ID
            timeout: 超时时间（秒），None表示无限等待
            
        Returns:
            bool: 是否成功完成
        """
        self._check_connected()
        
        start_time = time.time()
        while True:
            task = self.get_task_status(task_id)
            
            # 任务不存在
            if not task:
                return False
                
            # 任务完成
            if task.status == TaskStatus.COMPLETED:
                return True
                
            # 任务失败
            if task.status in [TaskStatus.FAILED, TaskStatus.CANCELED]:
                return False
                
            # 检查超时
            if timeout and (time.time() - start_time) > timeout:
                return False
                
            # 等待一小段时间
            time.sleep(0.1)
    
    def wait_all(self, timeout=None):
        """
        等待所有任务完成
        
        Args:
            timeout: 超时时间（秒），None表示无限等待
            
        Returns:
            bool: 是否所有任务都成功完成
        """
        self._check_connected()
        
        start_time = time.time()
        while True:
            tasks = self.get_all_tasks()
            
            # 检查是否还有活动或排队的任务
            if not tasks['active'] and tasks['queue_size'] == 0:
                return True
                
            # 检查超时
            if timeout and (time.time() - start_time) > timeout:
                return False
                
            # 等待一小段时间
            time.sleep(0.5)
    
    def download_directory(self, remote_dir, local_dir, on_progress=None, 
                     on_complete=None, on_error=None, priority=TaskPriority.NORMAL):
        """
        递归下载整个目录
        
        Args:
            remote_dir: 远程目录路径
            local_dir: 本地保存目录
            on_progress: 进度回调
            on_complete: 完成回调
            on_error: 错误回调
            priority: 任务优先级
            
        Returns:
            list: 所有创建的任务ID列表
        """
        self._check_connected()
        task_ids = []
        
        # 确保本地目录存在
        os.makedirs(local_dir, exist_ok=True)
        
        # 先列出远程目录内容
        list_task_id = self.list_directory(
            remote_path=remote_dir,
            priority=TaskPriority.HIGH  # 给列表操作高优先级
        )
        
        # 等待列表任务完成
        if not self.wait_for_task(list_task_id, timeout=30):
            logger.error(f"获取目录列表超时: {remote_dir}")
            if on_error:
                # 创建一个模拟任务对象传递给回调
                error_task = TransferTask(
                    id=f"err-{len(task_ids)+1}",
                    type=TaskType.DOWNLOAD,
                    args=(remote_dir, local_dir),
                    kwargs={},
                    priority=priority
                )
                error_task.mark_failed(Exception(f"获取目录列表超时: {remote_dir}"))
                on_error(error_task)
            return task_ids
        
        # 获取目录列表结果
        list_task = self.get_task_status(list_task_id)
        if not list_task or not list_task.result or not list_task.result.get('success'):
            logger.error(f"获取目录列表失败: {remote_dir}")
            if on_error:
                # 创建一个模拟任务对象传递给回调
                error_task = TransferTask(
                    id=f"err-{len(task_ids)+1}",
                    type=TaskType.DOWNLOAD,
                    args=(remote_dir, local_dir),
                    kwargs={},
                    priority=priority
                )
                error_task.mark_failed(Exception(f"获取目录列表失败: {remote_dir}"))
                on_error(error_task)
            return task_ids
        
        # 处理目录中的每个项目
        items = list_task.result['listing']
        for item in items:
            if item.get('name') in ['.', '..']:
                continue
                
            remote_path = os.path.join(remote_dir, item['name']).replace('\\', '/')
            local_path = os.path.join(local_dir, item['name'])
            
            if item.get('type') == 'dir':
                # 递归处理子目录
                sub_tasks = self.download_directory(
                    remote_path, 
                    local_path,
                    on_progress=on_progress,
                    on_complete=on_complete,
                    on_error=on_error,
                    priority=priority
                )
                task_ids.extend(sub_tasks)
            else:
                # 下载文件
                task_id = self.download(
                    remote_path=remote_path,
                    local_path=local_path,
                    on_progress=on_progress,
                    on_complete=on_complete,
                    on_error=on_error,
                    priority=priority
                )
                task_ids.append(task_id)
        
        return task_ids
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.disconnect()

import os
import time
import uuid
import queue
import threading
import logging
from enum import Enum, auto
from datetime import datetime
from pathlib import Path

from common.exceptions import FTPError, ConnectionError
from client.ftp_client import FTPClient

# 设置日志记录器
logger = logging.getLogger(__name__)

class TaskType(Enum):
    """任务类型"""
    CONNECT = auto()
    LIST = auto()
    DOWNLOAD = auto()
    UPLOAD = auto()
    DELETE = auto()
    MKDIR = auto()
    RMDIR = auto()
    RENAME = auto()
    SIZE = auto()
    MDTM = auto()
    OTHER = auto()

class TaskPriority(Enum):
    """任务优先级"""
    LOW = 10
    NORMAL = 5
    HIGH = 1

class TaskStatus(Enum):
    """任务状态"""
    PENDING = "待处理"
    RUNNING = "运行中"
    COMPLETE = "已完成"
    FAILED = "失败"
    CANCELLED = "已取消"

class Task:
    """任务类，代表一个FTP操作"""
    
    def __init__(self, task_type, func, args=None, kwargs=None, priority=TaskPriority.NORMAL):
        self.id = f"task-{uuid.uuid4().hex[:8]}"
        self.type = task_type
        self.func = func
        self.args = args or []
        self.kwargs = kwargs or {}
        self.priority = priority
        self.status = TaskStatus.PENDING
        self.created_at = datetime.now()
        self.started_at = None
        self.completed_at = None
        self.result = None
        self.error = None
        self.progress = 0
        self.retries = 0
        self.max_retries = 3
        
        # 回调函数
        self.on_progress = None
        self.on_complete = None
        self.on_error = None
        
        # 从kwargs中提取回调
        self._extract_callbacks()
    
    def _extract_callbacks(self):
        """从kwargs中提取回调函数"""
        for key in ['on_progress', 'on_complete', 'on_error']:
            if key in self.kwargs:
                setattr(self, key, self.kwargs.pop(key))
    
    def start(self):
        """开始执行任务"""
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now()
    
    def complete(self, result):
        """完成任务"""
        self.status = TaskStatus.COMPLETE
        self.completed_at = datetime.now()
        self.result = result
        self.progress = 100
        
        if self.on_complete:
            try:
                self.on_complete(self)
            except Exception as e:
                logger.error(f"任务完成回调执行错误: {str(e)}")
    
    def fail(self, error):
        """任务失败"""
        self.status = TaskStatus.FAILED
        self.completed_at = datetime.now()
        self.error = error
        
        if self.on_error:
            try:
                self.on_error(self)
            except Exception as e:
                logger.error(f"任务错误回调执行错误: {str(e)}")
    
    def cancel(self):
        """取消任务"""
        self.status = TaskStatus.CANCELLED
        self.completed_at = datetime.now()
        
        if self.on_error:
            try:
                self.on_error(self)
            except Exception as e:
                logger.error(f"任务取消回调执行错误: {str(e)}")
    
    def update_progress(self, current, total, elapsed):
        """更新进度"""
        if total > 0:
            self.progress = min(int(current * 100 / total), 100)
        else:
            self.progress = 0
        
        if self.on_progress:
            try:
                self.on_progress(self, current, total, elapsed)
            except Exception as e:
                logger.error(f"进度回调执行错误: {str(e)}")
    
    def should_retry(self):
        """判断是否应该重试"""
        return self.retries < self.max_retries
    
    @property
    def duration(self):
        """获取任务持续时间（秒）"""
        if not self.started_at:
            return 0
        
        end_time = self.completed_at or datetime.now()
        return (end_time - self.started_at).total_seconds()
    
    def __lt__(self, other):
        """比较方法，用于优先队列排序"""
        if self.priority != other.priority:
            return self.priority.value < other.priority.value
        return self.created_at < other.created_at

class TransferQueue:
    """传输队列，管理FTP任务"""
    
    def __init__(self, max_concurrent_tasks=3, auto_retry=True, retry_delay=5):
        self.task_queue = queue.PriorityQueue()
        self.active_tasks = {}
        self.completed_tasks = {}
        self.failed_tasks = {}
        self.max_concurrent_tasks = max_concurrent_tasks
        self.auto_retry = auto_retry
        self.retry_delay = retry_delay
        self.running = False
        self.lock = threading.RLock()
        self.workers = []
        self._shutdown_event = threading.Event()
        
        logger.info(f"传输队列已初始化，最大并发任务数: {max_concurrent_tasks}, 自动重试: {auto_retry}")
    
    def start(self):
        """启动队列处理"""
        if self.running:
            return
        
        self.running = True
        self._shutdown_event.clear()
        
        # 创建工作线程
        for i in range(self.max_concurrent_tasks):
            worker = threading.Thread(
                target=self._worker_thread,
                name=f"FTP-Worker-{i+1}",
                daemon=True
            )
            self.workers.append(worker)
            worker.start()
        
        logger.info(f"已启动 {self.max_concurrent_tasks} 个工作线程")
    
    def stop(self):
        """停止队列处理"""
        if not self.running:
            return
        
        logger.info("正在停止传输队列...")
        self.running = False
        self._shutdown_event.set()
        
        # 等待所有线程结束
        for worker in self.workers:
            if worker.is_alive():
                worker.join(timeout=1.0)
        
        self.workers = []
        logger.info("传输队列已停止")
    
    def add_task(self, task):
        """
        添加任务到队列
        
        Args:
            task (Task): 要添加的任务
            
        Returns:
            str: 任务ID
        """
        with self.lock:
            self.task_queue.put(task)
            logger.debug(f"任务已添加到队列: {task.id} 类型: {task.type.name}")
        return task.id
    
    def cancel_task(self, task_id):
        """
        取消任务
        
        Args:
            task_id (str): 任务ID
            
        Returns:
            bool: 是否成功取消
        """
        with self.lock:
            # 检查活动任务
            if task_id in self.active_tasks:
                task = self.active_tasks[task_id]
                task.cancel()
                self.failed_tasks[task_id] = task
                del self.active_tasks[task_id]
                logger.info(f"已取消活动任务: {task_id}")
                return True
            
            # 无法取消已完成或失败的任务
            if task_id in self.completed_tasks or task_id in self.failed_tasks:
                logger.warning(f"无法取消已完成或失败的任务: {task_id}")
                return False
        
        # 如果是队列中的任务，需要遍历优先队列（较复杂）
        # 简单起见，这里不实现队列中任务的取消
        logger.warning(f"无法取消队列中的任务: {task_id}")
        return False
    
    def get_task_status(self, task_id):
        """
        获取任务状态
        
        Args:
            task_id (str): 任务ID
            
        Returns:
            Task: 任务对象，如果不存在返回None
        """
        with self.lock:
            if task_id in self.active_tasks:
                return self.active_tasks[task_id]
            if task_id in self.completed_tasks:
                return self.completed_tasks[task_id]
            if task_id in self.failed_tasks:
                return self.failed_tasks[task_id]
        return None
    
    def get_all_tasks(self):
        """
        获取所有任务状态
        
        Returns:
            dict: 包含活动、完成、失败任务和队列大小的字典
        """
        with self.lock:
            return {
                'active': dict(self.active_tasks),
                'completed': dict(self.completed_tasks),
                'failed': dict(self.failed_tasks),
                'queue_size': self.task_queue.qsize()
            }
    
    def _worker_thread(self):
        """工作线程函数，处理队列中的任务"""
        thread_name = threading.current_thread().name
        logger.debug(f"{thread_name} 已启动")
        
        while self.running:
            try:
                # 获取任务，设置超时以便定期检查running标志
                try:
                    task = self.task_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # 检查是否应该关闭
                if self._shutdown_event.is_set():
                    self.task_queue.put(task)  # 放回队列
                    break
                
                # 更新任务状态并加入活动任务列表
                with self.lock:
                    task.start()
                    self.active_tasks[task.id] = task
                
                logger.info(f"{thread_name} 开始执行任务: {task.id} 类型: {task.type.name}")
                
                # 执行任务
                try:
                    result = task.func(*task.args, **task.kwargs)
                    
                    # 更新任务状态
                    with self.lock:
                        task.complete(result)
                        if task.id in self.active_tasks:
                            del self.active_tasks[task.id]
                        self.completed_tasks[task.id] = task
                    
                    logger.info(f"{thread_name} 完成任务: {task.id}")
                    
                except Exception as e:
                    logger.error(f"{thread_name} 执行任务时出错: {task.id}, {str(e)}")
                    
                    # 更新任务状态
                    with self.lock:
                        if self.auto_retry and task.should_retry():
                            # 重试任务
                            task.retries += 1
                            task.status = TaskStatus.PENDING
                            logger.info(f"{thread_name} 任务将重试: {task.id}, 重试次数: {task.retries}")
                            
                            # 延迟一段时间再放入队列
                            time.sleep(self.retry_delay)
                            self.task_queue.put(task)
                            
                            if task.id in self.active_tasks:
                                del self.active_tasks[task.id]
                        else:
                            # 任务失败，不再重试
                            task.fail(e)
                            if task.id in self.active_tasks:
                                del self.active_tasks[task.id]
                            self.failed_tasks[task.id] = task
                
                # 标记任务完成
                self.task_queue.task_done()
                
            except Exception as e:
                logger.error(f"{thread_name} 处理任务过程中出错: {str(e)}")
                # 继续循环，不让线程退出
        
        logger.debug(f"{thread_name} 已停止")

class AdvancedFTPClient:
    """
    高级FTP客户端，提供任务队列、批量传输等功能
    """
    
    def __init__(self, max_concurrent_tasks=5):
        """
        初始化高级FTP客户端
        
        Args:
            max_concurrent_tasks (int): 最大并发任务数
        """
        self.ftp_client = None
        self.transfer_queue = TransferQueue(max_concurrent_tasks)
        self.transfer_queue.start()
        self.connected = False
        self._connection_lock = threading.RLock()
        self._keep_alive_timer = None
        self._keep_alive_interval = 60  # 默认60秒发送一次保活命令
        
        # 连接选项
        self.retry_count = 3
        self.retry_delay = 5
        self.timeout = 30
        self.keep_alive = False
    
    def set_connection_options(self, retry_count=3, retry_delay=5, timeout=30, keep_alive=False):
        """
        设置连接选项
        
        Args:
            retry_count (int): 重试次数
            retry_delay (int): 重试延迟（秒）
            timeout (int): 超时时间（秒）
            keep_alive (bool): 是否启用保活机制
        """
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.timeout = timeout
        self.keep_alive = keep_alive
    
    def _create_ftp_client(self, enable_ssl=False):
        """
        创建FTP客户端
        
        Args:
            enable_ssl (bool): 是否启用SSL/TLS
            
        Returns:
            FTPClient: FTP客户端实例
        """
        try:
            # 创建新的FTP客户端
            client = FTPClient(timeout=self.timeout, enable_ssl=enable_ssl)
            return client
        except Exception as e:
            logger.error(f"创建FTP客户端失败: {str(e)}")
            raise ConnectionError(f"创建FTP客户端连接失败: {str(e)}")
    
    def _get_ftp_client(self):
        """
        获取FTP客户端实例，如果不存在则创建
        
        Returns:
            FTPClient: FTP客户端实例
        """
        with self._connection_lock:
            if not self.ftp_client or not self.connected:
                raise ConnectionError("未连接到FTP服务器")
            return self.ftp_client
    
    def _start_keep_alive(self):
        """启动保活机制"""
        if not self.keep_alive:
            return
            
        if self._keep_alive_timer:
            self._keep_alive_timer.cancel()
            
        self._keep_alive_timer = threading.Timer(self._keep_alive_interval, self._send_keep_alive)
        self._keep_alive_timer.daemon = True
        self._keep_alive_timer.start()
    
    def _send_keep_alive(self):
        """发送保活命令"""
        try:
            if self.connected and self.ftp_client:
                # 发送无害的命令保持连接
                with self._connection_lock:
                    self.ftp_client._send_command("NOOP")
                    self.ftp_client._read_response()
            # 安排下一次保活
            self._start_keep_alive()
        except Exception as e:
            logger.debug(f"保活命令失败: {str(e)}")
            # 如果保活失败，不重新安排，连接可能已断开
    
    def connect(self, host, port=21, username="anonymous", password="", enable_ssl=False, passive_mode=True):
        """
        连接到FTP服务器
        
        Args:
            host (str): FTP服务器主机名或IP
            port (int): FTP服务器端口
            username (str): 用户名
            password (str): 密码
            enable_ssl (bool): 是否启用SSL/TLS
            passive_mode (bool): 是否使用被动模式
            
        Returns:
            bool: 连接成功返回True
        """
        with self._connection_lock:
            # 如果已经连接，先断开
            if self.connected and self.ftp_client:
                try:
                    self.ftp_client.quit()
                except Exception:
                    pass
                self.ftp_client = None
                self.connected = False
            
            # 创建新的FTP客户端连接
            retry_count = 0
            last_error = None
            
            while retry_count <= self.retry_count:
                try:
                    # 创建FTP客户端
                    self.ftp_client = self._create_ftp_client(enable_ssl)
                    
                    # 设置连接参数
                    self.ftp_client.host = host
                    self.ftp_client.port = port
                    
                    # 连接服务器
                    self.ftp_client.connect()
                    
                    # 设置传输模式
                    if passive_mode:
                        self.ftp_client.set_connection_mode(ConnectionMode.PASSIVE)
                    else:
                        self.ftp_client.set_connection_mode(ConnectionMode.ACTIVE)
                    
                    # 登录
                    self.ftp_client.login(username, password)
                    
                    # 连接成功
                    self.connected = True
                    logger.info(f"已连接到FTP服务器 {host}:{port}")
                    
                    # 启动保活机制
                    if self.keep_alive:
                        self._start_keep_alive()
                    
                    return True
                    
                except Exception as e:
                    last_error = e
                    logger.warning(f"连接尝试 {retry_count+1}/{self.retry_count+1} 失败: {str(e)}")
                    retry_count += 1
                    
                    if retry_count <= self.retry_count:
                        time.sleep(self.retry_delay)
            
            # 所有重试都失败
            logger.error(f"连接到FTP服务器失败，已重试 {self.retry_count} 次: {str(last_error)}")
            raise last_error
    
    def disconnect(self):
        """
        断开与FTP服务器的连接
        
        Returns:
            bool: 断开成功返回True
        """
        with self._connection_lock:
            # 停止保活定时器
            if self._keep_alive_timer:
                self._keep_alive_timer.cancel()
                self._keep_alive_timer = None
            
            # 断开连接
            if self.connected and self.ftp_client:
                try:
                    self.ftp_client.quit()
                    logger.info("已断开FTP连接")
                except Exception as e:
                    logger.warning(f"断开连接时出错: {str(e)}")
                finally:
                    self.ftp_client = None
                    self.connected = False
            
            return True
    
    def cleanup(self):
        """清理资源"""
        self.disconnect()
        self.transfer_queue.stop()
    
    def list_directory(self, remote_path=None, on_complete=None, on_error=None):
        """
        列出目录内容
        
        Args:
            remote_path (str, optional): 要列出的远程目录路径
            on_complete (callable): 完成回调函数
            on_error (callable): 错误回调函数
            
        Returns:
            str: 任务ID
        """
        def task_func(remote_path=None):
            client = self._get_ftp_client()
            
            if remote_path:
                # 切换到指定目录
                client.cwd(remote_path)
            else:
                # 获取当前目录
                remote_path = client.pwd()
            
            # 列出目录内容
            items = client.list()
            
            return {
                'success': True,
                'remote_path': remote_path,
                'listing': items
            }
        
        task = Task(
            task_type=TaskType.LIST,
            func=task_func,
            args=[remote_path],
            priority=TaskPriority.HIGH
        )
        
        task.on_complete = on_complete
        task.on_error = on_error
        
        return self.transfer_queue.add_task(task)
    
    def mkdir(self, remote_path, on_complete=None, on_error=None):
        """
        创建远程目录
        
        Args:
            remote_path (str): 要创建的目录路径
            on_complete (callable): 完成回调函数
            on_error (callable): 错误回调函数
            
        Returns:
            str: 任务ID
        """
        def task_func(remote_path):
            client = self._get_ftp_client()
            
            try:
                # 创建目录
                result = client.mkd(remote_path)
                
                return {
                    'success': True,
                    'remote_path': remote_path,
                    'result': result
                }
            except Exception as e:
                # 如果目录已存在，则认为成功
                if "directory already exists" in str(e).lower():
                    return {
                        'success': True,
                        'remote_path': remote_path,
                        'result': remote_path,
                        'note': 'Directory already exists'
                    }
                raise
        
        task = Task(
            task_type=TaskType.MKDIR,
            func=task_func,
            args=[remote_path],
            priority=TaskPriority.NORMAL
        )
        
        task.on_complete = on_complete
        task.on_error = on_error
        
        return self.transfer_queue.add_task(task)
    
    def rmdir(self, remote_path, on_complete=None, on_error=None):
        """
        删除远程目录
        
        Args:
            remote_path (str): 要删除的目录路径
            on_complete (callable): 完成回调函数
            on_error (callable): 错误回调函数
            
        Returns:
            str: 任务ID
        """
        def task_func(remote_path):
            client = self._get_ftp_client()
            
            # 删除目录
            result = client.rmd(remote_path)
            
            return {
                'success': True,
                'remote_path': remote_path,
                'result': result
            }
        
        task = Task(
            task_type=TaskType.RMDIR,
            func=task_func,
            args=[remote_path],
            priority=TaskPriority.NORMAL
        )
        
        task.on_complete = on_complete
        task.on_error = on_error
        
        return self.transfer_queue.add_task(task)
    
    def download(self, remote_path, local_path, priority=TaskPriority.NORMAL, 
                verify=False, resume=False, on_progress=None, on_complete=None, on_error=None):
        """
        下载文件
        
        Args:
            remote_path (str): 远程文件路径
            local_path (str): 本地保存路径
            priority (TaskPriority): 任务优先级
            verify (bool): 是否验证文件完整性
            resume (bool): 是否断点续传
            on_progress (callable): 进度回调函数
            on_complete (callable): 完成回调函数
            on_error (callable): 错误回调函数
            
        Returns:
            str: 任务ID
        """
        def task_func(remote_path, local_path, verify, resume):
            client = self._get_ftp_client()
            
            # 确保本地目录存在
            os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
            
            # 设置进度回调
            def progress_callback(transferred, total, elapsed):
                if task:
                    task.update_progress(transferred, total, elapsed)
            
            client.set_progress_callback(progress_callback)
            
            # 下载文件
            success, size, duration = client.download(
                remote_path=remote_path,
                local_path=local_path,
                verify=verify,
                resume=resume
            )
            
            return {
                'success': success,
                'remote_path': remote_path,
                'local_path': local_path,
                'size': size,
                'duration': duration,
                'speed': size / duration if duration > 0 else 0
            }
        
        task = Task(
            task_type=TaskType.DOWNLOAD,
            func=task_func,
            args=[remote_path, local_path, verify, resume],
            priority=priority
        )
        
        task.on_progress = on_progress
        task.on_complete = on_complete
        task.on_error = on_error
        
        return self.transfer_queue.add_task(task)
    
    def upload(self, local_path, remote_path, priority=TaskPriority.NORMAL, 
              verify=False, resume=False, on_progress=None, on_complete=None, on_error=None):
        """
        上传文件
        
        Args:
            local_path (str): 本地文件路径
            remote_path (str): 远程保存路径
            priority (TaskPriority): 任务优先级
            verify (bool): 是否验证文件完整性
            resume (bool): 是否断点续传
            on_progress (callable): 进度回调函数
            on_complete (callable): 完成回调函数
            on_error (callable): 错误回调函数
            
        Returns:
            str: 任务ID
        """
        def task_func(local_path, remote_path, verify, resume):
            client = self._get_ftp_client()
            
            # 设置进度回调
            def progress_callback(transferred, total, elapsed):
                if task:
                    task.update_progress(transferred, total, elapsed)
            
            client.set_progress_callback(progress_callback)
            
            # 上传文件
            success, size, duration = client.upload(
                local_path=local_path,
                remote_path=remote_path,
                verify=verify,
                resume=resume
            )
            
            return {
                'success': success,
                'local_path': local_path,
                'remote_path': remote_path,
                'size': size,
                'duration': duration,
                'speed': size / duration if duration > 0 else 0
            }
        
        task = Task(
            task_type=TaskType.UPLOAD,
            func=task_func,
            args=[local_path, remote_path, verify, resume],
            priority=priority
        )
        
        task.on_progress = on_progress
        task.on_complete = on_complete
        task.on_error = on_error
        
        return self.transfer_queue.add_task(task)
    
    def delete(self, remote_path, on_complete=None, on_error=None):
        """
        删除远程文件
        
        Args:
            remote_path (str): 要删除的文件路径
            on_complete (callable): 完成回调函数
            on_error (callable): 错误回调函数
            
        Returns:
            str: 任务ID
        """
        def task_func(remote_path):
            client = self._get_ftp_client()
            
            # 删除文件
            result = client.delete(remote_path)
            
            return {
                'success': True,
                'remote_path': remote_path,
                'result': result
            }
        
        task = Task(
            task_type=TaskType.DELETE,
            func=task_func,
            args=[remote_path],
            priority=TaskPriority.NORMAL
        )
        
        task.on_complete = on_complete
        task.on_error = on_error
        
        return self.transfer_queue.add_task(task)
    
    def rename(self, from_path, to_path, on_complete=None, on_error=None):
        """
        重命名远程文件或目录
        
        Args:
            from_path (str): 原路径
            to_path (str): 新路径
            on_complete (callable): 完成回调函数
            on_error (callable): 错误回调函数
            
        Returns:
            str: 任务ID
        """
        def task_func(from_path, to_path):
            client = self._get_ftp_client()
            
            # 重命名文件或目录
            result = client.rename(from_path, to_path)
            
            return {
                'success': True,
                'from_path': from_path,
                'to_path': to_path,
                'result': result
            }
        
        task = Task(
            task_type=TaskType.RENAME,
            func=task_func,
            args=[from_path, to_path],
            priority=TaskPriority.NORMAL
        )
        
        task.on_complete = on_complete
        task.on_error = on_error
        
        return self.transfer_queue.add_task(task)
    
    def download_directory(self, remote_dir, local_dir, on_progress=None, on_complete=None, on_error=None):
        """
        下载整个目录
        
        Args:
            remote_dir (str): 远程目录路径
            local_dir (str): 本地保存目录路径
            on_progress (callable): 进度回调函数
            on_complete (callable): 完成回调函数
            on_error (callable): 错误回调函数
            
        Returns:
            list: 所有创建的任务的ID列表
        """
        def list_task_func(remote_dir, local_dir):
            client = self._get_ftp_client()
            
            # 首先确保本地目录存在
            os.makedirs(local_dir, exist_ok=True)
            
            # 切换到远程目录
            current_dir = client.pwd()
            client.cwd(remote_dir)
            
            try:
                # 列出目录内容
                items = client.list()
                
                # 为每个项创建下载任务
                task_ids = []
                
                for item in items:
                    name = item.get('name', '')
                    if name in ['.', '..']:
                        continue
                        
                    item_type = item.get('type', 'file')
                    remote_path = os.path.join(remote_dir, name).replace('\\', '/')
                    local_path = os.path.join(local_dir, name)
                    
                    if item_type == 'dir':
                        # 递归下载子目录
                        sub_ids = self.download_directory(
                            remote_dir=remote_path,
                            local_dir=local_path,
                            on_progress=on_progress,
                            on_complete=on_complete,
                            on_error=on_error
                        )
                        task_ids.extend(sub_ids)
                    else:
                        # 下载文件
                        task_id = self.download(
                            remote_path=remote_path,
                            local_path=local_path,
                            on_progress=on_progress,
                            on_complete=on_complete,
                            on_error=on_error
                        )
                        task_ids.append(task_id)
                
                # 恢复原始目录
                client.cwd(current_dir)
                
                return {
                    'success': True,
                    'remote_dir': remote_dir,
                    'local_dir': local_dir,
                    'task_ids': task_ids
                }
            except Exception as e:
                # 发生错误，恢复原始目录
                try:
                    client.cwd(current_dir)
                except Exception:
                    pass
                raise e
        
        task = Task(
            task_type=TaskType.LIST,
            func=list_task_func,
            args=[remote_dir, local_dir],
            priority=TaskPriority.HIGH
        )
        
        task_id = self.transfer_queue.add_task(task)
        # 等待列表任务完成并返回创建的所有下载任务ID
        result = self.wait_for_task(task_id)
        if result and 'task_ids' in result:
            return result['task_ids']
        return []
    
    def upload_directory(self, local_dir, remote_dir, on_progress=None, on_complete=None, on_error=None):
        """
        上传整个目录
        
        Args:
            local_dir (str): 本地目录路径
            remote_dir (str): 远程保存目录路径
            on_progress (callable): 进度回调函数
            on_complete (callable): 完成回调函数
            on_error (callable): 错误回调函数
            
        Returns:
            list: 所有创建的任务的ID列表
        """
        # 确保本地目录存在
        if not os.path.exists(local_dir) or not os.path.isdir(local_dir):
            raise FileNotFoundError(f"本地目录不存在: {local_dir}")
        
        # 先创建远程目录
        mkdir_id = self.mkdir(remote_dir)
        self.wait_for_task(mkdir_id)
        
        # 遍历本地目录
        task_ids = []
        
        for item in os.listdir(local_dir):
            local_path = os.path.join(local_dir, item)
            remote_path = os.path.join(remote_dir, item).replace('\\', '/')
            
            if os.path.isdir(local_path):
                # 递归上传子目录
                sub_ids = self.upload_directory(
                    local_dir=local_path,
                    remote_dir=remote_path,
                    on_progress=on_progress,
                    on_complete=on_complete,
                    on_error=on_error
                )
                task_ids.extend(sub_ids)
            else:
                # 上传文件
                task_id = self.upload(
                    local_path=local_path,
                    remote_path=remote_path,
                    on_progress=on_progress,
                    on_complete=on_complete,
                    on_error=on_error
                )
                task_ids.append(task_id)
        
        return task_ids
    
    def wait_for_task(self, task_id, timeout=None):
        """
        等待任务完成
        
        Args:
            task_id (str): 任务ID
            timeout (float): 超时时间（秒），None表示无限等待
            
        Returns:
            Any: 任务结果，如果失败则返回None
        """
        start_time = time.time()
        
        while True:
            task = self.get_task_status(task_id)
            
            if not task:
                return None
            
            if task.status == TaskStatus.COMPLETE:
                return task.result
            
            if task.status == TaskStatus.FAILED or task.status == TaskStatus.CANCELLED:
                return None
            
            # 检查超时
            if timeout is not None and time.time() - start_time > timeout:
                return None
            
            # 等待一段时间再检查
            time.sleep(0.1)
    
    def wait_all(self, timeout=None):
        """
        等待所有任务完成
        
        Args:
            timeout (float): 超时时间（秒），None表示无限等待
            
        Returns:
            bool: 是否所有任务都成功完成
        """
        start_time = time.time()
        
        while True:
            tasks = self.get_all_tasks()
            
            # 如果没有活动任务且队列为空，则完成
            if len(tasks['active']) == 0 and tasks['queue_size'] == 0:
                return True
            
            # 检查超时
            if timeout is not None and time.time() - start_time > timeout:
                return False
            
            # 等待一段时间再检查
            time.sleep(0.5)
    
    def get_task_status(self, task_id):
        """
        获取任务状态
        
        Args:
            task_id (str): 任务ID
            
        Returns:
            Task: 任务对象，如果不存在返回None
        """
        return self.transfer_queue.get_task_status(task_id)
    
    def get_all_tasks(self):
        """
        获取所有任务状态
        
        Returns:
            dict: 包含活动、完成、失败任务和队列大小的字典
        """
        return self.transfer_queue.get_all_tasks()
    
    def cancel_task(self, task_id):
        """
        取消任务
        
        Args:
            task_id (str): 任务ID
            
        Returns:
            bool: 是否成功取消
        """
        return self.transfer_queue.cancel_task(task_id)

# 用于方便导入的类型别名
from client.ftp_client import ConnectionMode, TransferMode
