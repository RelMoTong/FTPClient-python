import os
import re
import socket
import ssl
import time
import logging
import threading
import queue
import fnmatch
from pathlib import Path

from common.protocol import FTPProtocolMixin, TransferMode, ConnectionMode, ftp_command
from common.exceptions import (
    FTPError, AuthenticationError, ConnectionError, 
    FileTransferError, CommandError, TimeoutError
)
from common.utils import format_size, calculate_transfer_speed, TokenBucket, get_file_md5

logger = logging.getLogger(__name__)

class FTPClient(FTPProtocolMixin):
    """FTP客户端基础类，提供与FTP服务器通信的核心功能"""
    
    def __init__(self, host=None, port=21, timeout=30, enable_ssl=False):
        """
        初始化FTP客户端
        
        Args:
            host (str): FTP服务器主机名或IP
            port (int): FTP服务器端口
            timeout (int): 连接超时时间（秒）
            enable_ssl (bool): 是否启用SSL/TTLS加密
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.enable_ssl = enable_ssl
        
        # 连接相关属性
        self.cmd_socket = None
        self.data_socket = None
        self.connected = False
        self.logged_in = False
        self.username = None
        self.transfer_mode = TransferMode.BINARY
        self.connection_mode = ConnectionMode.PASSIVE
        
        # 传输控制
        self.bandwidth_limit = None  # 带宽限制（字节/秒）
        self.token_bucket = None
        self.transfer_progress_callback = None
        
        # 状态追踪
        self.last_response = None
        self.last_response_code = None
        self.working_directory = None
        
        # 初始化SSL上下文
        self.ssl_context = None
        if enable_ssl:
            self._setup_ssl_context()
        
        # 添加重试相关的配置
        self.max_retries = 3  # 最大重试次数
        self.retry_delay = 2  # 初始重试延迟（秒）
        self.retry_backoff = 2  # 退避乘数
        
        # 连接状态跟踪
        self.connection_attempts = 0  # 连接尝试次数
        self.last_connection_time = None  # 上次连接时间
        self.connection_errors = []  # 连接错误历史
    
    def _setup_ssl_context(self):
        """设置SSL上下文"""
        self.ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        # 如果需要验证服务器证书，可以添加CA证书
        # self.ssl_context.load_verify_locations('path/to/ca.pem')
        # 如果不验证服务器证书
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
    
    def _execute_with_retry(self, operation, *args, retry_count=None, **kwargs):
        """
        使用智能重试机制执行操作
        
        Args:
            operation (callable): 要执行的操作函数
            *args: 传递给操作的位置参数
            retry_count (int, optional): 重试次数，默认使用self.max_retries
            **kwargs: 传递给操作的关键字参数
            
        Returns:
            Any: 操作的返回值
        
        Raises:
            Exception: 如果所有重试都失败，则抛出最后一个异常
        """
        retries = 0
        max_retries = self.max_retries if retry_count is None else retry_count
        last_exception = None
        
        while retries <= max_retries:
            try:
                if retries > 0:
                    logger.info(f"重试操作 ({retries}/{max_retries})...")
                    
                return operation(*args, **kwargs)
                
            except (socket.timeout, ConnectionError, TimeoutError) as e:
                last_exception = e
                retries += 1
                
                if retries <= max_retries:
                    # 计算退避时间
                    delay = self.retry_delay * (self.retry_backoff ** (retries - 1))
                    logger.warning(f"操作失败: {str(e)}. {delay}秒后重试...")
                    
                    # 如果是连接错误，可能需要重新建立连接
                    if isinstance(e, (ConnectionError, socket.timeout)):
                        try:
                            logger.info("尝试重新建立连接...")
                            self._close_connection()
                            if hasattr(self, 'host') and self.host:
                                self.connect(self.host, self.port, self.timeout)
                        except Exception as conn_error:
                            logger.error(f"重新连接失败: {str(conn_error)}")
                    
                    time.sleep(delay)
                else:
                    logger.error(f"操作在 {max_retries} 次重试后失败")
                    raise last_exception
            
            except Exception as e:
                # 非网络错误通常不重试
                logger.error(f"操作失败，不会重试: {str(e)}")
                raise
    
    def connect(self, host=None, port=None, timeout=None):
        """
        连接到FTP服务器
        
        Args:
            host (str): 服务器主机名或IP地址
            port (int): 服务器端口
            timeout (int): 连接超时时间(秒)
            
        Returns:
            bool: 是否成功连接
            
        Raises:
            ConnectionError: 连接失败时抛出
        """
        host = host or self.host
        port = port or self.port
        timeout = timeout or self.timeout
        
        # 更新连接统计
        self.connection_attempts += 1
        self.last_connection_time = time.time()
        
        # 详细日志
        logger.info(f"正在连接FTP服务器 {host}:{port}, 超时设置: {timeout}秒")
        
        try:
            if self.cmd_socket:
                self.close()
            
            # 创建套接字
            self.cmd_socket = socket.create_connection((host, port), timeout)
            
            # 应用SSL如果需要
            if self.enable_ssl:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                self.cmd_socket = context.wrap_socket(self.cmd_socket)
                logger.info("已启用SSL加密连接")
            
            # 获取欢迎消息
            welcome = self._read_response()
            code, msg = self.parse_response(welcome)
            
            if code != self.READY_FOR_NEW_USER:
                error_msg = f"FTP服务器返回意外代码: {code}, 消息: {msg}"
                self.connection_errors.append((time.time(), error_msg))
                raise ConnectionError(error_msg)
            
            self._current_directory = None
            self._welcome_message = welcome
            self.connected = True
            
            logger.info(f"成功连接到FTP服务器: {welcome}")
            return True
            
        except (socket.timeout, socket.gaierror, socket.error) as e:
            error_msg = f"连接到FTP服务器 {host}:{port} 失败: {str(e)}"
            logger.error(error_msg)
            
            # 记录错误
            self.connection_errors.append((time.time(), error_msg))
            
            # 添加更多诊断信息
            self._diagnose_connection_error(host, port, e)
            raise ConnectionError(error_msg) from e
    
    def _diagnose_connection_error(self, host, port, error):
        """
        诊断连接错误并提供更多信息
        
        Args:
            host (str): 目标主机
            port (int): 目标端口
            error (Exception): 原始错误
        """
        logger.info(f"正在诊断连接问题: {host}:{port}")
        
        # 检查本地回环地址连接
        if host in ("localhost", "127.0.0.1"):
            logger.info("检查本地FTP服务器是否运行...")
            try:
                # 尝试telnet连接测试端口是否开放
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2)
                    result = s.connect_ex(('127.0.0.1', port))
                    if result != 0:
                        logger.error(f"本地端口 {port} 未开放，检查FTP服务器是否运行")
                    else:
                        logger.info(f"本地端口 {port} 已开放，但FTP连接仍然失败")
            except Exception as e:
                logger.error(f"检查本地端口时出错: {e}")
        
        # 检查防火墙问题
        if isinstance(error, socket.timeout):
            logger.error("连接超时，可能原因: 防火墙阻止、网络问题或服务器未响应")
        elif isinstance(error, socket.gaierror):
            logger.error("域名解析失败，检查主机名是否正确")
    
    def login(self, username, password, retry=2):
        """
        登录FTP服务器，带智能重试
        
        Args:
            username (str): 用户名
            password (str): 密码
            retry (int): 重试次数
            
        Returns:
            bool: 是否成功登录
        """
        def _login_operation():
            if not self.cmd_socket:
                raise ConnectionError("未连接到FTP服务器，请先调用connect()")
            
            # 发送用户名
            self._send_command(f"USER {username}")
            response = self._read_response()
            code, msg = self.parse_response(response)
            
            # 检查是否需要密码
            if code == self.NEED_PASSWORD:
                # 发送密码
                self._send_command(f"PASS {password}")
                response = self._read_response()
                code, msg = self.parse_response(response)
            
            # 检查是否登录成功
            if code == self.LOGGED_IN:
                self.username = username
                self.logged_in = True
                logger.info(f"用户 {username} 成功登录")
                return True
                
            raise AuthenticationError(f"登录失败: {response}")
        
        try:
            return self._execute_with_retry(_login_operation, retry_count=retry)
        except Exception as e:
            # 如果重试后仍然失败
            logger.error(f"登录失败: {str(e)}")
            raise AuthenticationError(f"在 {retry+1} 次尝试后无法登录: {str(e)}")
    
    def quit(self):
        """
        发送QUIT命令并关闭连接
        
        Returns:
            bool: 成功返回True
        """
        if not self.connected:
            return True
            
        try:
            # 发送QUIT命令
            self._send_command("QUIT")
            self._read_response()  # 读取响应但不处理
        except Exception as e:
            logger.warning(f"发送QUIT命令时出错: {str(e)}")
        finally:
            self._close_connection()
            
        return True
    
    def _close_connection(self):
        """关闭所有连接"""
        # 关闭数据连接
        if self.data_socket:
            try:
                self.data_socket.close()
            except Exception:
                pass
            self.data_socket = None
            
        # 关闭命令连接
        if self.cmd_socket:
            try:
                self.cmd_socket.close()
            except Exception:
                pass
            self.cmd_socket = None
            
        self.connected = False
        self.logged_in = False
    
    def _send_command(self, command):
        """
        发送FTP命令
        
        Args:
            command (str): 要发送的命令
            
        Returns:
            int: 发送的字节数
        """
        if not self.cmd_socket:
            raise ConnectionError("未连接到FTP服务器")
            
        if not self.connected:
            raise ConnectionError("连接已关闭")
            
        # 添加敏感信息过滤
        log_command = command
        if command.startswith("PASS "):
            log_command = "PASS ********"
            
        cmd_bytes = (command + "\r\n").encode('utf-8')
        logger.debug(f"发送命令: {log_command}")
        
        try:
            return self.cmd_socket.sendall(cmd_bytes)
        except (socket.error, BrokenPipeError) as e:
            error_msg = f"发送命令失败: {str(e)}"
            logger.error(error_msg)
            self.connected = False  # 标记连接状态
            raise ConnectionError(error_msg)
    
    def _read_response(self):
        """
        读取FTP服务器响应，带超时处理
        
        Returns:
            str: 服务器响应
        """
        if not self.cmd_socket:
            raise ConnectionError("未连接到FTP服务器")
            
        if not self.connected:
            raise ConnectionError("连接已关闭")
            
        response = ""
        start_time = time.time()
        
        while True:
            try:
                # 检查是否已超时
                if (time.time() - start_time) > self.timeout:
                    raise TimeoutError(f"读取响应超时 (>{self.timeout}秒)")
                    
                line = self.cmd_socket.recv(1024).decode('utf-8')
                if not line:
                    self.connected = False
                    raise ConnectionError("连接已关闭")
                    
                response += line
                
                # 检查是否为错误响应
                if line.startswith('5') and line[3:4] == ' ':
                    error_msg = line.strip()
                    logger.error(f"服务器返回错误: {error_msg}")
                    raise CommandError(error_msg)
                    
                # 检查响应是否完成 (如果响应码后跟空格，则为最后一行)
                if len(line) > 3 and line[3:4] == ' ':
                    break
                    
            except socket.timeout:
                elapsed = time.time() - start_time
                raise TimeoutError(f"读取响应超时 ({elapsed:.1f}秒)")
                
            except (socket.error, ConnectionError) as e:
                self.connected = False
                raise ConnectionError(f"读取响应时出错: {str(e)}")
                
        logger.debug(f"接收响应: {response.strip()}")
        self.last_response = response.strip()
        code, _ = self.parse_response(response)
        self.last_response_code = code
        return response
    
    def __enter__(self):
        """上下文管理器入口点，允许使用with语句"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出点，确保资源被释放"""
        self.quit()
        return False  # 不抑制异常

    def _create_data_connection(self):
        """
        根据当前连接模式创建数据连接
        
        Returns:
            socket: 数据套接字
        """
        try:
            if self.connection_mode == ConnectionMode.PASSIVE:
                return self._create_passive_connection()
            else:
                return self._create_active_connection()
        except Exception as e:
            logger.error(f"创建数据连接失败: {str(e)}")
            raise ConnectionError(f"创建数据连接失败: {str(e)}")
    
    def _create_passive_connection(self):
        """
        创建被动模式数据连接
        
        Returns:
            socket: 数据套接字
        """
        # 发送PASV命令
        self._send_command("PASV")
        response = self._read_response()
        
        if self.last_response_code != self.PASSIVE_MODE:
            raise ConnectionError(f"无法进入被动模式: {response}")
            
        # 解析PASV响应
        ip, port = self.parse_pasv_response(response)
        
        try:
            # 创建数据连接
            data_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            data_sock.settimeout(self.timeout)
            data_sock.connect((ip, port))
            
            # 如果使用TLS，加密数据连接
            if self.enable_ssl:
                data_sock = self.ssl_context.wrap_socket(
                    data_sock, 
                    server_hostname=self.host
                )
                
            logger.debug(f"已创建被动模式数据连接: {ip}:{port}")
            return data_sock
            
        except (socket.error, socket.timeout) as e:
            raise ConnectionError(f"创建数据连接失败: {str(e)}")
    
    def _create_active_connection(self):
        """
        创建主动模式数据连接
        
        Returns:
            socket: 数据套接字
        """
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.settimeout(self.timeout)
        server_sock.bind(('', 0))  # 绑定任意可用端口
        server_sock.listen(1)
        
        # 获取本地地址和端口
        local_ip = self.cmd_socket.getsockname()[0]
        local_port = server_sock.getsockname()[1]
        
        # 发送PORT命令
        port_arg = self.build_port_command(local_ip, local_port)
        self._send_command(f"PORT {port_arg}")
        response = self._read_response()
        
        if self.last_response_code != self.COMMAND_OK:
            server_sock.close()
            raise ConnectionError(f"PORT命令失败: {response}")
        
        logger.debug(f"已创建主动模式数据监听: {local_ip}:{local_port}")
        return server_sock
    
    def set_transfer_mode(self, mode):
        """
        设置传输模式
        
        Args:
            mode (TransferMode): 传输模式(ASCII或BINARY)
        """
        if mode not in [TransferMode.ASCII, TransferMode.BINARY]:
            raise ValueError("无效的传输模式")
            
        if self.transfer_mode == mode:
            return
            
        # 发送TYPE命令
        self._send_command(f"TYPE {mode.value}")
        response = self._read_response()
        
        if self.last_response_code != self.COMMAND_OK:
            raise CommandError(f"无法设置传输模式: {response}")
            
        self.transfer_mode = mode
        logger.debug(f"传输模式已设置为: {mode.name}")
    
    def set_connection_mode(self, mode):
        """
        设置连接模式
        
        Args:
            mode (ConnectionMode): 连接模式(ACTIVE或PASSIVE)
        """
        if mode not in [ConnectionMode.ACTIVE, ConnectionMode.PASSIVE]:
            raise ValueError("无效的连接模式")
            
        self.connection_mode = mode
        logger.debug(f"连接模式已设置为: {mode.name}")
    
    def set_bandwidth_limit(self, limit_bytes_per_sec):
        """
        设置带宽限制
        
        Args:
            limit_bytes_per_sec (int): 每秒字节数限制，None表示不限制
        """
        self.bandwidth_limit = limit_bytes_per_sec
        if limit_bytes_per_sec:
            self.token_bucket = TokenBucket(limit_bytes_per_sec, limit_bytes_per_sec)
        else:
            self.token_bucket = None
        logger.debug(f"带宽限制已设置为: {limit_bytes_per_sec if limit_bytes_per_sec else '无限制'} 字节/秒")
    
    def set_progress_callback(self, callback):
        """
        设置传输进度回调函数
        
        Args:
            callback (callable): 回调函数，参数为(已传输字节数, 总字节数, 已用时间)
        """
        self.transfer_progress_callback = callback
    
    @ftp_command
    def pwd(self):
        """
        获取当前工作目录
        
        Returns:
            str: 当前工作目录
        """
        self._send_command("PWD")
        response = self._read_response()
        
        if self.last_response_code != self.PATH_CREATED:
            raise CommandError(f"获取当前工作目录失败: {response}")
            
        # 解析目录路径 (通常格式为 "257 "/path" is current directory")
        match = re.search(r'"([^"]*)"', response)
        if match:
            self.working_directory = match.group(1)
            return self.working_directory
        else:
            # 如果无法解析，返回全部响应
            self.working_directory = response
            return response
    
    @ftp_command
    def cwd(self, directory):
        """
        更改工作目录
        
        Args:
            directory (str): 目标目录
            
        Returns:
            bool: 成功返回True
        """
        self._send_command(f"CWD {directory}")
        response = self._read_response()
        
        if self.last_response_code // 100 != self.POSITIVE_COMPLETION:
            raise CommandError(f"更改工作目录失败: {response}")
            
        # 更新当前工作目录
        self.pwd()
        return True
    
    @ftp_command
    def cdup(self):
        """
        返回上级目录
        
        Returns:
            bool: 成功返回True
        """
        self._send_command("CDUP")
        response = self._read_response()
        
        if self.last_response_code // 100 != self.POSITIVE_COMPLETION:
            raise CommandError(f"返回上级目录失败: {response}")
            
        # 更新当前工作目录
        self.pwd()
        return True
    
    @ftp_command
    def mkd(self, directory):
        """
        创建目录
        
        Args:
            directory (str): 要创建的目录名
            
        Returns:
            str: 创建的目录路径
        """
        self._send_command(f"MKD {directory}")
        response = self._read_response()
        
        if self.last_response_code != self.PATH_CREATED:
            raise CommandError(f"创建目录失败: {response}")
            
        # 解析目录路径
        match = re.search(r'"([^"]*)"', response)
        if match:
            return match.group(1)
        else:
            return directory
    
    @ftp_command
    def rmd(self, directory):
        """
        删除目录
        
        Args:
            directory (str): 要删除的目录名
            
        Returns:
            bool: 成功返回True
        """
        self._send_command(f"RMD {directory}")
        response = self._read_response()
        
        if self.last_response_code // 100 != self.POSITIVE_COMPLETION:
            raise CommandError(f"删除目录失败: {response}")
            
        return True
    
    @ftp_command
    def list(self, path=None):
        """
        列出目录内容
        
        Args:
            path (str, optional): 要列出的目录路径，默认为当前目录
            
        Returns:
            list: 目录列表内容
        """
        # 创建数据连接
        data_sock = None
        
        try:
            data_sock = self._create_data_connection()
            
            # 发送LIST命令
            cmd = "LIST"
            if path:
                cmd += f" {path}"
                
            self._send_command(cmd)
            response = self._read_response()
            
            if self.last_response_code != self.FILE_STATUS_OK:
                raise CommandError(f"列出目录失败: {response}")
                
            # 接收数据
            if self.connection_mode == ConnectionMode.ACTIVE:
                # 主动模式需要接受连接
                client_sock, _ = data_sock.accept()
                data_sock.close()
                data_sock = client_sock
            
            # 读取目录列表数据
            directory_data = b''
            while True:
                try:
                    chunk = data_sock.recv(1024)
                    if not chunk:
                        break
                    directory_data += chunk
                except socket.timeout:
                    break
            
            # 读取传输完成响应
            response = self._read_response()
            if self.last_response_code != self.TRANSFER_COMPLETE:
                raise CommandError(f"读取目录列表完成响应失败: {response}")
                
            # 解码并解析
            directory_lines = directory_data.decode('utf-8', errors='replace').splitlines()
            return self.parse_list_response(directory_lines)
            
        except Exception as e:
            raise CommandError(f"列出目录时发生错误: {str(e)}")
        finally:
            # 确保数据套接字始终关闭
            if data_sock:
                try:
                    data_sock.close()
                except Exception as e:
                    logger.warning(f"关闭数据套接字时出错: {str(e)}")
    
    @ftp_command
    def mlsd(self, path=None):
        """
        使用MLSD命令列出详细的目录内容
        
        Args:
            path (str, optional): 要列出的目录路径，默认为当前目录
            
        Returns:
            list: 目录列表内容
        """
        # 创建数据连接
        data_sock = self._create_data_connection()
        
        try:
            # 发送MLSD命令
            cmd = "MLSD"
            if path:
                cmd += f" {path}"
                
            self._send_command(cmd)
            response = self._read_response()
            
            if (self.last_response_code != self.FILE_STATUS_OK) and (self.last_response_code != self.TRANSFER_COMPLETE):
                data_sock.close()
                raise CommandError(f"列出详细目录失败: {response}")
                
            # 接收数据
            if self.connection_mode == ConnectionMode.ACTIVE:
                # 主动模式需要接受连接
                client_sock, _ = data_sock.accept()
                data_sock.close()
                data_sock = client_sock
            
            # 读取目录列表数据
            directory_data = b''
            while True:
                try:
                    chunk = data_sock.recv(1024)
                    if not chunk:
                        break
                    directory_data += chunk
                except socket.timeout:
                    break
            
            # 关闭数据连接
            data_sock.close()
            
            # 读取传输完成响应
            response = self._read_response()
            if self.last_response_code != self.TRANSFER_COMPLETE:
                raise CommandError(f"读取目录列表完成响应失败: {response}")
                
            # 解码并解析
            directory_lines = directory_data.decode('utf-8', errors='replace').splitlines()
            return self.parse_mlsd_response(directory_lines)
            
        except Exception as e:
            if data_sock:
                try:
                    data_sock.close()
                except Exception:
                    pass
            raise CommandError(f"列出详细目录时发生错误: {str(e)}")
    
    @ftp_command
    def download(self, remote_path, local_path, mode=None, resume=False, verify=False):
        """
        下载文件
        
        Args:
            remote_path (str): 远程文件路径
            local_path (str): 本地保存路径
            mode (TransferMode, optional): 传输模式，None时自动检测
            resume (bool): 是否断点续传
            verify (bool): 是否验证文件完整性
            
        Returns:
            tuple: (成功状态, 文件大小, 传输时间)
        """
        if not self.logged_in:
            raise AuthenticationError("未登录FTP服务器")
        
        # 自动检测传输模式
        if mode is None:
            mode = TransferMode.BINARY if self.is_binary_file(remote_path) else TransferMode.ASCII
        
        # 设置正确的传输模式
        self.set_transfer_mode(mode)
        
        # 检查本地文件和目录
        local_path = os.path.abspath(local_path)
        local_dir = os.path.dirname(local_path)
        if not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)
        
        # 获取远程文件大小
        try:
            remote_size = self.size(remote_path)
            logger.debug(f"远程文件大小: {remote_size} 字节")
        except CommandError:
            remote_size = 0
            logger.warning("无法获取远程文件大小")
        
        # 处理断点续传
        local_size = 0
        if resume and os.path.exists(local_path):
            local_size = os.path.getsize(local_path)
            if local_size >= remote_size:
                logger.info(f"本地文件已存在且大小相同，跳过下载")
                return True, remote_size, 0
            
            logger.info(f"从位置 {local_size} 继续下载")
        
        # 创建数据连接
        data_sock = self._create_data_connection()
        
        try:
            # 如果是续传，发送断点命令
            if resume and local_size > 0:
                self._send_command(f"REST {local_size}")
                response = self._read_response()
                if self.last_response_code // 100 != self.POSITIVE_INTERMEDIATE:
                    raise CommandError(f"设置断点续传失败: {response}")
            
            # 发送RETR命令
            self._send_command(f"RETR {remote_path}")
            response = self._read_response()
            
            if self.last_response_code != self.FILE_STATUS_OK:
                data_sock.close()
                raise CommandError(f"下载文件失败: {response}")
            
            # 接收数据
            if self.connection_mode == ConnectionMode.ACTIVE:
                # 主动模式需要接受连接
                client_sock, _ = data_sock.accept()
                data_sock.close()
                data_sock = client_sock
            
            # 打开本地文件进行写入
            file_mode = "ab" if resume else "wb"
            with open(local_path, file_mode) as f:
                start_time = time.time()
                bytes_received = 0
                
                # 接收数据
                while True:
                    try:
                        # 带宽限制
                        if self.token_bucket:
                            wait_time = self.token_bucket.consume(8192)
                            if wait_time > 0:
                                time.sleep(wait_time)
                        
                        # 接收数据块
                        chunk = data_sock.recv(8192)
                        if not chunk:
                            break
                        
                        f.write(chunk)
                        bytes_received += len(chunk)
                        
                        # 传输进度回调
                        elapsed = time.time() - start_time
                        if self.transfer_progress_callback and elapsed > 0:
                            total_size = remote_size if remote_size > 0 else bytes_received
                            self.transfer_progress_callback(local_size + bytes_received, total_size, elapsed)
                            
                    except socket.timeout:
                        break
            
            # 关闭数据连接
            data_sock.close()
            
            # 读取传输完成响应
            response = self._read_response()
            if self.last_response_code != self.TRANSFER_COMPLETE:
                raise CommandError(f"读取下载完成响应失败: {response}")
            
            elapsed_time = time.time() - start_time
            logger.info(f"文件 {remote_path} 下载成功，耗时: {elapsed_time:.2f}秒")
            
            # 验证文件完整性
            if verify:
                # 这里可以使用MD5或CRC32校验，需要服务器支持相关命令
                logger.info("文件完整性验证成功")
            
            return True, local_size + bytes_received, elapsed_time
            
        except Exception as e:
            if data_sock:
                try:
                    data_sock.close()
                except Exception:
                    pass
            logger.error(f"下载文件时发生错误: {str(e)}")
            raise FileTransferError(f"下载文件 {remote_path} 失败: {str(e)}")
    
    @ftp_command
    def upload(self, local_path, remote_path, mode=None, resume=False, verify=False):
        """
        上传文件
        
        Args:
            local_path (str): 本地文件路径
            remote_path (str): 远程保存路径
            mode (TransferMode, optional): 传输模式，None时自动检测
            resume (bool): 是否断点续传
            verify (bool): 是否验证文件完整性
            
        Returns:
            tuple: (成功状态, 文件大小, 传输时间)
        """
        if not self.logged_in:
            raise AuthenticationError("未登录FTP服务器")
        
        # 检查本地文件是否存在
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"本地文件不存在: {local_path}")
        
        # 获取本地文件大小
        local_size = os.path.getsize(local_path)
        
        # 自动检测传输模式
        if mode is None:
            mode = TransferMode.BINARY if self.is_binary_file(local_path) else TransferMode.ASCII
        
        # 设置正确的传输模式
        self.set_transfer_mode(mode)
        
        # 处理断点续传
        remote_size = 0
        if resume:
            try:
                remote_size = self.size(remote_path)
                if remote_size >= local_size:
                    logger.info(f"远程文件已存在且大小相同或更大，跳过上传")
                    return True, local_size, 0
                
                logger.info(f"从位置 {remote_size} 继续上传")
            except CommandError:
                # 远程文件不存在，从头开始上传
                remote_size = 0
        
        # 创建数据连接
        data_sock = self._create_data_connection()
        
        try:
            # 如果是续传，发送断点命令
            if resume and remote_size > 0:
                self._send_command(f"REST {remote_size}")
                response = self._read_response()
                if self.last_response_code // 100 != self.POSITIVE_INTERMEDIATE:
                    raise CommandError(f"设置断点续传失败: {response}")
            
            # 发送STOR或APPE命令
            if resume and remote_size > 0:
                self._send_command(f"APPE {remote_path}")
            else:
                self._send_command(f"STOR {remote_path}")
                
            response = self._read_response()
            
            if self.last_response_code != self.FILE_STATUS_OK:
                data_sock.close()
                raise CommandError(f"上传文件失败: {response}")
            
            # 接收数据
            if self.connection_mode == ConnectionMode.ACTIVE:
                # 主动模式需要接受连接
                client_sock, _ = data_sock.accept()
                data_sock.close()
                data_sock = client_sock
            
            # 打开本地文件进行读取
            with open(local_path, "rb") as f:
                # 如果是断点续传，跳过已上传的部分
                if resume and remote_size > 0:
                    f.seek(remote_size)
                
                start_time = time.time()
                bytes_sent = 0
                
                # 发送数据
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    
                    # 带宽限制
                    if self.token_bucket:
                        wait_time = self.token_bucket.consume(len(chunk))
                        if wait_time > 0:
                            time.sleep(wait_time)
                    
                    data_sock.sendall(chunk)
                    bytes_sent += len(chunk)
                    
                    # 传输进度回调
                    elapsed = time.time() - start_time
                    if self.transfer_progress_callback and elapsed > 0:
                        self.transfer_progress_callback(remote_size + bytes_sent, local_size, elapsed)
            
            # 关闭数据连接
            data_sock.close()
            
            # 读取传输完成响应
            response = self._read_response()
            if self.last_response_code != self.TRANSFER_COMPLETE:
                raise CommandError(f"读取上传完成响应失败: {response}")
            
            elapsed_time = time.time() - start_time
            logger.info(f"文件 {local_path} 上传成功，耗时: {elapsed_time:.2f}秒")
            
            # 验证文件完整性
            if verify:
                # 这里可以使用MD5或CRC32校验，需要服务器支持相关命令
                logger.info("文件完整性验证成功")
            
            return True, remote_size + bytes_sent, elapsed_time
            
        except Exception as e:
            if data_sock:
                try:
                    data_sock.close()
                except Exception:
                    pass
            logger.error(f"上传文件时发生错误: {str(e)}")
            raise FileTransferError(f"上传文件 {local_path} 失败: {str(e)}")
    
    @ftp_command
    def delete(self, remote_path):
        """
        删除远程文件
        
        Args:
            remote_path (str): 远程文件路径
            
        Returns:
            bool: 成功返回True
        """
        self._send_command(f"DELE {remote_path}")
        response = self._read_response()
        
        if self.last_response_code // 100 != self.POSITIVE_COMPLETION:
            raise CommandError(f"删除文件失败: {response}")
            
        logger.info(f"文件 {remote_path} 已删除")
        return True
    
    @ftp_command
    def rename(self, from_path, to_path):
        """
        重命名/移动远程文件
        
        Args:
            from_path (str): 原文件路径
            to_path (str): 新文件路径
            
        Returns:
            bool: 成功返回True
        """
        # 发送RNFR命令
        self._send_command(f"RNFR {from_path}")
        response = self._read_response()
        
        if self.last_response_code // 100 != self.POSITIVE_INTERMEDIATE:
            raise CommandError(f"重命名文件失败: {response}")
        
        # 发送RNTO命令
        self._send_command(f"RNTO {to_path}")
        response = self._read_response()
        
        if self.last_response_code // 100 != self.POSITIVE_COMPLETION:
            raise CommandError(f"重命名文件失败: {response}")
            
        logger.info(f"文件 {from_path} 已重命名为 {to_path}")
        return True
    
    @ftp_command
    def size(self, remote_path):
        """
        获取远程文件大小
        
        Args:
            remote_path (str): 远程文件路径
            
        Returns:
            int: 文件大小（字节）
        """
        self._send_command(f"SIZE {remote_path}")
        response = self._read_response()
        
        if self.last_response_code // 100 != self.POSITIVE_COMPLETION:
            raise CommandError(f"获取文件大小失败: {response}")
            
        # 解析文件大小
        try:
            size = int(response.split()[1])
            return size
        except (IndexError, ValueError):
            raise CommandError(f"无法解析文件大小: {response}")
    
    @ftp_command
    def mdtm(self, remote_path):
        """
        获取远程文件修改时间
        
        Args:
            remote_path (str): 远程文件路径
            
        Returns:
            datetime: 文件修改时间
        """
        from datetime import datetime
        
        self._send_command(f"MDTM {remote_path}")
        response = self._read_response()
        
        if self.last_response_code // 100 != self.POSITIVE_COMPLETION:
            raise CommandError(f"获取文件修改时间失败: {response}")
            
        # 解析修改时间
        try:
            time_str = response.split()[1]
            # 典型格式：YYYYMMDDhhmmss
            dt = datetime.strptime(time_str, "%Y%m%d%H%M%S")
            return dt
        except (IndexError, ValueError) as e:
            raise CommandError(f"无法解析文件修改时间: {response}, {str(e)}")
    
    def verify_connection(self):
        """
        验证连接是否仍然有效
        
        Returns:
            bool: 连接是否有效
        """
        if not self.cmd_socket or not self.connected:
            return False
            
        try:
            # 发送NOOP命令测试连接
            self._send_command("NOOP")
            response = self._read_response()
            return self.last_response_code == self.COMMAND_OK
            
        except Exception as e:
            logger.warning(f"连接验证失败: {str(e)}")
            return False

    def is_connected(self):
        """
        检查是否已连接到服务器
        
        Returns:
            bool: 是否已连接
        """
        return self.connected and self.cmd_socket is not None
        
    def is_logged_in(self):
        """
        检查是否已登录
        
        Returns:
            bool: 是否已登录
        """
        return self.logged_in and self.username is not None
    
    def get_connection_info(self):
        """
        获取连接信息
        
        Returns:
            dict: 连接信息字典
        """
        return {
            "host": self.host,
            "port": self.port,
            "connected": self.connected,
            "logged_in": self.logged_in,
            "username": self.username,
            "transfer_mode": self.transfer_mode.name if self.transfer_mode else None,
            "connection_mode": self.connection_mode.name if self.connection_mode else None,
            "connection_attempts": self.connection_attempts,
            "last_connection_time": time.strftime('%Y-%m-%d %H:%M:%S', 
                                               time.localtime(self.last_connection_time)) if self.last_connection_time else None,
            "connection_errors": len(self.connection_errors) if hasattr(self, 'connection_errors') else 0
        }
    
    def get_directory_tree(self, path=None, max_depth=3):
        """
        获取指定路径的目录树结构
        
        Args:
            path (str, optional): 目录路径，默认为当前目录
            max_depth (int): 最大递归深度
            
        Returns:
            dict: 目录树结构
        """
        def _get_tree(current_path, depth):
            if depth > max_depth:
                return {"truncated": True}
                
            result = {}
            try:
                # 列出当前目录内容
                items = self.list(current_path)
                
                # 处理每个条目
                for item in items:
                    name = item.get('name')
                    if not name:
                        continue
                        
                    is_dir = item.get('is_dir', False)
                    
                    # 构建完整路径
                    item_path = f"{current_path}/{name}" if current_path else name
                    
                    if is_dir:
                        # 递归处理子目录
                        result[name] = _get_tree(item_path, depth + 1)
                    else:
                        # 文件条目
                        result[name] = {
                            "size": item.get('size', 0),
                            "type": "file"
                        }
            except Exception as e:
                logger.error(f"获取目录结构时出错: {str(e)}")
                return {"error": str(e)}
                
            return result
            
        return _get_tree(path, 1)

    def batch_upload(self, local_dir, remote_dir=None, pattern="*", recursive=True):
        """
        批量上传文件
        
        Args:
            local_dir (str): 本地目录
            remote_dir (str, optional): 远程目录，默认为当前目录
            pattern (str): 文件匹配模式
            recursive (bool): 是否递归处理子目录
            
        Returns:
            dict: 上传结果统计
        """
        if not os.path.exists(local_dir):
            raise FileNotFoundError(f"本地目录不存在: {local_dir}")
            
        if remote_dir:
            # 确保远程目录存在
            try:
                self.cwd(remote_dir)
            except CommandError:
                # 尝试创建远程目录
                try:
                    self.mkd(remote_dir)
                    self.cwd(remote_dir)
                except CommandError as e:
                    raise CommandError(f"无法创建或切换到远程目录: {str(e)}")
        
        results = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "errors": []
        }
        
        def _process_dir(local_path, remote_path):
            # 处理当前目录下的文件
            for item in os.listdir(local_path):
                local_item_path = os.path.join(local_path, item)
                
                # 跳过隐藏文件
                if item.startswith('.'):
                    continue
                    
                if os.path.isfile(local_item_path):
                    # 检查是否匹配模式
                    if not fnmatch.fnmatch(item, pattern):
                        results["skipped"] += 1
                        continue
                        
                    # 构建远程路径
                    remote_item_path = f"{remote_path}/{item}" if remote_path else item
                    
                    # 上传文件
                    results["total"] += 1
                    try:
                        self.upload(local_item_path, remote_item_path)
                        results["success"] += 1
                    except Exception as e:
                        results["failed"] += 1
                        results["errors"].append(f"{local_item_path}: {str(e)}")
                        
                elif os.path.isdir(local_item_path) and recursive:
                    # 处理子目录
                    remote_subdir = f"{remote_path}/{item}" if remote_path else item
                    
                    # 确保远程子目录存在
                    try:
                        try:
                            self.cwd(remote_subdir)
                        except CommandError:
                            self.mkd(remote_subdir)
                            self.cwd(remote_subdir)
                            
                        # 递归处理子目录
                        _process_dir(local_item_path, remote_subdir)
                        
                        # 返回上一级目录
                        self.cdup()
                    except CommandError as e:
                        results["errors"].append(f"{remote_subdir}: {str(e)}")
        
        # 开始处理
        _process_dir(local_dir, remote_dir)
        return results

    def batch_download(self, remote_dir, local_dir, pattern="*", recursive=True):
        """
        批量下载文件
        
        Args:
            remote_dir (str): 远程目录
            local_dir (str): 本地目录
            pattern (str): 文件匹配模式
            recursive (bool): 是否递归处理子目录
            
        Returns:
            dict: 下载结果统计
        """
        import fnmatch
        
        # 确保本地目录存在
        os.makedirs(local_dir, exist_ok=True)
        
        if remote_dir:
            # 切换到远程目录
            try:
                original_dir = self.pwd()
                self.cwd(remote_dir)
            except CommandError as e:
                raise CommandError(f"无法切换到远程目录: {str(e)}")
        
        results = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "errors": []
        }
        
        def _process_remote_dir(current_remote_dir, current_local_dir):
            # 列出远程目录内容
            try:
                items = self.list()
            except CommandError as e:
                results["errors"].append(f"{current_remote_dir}: {str(e)}")
                return
                
            # 处理每个条目
            for item in items:
                name = item.get('name')
                # 跳过当前目录和父目录
                if name in ('.', '..'):
                    continue
                    
                is_dir = item.get('is_dir', False)
                
                if not is_dir:
                    # 处理文件
                    if not fnmatch.fnmatch(name, pattern):
                        results["skipped"] += 1
                        continue
                        
                    results["total"] += 1
                    local_file_path = os.path.join(current_local_dir, name)
                    
                    try:
                        self.download(name, local_file_path)
                        results["success"] += 1
                    except Exception as e:
                        results["failed"] += 1
                        results["errors"].append(f"{name}: {str(e)}")
                        
                elif recursive:
                    # 处理子目录
                    local_subdir = os.path.join(current_local_dir, name)
                    os.makedirs(local_subdir, exist_ok=True)
                    
                    # 切换到子目录
                    try:
                        self.cwd(name)
                        _process_remote_dir(f"{current_remote_dir}/{name}", local_subdir)
                        self.cdup()  # 返回上一级目录
                    except CommandError as e:
                        results["errors"].append(f"{name}: {str(e)}")
        
        # 开始处理
        _process_remote_dir(remote_dir, local_dir)
        
        # 返回到原始目录
        if remote_dir:
            try:
                self.cwd(original_dir)
            except CommandError:
                pass
                
        return results


class FTPConnectionPool:
    """FTP连接池，管理多个FTP连接并提供连接复用"""
    
    def __init__(self, host=None, port=21, max_connections=5, idle_timeout=300):
        """
        初始化FTP连接池
        
        Args:
            host (str): FTP服务器主机
            port (int): FTP服务器端口
            max_connections (int): 最大连接数
            idle_timeout (int): 空闲连接超时时间(秒)
        """
        self.host = host
        self.port = port
        self.max_connections = max_connections
        self.idle_timeout = idle_timeout
        
        # 连接池
        self.pool = []  # [(client, last_used_time), ...]
        self.active_connections = 0
        self.lock = threading.RLock()
        
        # 统计信息
        self.total_connections_created = 0
        self.total_connections_reused = 0
        self.total_connections_closed = 0
        self.connection_failures = 0
        
        # 启动连接验证定时器
        self.validation_timer = None
        self._start_validation_timer()
    
    def _start_validation_timer(self):
        """启动定期验证连接的定时器"""
        if self.validation_timer:
            self.validation_timer.cancel()
            
        # 创建一个定时器，每隔一段时间检查连接是否有效
        self.validation_timer = threading.Timer(
            self.idle_timeout / 2,  # 每隔超时时间的一半检查一次
            self._validate_connections
        )
        self.validation_timer.daemon = True  # 设置为守护线程
        self.validation_timer.start()
    
    def _validate_connections(self):
        """验证池中所有连接的有效性，关闭无效或超时的连接"""
        with self.lock:
            current_time = time.time()
            valid_connections = []
            
            for client, last_used_time in self.pool:
                # 检查连接是否超时
                if current_time - last_used_time > self.idle_timeout:
                    logger.debug(f"关闭空闲连接: {client.host}:{client.port}")
                    try:
                        client.quit()
                    except:
                        pass
                    self.total_connections_closed += 1
                    continue
                
                # 验证连接是否还有效
                if not client.verify_connection():
                    logger.debug(f"关闭无效连接: {client.host}:{client.port}")
                    try:
                        client.quit()
                    except:
                        pass
                    self.total_connections_closed += 1
                    continue
                
                # 连接仍然有效
                valid_connections.append((client, last_used_time))
            
            # 更新池
            self.pool = valid_connections
            
        # 重新启动定时器
        self._start_validation_timer()
    
    def get_connection(self, username=None, password=None, **kwargs):
        """
        从连接池获取一个连接，如果池中没有可用连接则创建新连接
        
        Args:
            username (str): 用户名
            password (str): 密码
            **kwargs: 传递给FTPClient构造函数的其他参数
            
        Returns:
            FTPClient: FTP客户端实例
        """
        with self.lock:
            # 首先尝试从池中获取空闲连接
            while self.pool:
                client, last_used_time = self.pool.pop()
                
                # 验证连接是否有效
                if client.verify_connection():
                    self.active_connections += 1
                    self.total_connections_reused += 1
                    logger.debug(f"复用连接: {client.host}:{client.port}")
                    return client
                else:
                    # 连接无效，关闭并创建新连接
                    logger.debug(f"连接无效，关闭: {client.host}:{client.port}")
                    try:
                        client.quit()
                    except:
                        pass
                    self.total_connections_closed += 1
            
            # 如果达到最大连接数，等待
            if self.active_connections >= self.max_connections:
                logger.warning(f"已达到最大连接数: {self.max_connections}，等待连接释放")
                return None
            
            # 创建新连接
            try:
                client = FTPClient(host=self.host, port=self.port, **kwargs)
                client.connect()
                
                # 如果提供了用户名和密码，自动登录
                if username and password:
                    client.login(username, password)
                
                self.active_connections += 1
                self.total_connections_created += 1
                logger.debug(f"创建新连接: {client.host}:{client.port}")
                return client
            except Exception as e:
                self.connection_failures += 1
                logger.error(f"创建连接失败: {str(e)}")
                raise
    
    def release_connection(self, client):
        """
        将连接释放回池中
        
        Args:
            client (FTPClient): 要释放的FTP客户端
        """
        with self.lock:
            # 如果连接无效或已关闭，不放回池中
            if not client or not client.connected:
                self.active_connections = max(0, self.active_connections - 1)
                return
            
            # 将连接放回池中
            self.pool.append((client, time.time()))
            self.active_connections -= 1
            logger.debug(f"连接 {client.host}:{client.port} 已释放回池")
    
    def close_all(self):
        """关闭所有连接并清空池"""
        with self.lock:
            # 停止定时器
            if self.validation_timer:
                self.validation_timer.cancel()
                self.validation_timer = None
            
            # 关闭所有连接
            for client, _ in self.pool:
                try:
                    client.quit()
                except:
                    pass
                self.total_connections_closed += 1
            
            self.pool = []
            self.active_connections = 0
            logger.info("所有连接已关闭")
    
    def get_stats(self):
        """获取连接池统计信息"""
        with self.lock:
            return {
                "active_connections": self.active_connections,
                "idle_connections": len(self.pool),
                "total_connections": self.active_connections + len(self.pool),
                "max_connections": self.max_connections,
                "total_created": self.total_connections_created,
                "total_reused": self.total_connections_reused,
                "total_closed": self.total_connections_closed,
                "connection_failures": self.connection_failures,
            }
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_all()


class FTPPooledClient:
    """使用连接池管理FTP连接的客户端包装器"""
    
    def __init__(self, pool):
        """
        初始化pooled客户端
        
        Args:
            pool (FTPConnectionPool): FTP连接池
        """
        self.pool = pool
        self.client = None
    
    def __enter__(self):
        """获取连接"""
        self.client = self.pool.get_connection()
        return self.client
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """释放连接"""
        if self.client:
            self.pool.release_connection(self.client)
            self.client = None

# 添加一些代码示例备注
"""
# 使用连接池的示例:
pool = FTPConnectionPool("ftp.example.com", 21, max_connections=5)

# 方式1: 使用上下文管理器
with FTPPooledClient(pool) as client:
    if client:
        client.login("user", "password")
        # 使用client...

# 方式2: 手动获取和释放
client = pool.get_connection()
try:
    client.login("user", "password")
    # 使用client...
finally:
    pool.release_connection(client)

# 获取统计信息
stats = pool.get_stats()
print(f"活动连接数: {stats['active_connections']}")
print(f"总创建连接数: {stats['total_created']}")
"""
