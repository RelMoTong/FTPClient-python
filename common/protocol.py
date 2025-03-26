from enum import Enum
from functools import wraps
import logging
import ftplib
import re
import socket
import ssl

logger = logging.getLogger(__name__)

class TransferMode(Enum):
    """传输模式枚举"""
    ASCII = 'A'
    BINARY = 'I'

class ConnectionMode(Enum):
    """连接模式枚举"""
    ACTIVE = 'PORT'
    PASSIVE = 'PASV'

def ftp_command(func):
    """
    FTP命令装饰器，处理异常和日志
    
    Args:
        func: 被装饰的函数
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        cmd_name = func.__name__.upper()
        logger.debug(f"执行FTP命令: {cmd_name} {args}")
        try:
            result = func(self, *args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"FTP命令 {cmd_name} 执行失败: {e}")
            raise
    return wrapper

class FTPProtocolMixin:
    """
    FTP协议解析器，实现命令到方法的映射
    该Mixin类用于在FTP客户端类中混合使用
    """
    
    # FTP回复码分类
    POSITIVE_PRELIMINARY = 1  # 1xx: 肯定初步回答
    POSITIVE_COMPLETION = 2   # 2xx: 肯定完成回答
    POSITIVE_INTERMEDIATE = 3 # 3xx: 肯定中间回答
    NEGATIVE_TRANSIENT = 4    # 4xx: 暂时否定回答
    NEGATIVE_PERMANENT = 5    # 5xx: 永久否定回答
    
    # 常见FTP回复码
    COMMAND_OK = 200
    READY_FOR_NEW_USER = 220
    LOGGED_IN = 230
    NEED_PASSWORD = 331
    LOGIN_FAILED = 530
    FILE_STATUS_OK = 150
    TRANSFER_COMPLETE = 226
    PATH_CREATED = 257
    PASSIVE_MODE = 227
    
    def parse_response(self, response):
        """
        解析FTP服务器响应
        
        Args:
            response (str): 响应字符串
            
        Returns:
            tuple: (code, message)
        """
        try:
            code = int(response[:3])
            message = response[3:].strip()
            return code, message
        except (ValueError, IndexError):
            logger.error(f"无法解析FTP响应: {response}")
            return None, response
    
    def parse_pasv_response(self, response):
        """
        解析PASV命令响应，提取IP和端口
        
        Args:
            response (str): PASV响应字符串
            
        Returns:
            tuple: (ip, port)
        """
        pattern = r'(\d+),(\d+),(\d+),(\d+),(\d+),(\d+)'
        match = re.search(pattern, response)
        if not match:
            raise ValueError("无法解析PASV响应")
        
        numbers = [int(n) for n in match.groups()]
        ip = '.'.join(str(n) for n in numbers[:4])
        port = (numbers[4] << 8) + numbers[5]
        return ip, port
    
    def build_port_command(self, ip, port):
        """
        构建PORT命令参数
        
        Args:
            ip (str): 本地IP地址
            port (int): 本地端口
            
        Returns:
            str: PORT命令参数
        """
        ip_parts = ip.split('.')
        port_hi = port // 256
        port_lo = port % 256
        return f"{','.join(ip_parts)},{port_hi},{port_lo}"
    
    def parse_mlsd_response(self, response_list):
        """
        解析MLSD命令的响应，获取详细的目录列表
        
        Args:
            response_list (list): MLSD命令响应的数据行列表
            
        Returns:
            list: 文件和目录信息的列表
        """
        result = []
        for line in response_list:
            if not line.strip():
                continue
                
            # MLSD格式: facts; filename
            try:
                facts_part, name = line.strip().split(' ', 1)
                facts = {}
                
                # 解析facts部分
                for fact in facts_part.split(';'):
                    if not fact:
                        continue
                    key, value = fact.split('=', 1)
                    facts[key.lower()] = value
                
                # 添加文件名
                facts['name'] = name
                result.append(facts)
            except Exception as e:
                logger.warning(f"解析MLSD行失败: {line}, 错误: {e}")
                continue
        
        return result
    
    def parse_list_response(self, response_list):
        """
        解析LIST命令的响应，尝试解析Unix格式的目录列表
        
        Args:
            response_list (list): LIST命令响应的数据行列表
            
        Returns:
            list: 文件和目录信息的列表
        """
        result = []
        unix_pattern = re.compile(
            r'^([d-])([rwxst-]{9})\s+(\d+)\s+(\w+)\s+(\w+)\s+(\d+)\s+(\w+\s+\d+\s+[\w:]+)\s+(.+)$'
        )
        
        for line in response_list:
            if not line.strip():
                continue
                
            match = unix_pattern.match(line)
            if match:
                file_info = {
                    'type': 'dir' if match.group(1) == 'd' else 'file',
                    'permissions': match.group(2),
                    'links': int(match.group(3)),
                    'owner': match.group(4),
                    'group': match.group(5),
                    'size': int(match.group(6)),
                    'date': match.group(7),
                    'name': match.group(8)
                }
                result.append(file_info)
            else:
                # 尝试处理非Unix格式的输出
                logger.debug(f"无法解析为Unix格式: {line}")
                if line.strip():
                    result.append({'name': line.strip(), 'type': 'unknown'})
        
        return result
    
    @staticmethod
    def is_binary_file(filename):
        """
        判断文件是否应使用二进制模式传输
        
        Args:
            filename (str): 文件名
            
        Returns:
            bool: 是否是二进制文件
        """
        from common.utils import is_binary_file as utils_is_binary
        return utils_is_binary(filename)
