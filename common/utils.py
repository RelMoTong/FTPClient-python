import os
import sys
import time
import hashlib
import zlib
import platform
import logging
import mmap
import re
from functools import wraps
from pathlib import Path

logger = logging.getLogger(__name__)

def get_file_md5(filepath, chunk_size=8192):
    """
    计算文件MD5值
    
    Args:
        filepath (str): 文件路径
        chunk_size (int): 每次读取的块大小
        
    Returns:
        str: 文件的MD5哈希值
    """
    md5 = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            md5.update(chunk)
    return md5.hexdigest()

def get_file_crc32(filepath, chunk_size=8192):
    """
    计算文件CRC32校验值
    
    Args:
        filepath (str): 文件路径
        chunk_size (int): 每次读取的块大小
        
    Returns:
        int: 文件的CRC32校验值
    """
    crc = 0
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            crc = zlib.crc32(chunk, crc)
    return crc & 0xffffffff

def get_block_crc32(data):
    """
    计算数据块的CRC32校验值
    
    Args:
        data (bytes): 二进制数据块
        
    Returns:
        int: CRC32校验值
    """
    return zlib.crc32(data) & 0xffffffff

def format_path(path):
    """
    跨平台路径格式化，确保路径格式符合当前操作系统
    
    Args:
        path (str): 原始路径
        
    Returns:
        str: 格式化后的路径
    """
    if platform.system() == 'Windows':
        return path.replace('/', '\\')
    else:
        return path.replace('\\', '/')

def format_size(size, decimal_places=2):
    """
    格式化文件大小显示
    
    Args:
        size (int): 文件大小（字节）
        decimal_places (int): 小数点后位数
        
    Returns:
        str: 格式化后的大小字符串
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0 or unit == 'TB':
            break
        size /= 1024.0
    return f"{size:.{decimal_places}f} {unit}"

def calculate_transfer_speed(size, elapsed_time):
    """
    计算传输速率
    
    Args:
        size (int): 已传输的字节数
        elapsed_time (float): 经过的时间（秒）
        
    Returns:
        str: 格式化后的传输速率字符串
    """
    if elapsed_time == 0:
        return "0 B/s"
    
    speed = size / elapsed_time
    return f"{format_size(speed)}/s"

def benchmark(func):
    """
    性能基准测试装饰器
    
    Args:
        func: 被装饰的函数
        
    Returns:
        function: 装饰后的函数
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        elapsed_time = time.time() - start_time
        logger.debug(f"{func.__name__} 执行时间: {elapsed_time:.6f}秒")
        return result
    return wrapper

class TokenBucket:
    """令牌桶算法实现带宽限制"""
    
    def __init__(self, capacity, fill_rate):
        """
        初始化令牌桶
        
        Args:
            capacity (float): 桶容量(最大可用令牌数)
            fill_rate (float): 填充速率(每秒添加的令牌数)
        """
        self.capacity = float(capacity)
        self.fill_rate = float(fill_rate)
        self.tokens = float(capacity)
        self.last_time = time.time()
        
    def consume(self, tokens):
        """
        消费令牌，如果没有足够的令牌可以消费，则等待
        
        Args:
            tokens (float): 要消费的令牌数
            
        Returns:
            float: 需要等待的时间(秒)
        """
        # 更新令牌数量
        now = time.time()
        elapsed = now - self.last_time
        self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)
        self.last_time = now
        
        # 检查是否有足够的令牌
        if tokens <= self.tokens:
            self.tokens -= tokens
            return 0.0
        else:
            # 计算需要等待的时间
            wait_time = (tokens - self.tokens) / self.fill_rate
            self.tokens = 0
            return wait_time

def memory_usage():
    """
    获取当前进程的内存使用情况
    
    Returns:
        float: 内存使用量（MB）
    """
    import psutil
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    return mem_info.rss / 1024 / 1024  # 返回MB

def is_binary_file(filename):
    """
    判断文件是否为二进制文件
    
    Args:
        filename (str): 文件名
        
    Returns:
        bool: 如果是二进制文件返回True，否则返回False
    """
    text_extensions = [
        '.txt', '.md', '.html', '.htm', '.css', '.js', '.json', 
        '.xml', '.csv', '.log', '.ini', '.conf', '.cfg', 
        '.py', '.java', '.c', '.cpp', '.h', '.sh', '.bat',
        '.yaml', '.yml', '.toml'
    ]
    
    # 检查文件扩展名
    _, ext = os.path.splitext(filename.lower())
    if ext in text_extensions:
        return False
    return True

def generate_session_id():
    """
    生成会话ID
    
    Returns:
        str: 唯一的会话ID
    """
    import uuid
    return str(uuid.uuid4())

def parse_permissions(permission_str):
    """
    解析Unix风格的权限字符串
    
    Args:
        permission_str (str): 权限字符串，如'rwxr-xr--'
        
    Returns:
        int: 数值化的权限值(如0755)
    """
    if not permission_str or len(permission_str) != 9:
        return None
    
    # 将权限字符串转换为3组权限值
    modes = []
    for i in range(0, 9, 3):
        mode = 0
        if permission_str[i] == 'r':
            mode += 4
        if permission_str[i+1] == 'w':
            mode += 2
        if permission_str[i+2] == 'x':
            mode += 1
        modes.append(mode)
    
    # 组合为权限值
    return (modes[0] * 100) + (modes[1] * 10) + modes[2]

def permissions_to_str(mode):
    """
    将数值权限转换为字符串表示
    
    Args:
        mode (int): 权限值，如0755
        
    Returns:
        str: 权限字符串，如'rwxr-xr--'
    """
    result = ""
    
    # 解析为3组权限值
    owner = (mode // 100) % 10
    group = (mode // 10) % 10
    other = mode % 10
    
    for m in [owner, group, other]:
        result += 'r' if m & 4 else '-'
        result += 'w' if m & 2 else '-'
        result += 'x' if m & 1 else '-'
    
    return result

def use_mmap_read(file_obj, size=-1, offset=0, access=mmap.ACCESS_READ):
    """
    使用mmap进行零拷贝文件读取
    
    Args:
        file_obj: 文件对象
        size (int): 映射的大小，-1表示整个文件
        offset (int): 偏移量
        access: 访问模式
        
    Returns:
        mmap.mmap: 内存映射对象
    """
    if size == -1:
        size = os.fstat(file_obj.fileno()).st_size - offset
    
    return mmap.mmap(file_obj.fileno(), size, access=access, offset=offset)
