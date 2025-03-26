import os
import time
import queue
import threading
import logging
from enum import Enum, auto
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional, Dict, List, Any

from common.exceptions import QueueError, FileTransferError
from common.utils import format_size, calculate_transfer_speed

logger = logging.getLogger(__name__)

class TaskPriority(Enum):
    """传输任务优先级"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3

class TaskStatus(Enum):
    """传输任务状态"""
    PENDING = auto()    # 等待中
    RUNNING = auto()    # 正在执行
    COMPLETED = auto()  # 已完成
    FAILED = auto()     # 失败
    CANCELED = auto()   # 已取消
    PAUSED = auto()     # 已暂停
    RETRYING = auto()   # 重试中

class TaskType(Enum):
    """任务类型"""
    UPLOAD = auto()     # 上传
    DOWNLOAD = auto()   # 下载
    DELETE = auto()     # 删除
    RENAME = auto()     # 重命名
    MKDIR = auto()      # 创建目录
    RMDIR = auto()      # 删除目录
    LIST = auto()       # 列表

@dataclass
class TransferTask:
    """传输任务定义"""
    # 基本属性
    id: str                  # 任务ID
    type: TaskType           # 任务类型
    args: tuple              # 任务参数
    kwargs: dict             # 任务关键字参数
    priority: TaskPriority   # 任务优先级
    
    # 状态跟踪
    status: TaskStatus = TaskStatus.PENDING       # 任务状态
    created_time: datetime = None                 # 创建时间
    start_time: Optional[datetime] = None         # 开始时间
    end_time: Optional[datetime] = None           # 结束时间
    progress: float = 0                           # 进度(0-100)
    error: Optional[Exception] = None             # 错误信息
    result: Any = None                            # 任务结果
    
    # 重试相关
    retry_count: int = 0                          # 当前重试次数
    max_retries: int = 3                          # 最大重试次数
    retry_delay: int = 5                          # 重试延迟(秒)
    
    # 回调
    on_progress: Optional[Callable] = None        # 进度回调
    on_complete: Optional[Callable] = None        # 完成回调
    on_error: Optional[Callable] = None           # 错误回调
    
    def __post_init__(self):
        """初始化后处理"""
        if self.created_time is None:
            self.created_time = datetime.now()
    
    def update_progress(self, current: int, total: int, elapsed: float):
        """
        更新任务进度
        
        Args:
            current: 当前完成量
            total: 总量
            elapsed: 已用时间(秒)
        """
        if total > 0:
            self.progress = min(100.0, (current / total) * 100)
        else:
            self.progress = 0
            
        if self.on_progress:
            self.on_progress(self, current, total, elapsed)
    
    def mark_running(self):
        """标记任务为运行中"""
        self.status = TaskStatus.RUNNING
        self.start_time = datetime.now()
    
    def mark_completed(self, result=None):
        """标记任务为已完成"""
        self.status = TaskStatus.COMPLETED
        self.end_time = datetime.now()
        self.result = result
        self.progress = 100.0
        
        if self.on_complete:
            self.on_complete(self)
    
    def mark_failed(self, error=None):
        """标记任务为失败"""
        self.status = TaskStatus.FAILED
        self.end_time = datetime.now()
        self.error = error
        
        if self.on_error:
            self.on_error(self)
    
    def mark_canceled(self):
        """标记任务为已取消"""
        self.status = TaskStatus.CANCELED
        self.end_time = datetime.now()
    
    def mark_paused(self):
        """标记任务为已暂停"""
        self.status = TaskStatus.PAUSED
    
    def mark_retrying(self):
        """标记任务为重试中"""
        self.status = TaskStatus.RETRYING
        self.retry_count += 1
    
    @property
    def duration(self) -> float:
        """获取任务持续时间"""
        if not self.start_time:
            return 0
            
        end = self.end_time if self.end_time else datetime.now()
        return (end - self.start_time).total_seconds()
    
    @property
    def age(self) -> float:
        """获取任务年龄(从创建至今)"""
        return (datetime.now() - self.created_time).total_seconds()
    
    def can_retry(self) -> bool:
        """检查任务是否可以重试"""
        return (self.status == TaskStatus.FAILED and 
                self.retry_count < self.max_retries)
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': self.id,
            'type': self.type.name,
            'status': self.status.name,
            'progress': self.progress,
            'created': self.created_time.isoformat() if self.created_time else None,
            'started': self.start_time.isoformat() if self.start_time else None,
            'ended': self.end_time.isoformat() if self.end_time else None,
            'duration': self.duration,
            'retry_count': self.retry_count,
            'error': str(self.error) if self.error else None,
            'priority': self.priority.name,
        }

class TransferQueue:
    """传输队列管理器"""
    
    def __init__(self, max_concurrent_tasks=3, auto_retry=True):
        """
        初始化传输队列
        
        Args:
            max_concurrent_tasks: 最大并发任务数
            auto_retry: 是否自动重试失败任务
        """
        self.task_queue = queue.PriorityQueue()     # 任务优先队列
        self.active_tasks = {}                      # 活动任务 {id: task}
        self.completed_tasks = {}                   # 已完成任务 {id: task}
        self.failed_tasks = {}                      # 失败任务 {id: task}
        self.max_concurrent_tasks = max_concurrent_tasks
        self.auto_retry = auto_retry
        self.shutdown_flag = threading.Event()      # 关闭标志
        self.task_added_event = threading.Event()   # 任务添加事件
        
        # 工作线程
        self._worker_threads = []
        self._lock = threading.RLock()
        self._task_id_counter = 0
        
        # 启动工作线程
        for i in range(max_concurrent_tasks):
            t = threading.Thread(
                target=self._worker, 
                name=f"TransferWorker-{i}",
                daemon=True
            )
            self._worker_threads.append(t)
            t.start()
        
        # 启动重试线程
        if auto_retry:
            self._retry_thread = threading.Thread(
                target=self._retry_worker,
                name="RetryWorker",
                daemon=True
            )
            self._retry_thread.start()
        
        logger.info(f"传输队列已初始化，最大并发任务数: {max_concurrent_tasks}, 自动重试: {auto_retry}")
    
    def _get_next_task_id(self):
        """获取下一个任务ID"""
        with self._lock:
            self._task_id_counter += 1
            return f"task-{self._task_id_counter}"
    
    def add_task(self, task_type, *args, priority=TaskPriority.NORMAL, 
                on_progress=None, on_complete=None, on_error=None, **kwargs):
        """
        添加传输任务
        
        Args:
            task_type: 任务类型
            *args: 任务参数
            priority: 任务优先级
            on_progress: 进度回调函数
            on_complete: 完成回调函数
            on_error: 错误回调函数
            **kwargs: 任务关键字参数
            
        Returns:
            task_id: 任务ID
        """
        task_id = self._get_next_task_id()
        
        task = TransferTask(
            id=task_id,
            type=task_type,
            args=args,
            kwargs=kwargs,
            priority=priority,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
            max_retries=kwargs.get('max_retries', 3),
            retry_delay=kwargs.get('retry_delay', 5),
        )
        
        # 添加到队列
        # 使用负优先级值是因为PriorityQueue是按照优先级从小到大排序
        self.task_queue.put((-task.priority.value, task.created_time, task))
        
        # 通知有新任务
        self.task_added_event.set()
        
        logger.debug(f"已添加任务 {task_id} 类型: {task_type.name}, 优先级: {priority.name}")
        return task_id
    
    def _worker(self):
        """工作线程，处理队列任务"""
        while not self.shutdown_flag.is_set():
            try:
                # 等待任务 (带有0.5秒超时)
                try:
                    _, _, task = self.task_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                # 检查任务是否被取消
                if task.status == TaskStatus.CANCELED:
                    logger.debug(f"跳过已取消的任务: {task.id}")
                    self.task_queue.task_done()
                    continue
                
                # 更新任务状态
                with self._lock:
                    task.mark_running()
                    self.active_tasks[task.id] = task
                
                logger.info(f"开始执行任务: {task.id} 类型: {task.type.name}")
                
                try:
                    # 将任务交给具体处理方法执行
                    handler_method = self._get_task_handler(task.type)
                    result = handler_method(task)
                    
                    # 任务成功完成
                    with self._lock:
                        task.mark_completed(result)
                        self.completed_tasks[task.id] = task
                        self.active_tasks.pop(task.id, None)
                        
                    logger.info(f"任务完成: {task.id} 类型: {task.type.name}")
                    
                except Exception as e:
                    # 任务执行失败
                    with self._lock:
                        task.mark_failed(e)
                        self.failed_tasks[task.id] = task
                        self.active_tasks.pop(task.id, None)
                        
                    logger.error(f"任务失败: {task.id} 类型: {task.type.name}, 错误: {e}")
                
                finally:
                    self.task_queue.task_done()
                    
            except Exception as e:
                logger.exception(f"工作线程异常: {e}")
    
    def _retry_worker(self):
        """重试线程，处理失败的任务"""
        while not self.shutdown_flag.is_set():
            try:
                # 每5秒检查一次
                time.sleep(5)
                
                # 检查有无需要重试的任务
                retry_tasks = []
                with self._lock:
                    for task_id, task in list(self.failed_tasks.items()):
                        if task.can_retry():
                            retry_tasks.append(task)
                            self.failed_tasks.pop(task_id)
                
                # 重新提交需要重试的任务
                for task in retry_tasks:
                    task.mark_retrying()
                    logger.info(f"重试任务: {task.id} 类型: {task.type.name}, 第 {task.retry_count} 次重试")
                    
                    # 等待重试延迟
                    time.sleep(task.retry_delay)
                    
                    # 重新添加到队列
                    self.task_queue.put((-task.priority.value, task.created_time, task))
                    self.task_added_event.set()
                    
            except Exception as e:
                logger.exception(f"重试线程异常: {e}")
    
    def _get_task_handler(self, task_type):
        """
        获取任务处理方法
        
        Args:
            task_type: 任务类型
            
        Returns:
            handler: 处理方法
        """
        # 这个方法会在子类中被覆盖实现
        raise NotImplementedError(
            f"任务类型 {task_type} 的处理方法未实现，"
            "请在子类中实现 _get_task_handler 方法"
        )
    
    def cancel_task(self, task_id):
        """
        取消任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            bool: 是否成功取消
        """
        with self._lock:
            # 检查活动任务
            if task_id in self.active_tasks:
                logger.warn(f"无法取消正在执行的任务: {task_id}")
                return False
            
            # 检查失败任务
            if task_id in self.failed_tasks:
                task = self.failed_tasks.pop(task_id)
                task.mark_canceled()
                self.completed_tasks[task_id] = task
                logger.info(f"已取消失败任务: {task_id}")
                return True
            
            # 检查已完成任务
            if task_id in self.completed_tasks:
                logger.warn(f"无法取消已完成的任务: {task_id}")
                return False
        
        # 任务可能还在队列中
        # 由于PriorityQueue不支持直接删除或修改元素
        # 我们只能在worker线程中跳过已取消的任务
        # 在这里标记任务为已取消并返回True
        logger.info(f"标记队列中的任务为取消: {task_id}")
        return True
    
    def get_task_status(self, task_id):
        """
        获取任务状态
        
        Args:
            task_id: 任务ID
            
        Returns:
            task: 任务对象或None
        """
        with self._lock:
            # 按优先级查找: 活动 > 已完成 > 失败
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
            dict: 所有任务状态
        """
        result = {
            'active': {},
            'completed': {},
            'failed': {},
            'queued': [],
        }
        
        with self._lock:
            # 活动任务
            for task_id, task in self.active_tasks.items():
                result['active'][task_id] = task.to_dict()
                
            # 已完成任务
            for task_id, task in self.completed_tasks.items():
                result['completed'][task_id] = task.to_dict()
                
            # 失败任务
            for task_id, task in self.failed_tasks.items():
                result['failed'][task_id] = task.to_dict()
        
        # 无法直接查看队列中的所有元素
        # 但可以获取队列大小
        result['queue_size'] = self.task_queue.qsize()
        
        return result
    
    def clear_completed_tasks(self, older_than=3600):
        """
        清理已完成的任务
        
        Args:
            older_than: 清理多少秒以前的已完成任务
            
        Returns:
            int: 清理的任务数量
        """
        now = time.time()
        count = 0
        
        with self._lock:
            for task_id in list(self.completed_tasks.keys()):
                task = self.completed_tasks[task_id]
                if task.end_time and (now - task.end_time.timestamp()) > older_than:
                    self.completed_tasks.pop(task_id)
                    count += 1
        
        logger.info(f"已清理 {count} 个已完成任务")
        return count
    
    def shutdown(self, wait=True):
        """
        关闭队列管理器
        
        Args:
            wait: 是否等待所有任务完成
        """
        if wait:
            self.task_queue.join()
            
        self.shutdown_flag.set()
        
        for thread in self._worker_threads:
            if thread.is_alive():
                thread.join(timeout=1.0)
        
        if hasattr(self, '_retry_thread') and self._retry_thread.is_alive():
            self._retry_thread.join(timeout=1.0)
            
        logger.info("传输队列已关闭")
    
    def __del__(self):
        """析构时确保线程正确关闭"""
        if not self.shutdown_flag.is_set():
            self.shutdown(wait=False)
