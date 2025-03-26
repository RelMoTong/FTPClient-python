import os
import json
import logging
import logging.config
from datetime import datetime
from pathlib import Path

def setup_logging(config_path=None, default_level=logging.INFO, log_dir=None):
    """
    配置日志系统
    
    Args:
        config_path (str, optional): 日志配置文件路径
        default_level (int, optional): 默认日志级别
        log_dir (str, optional): 日志文件目录
        
    Returns:
        logger: 根日志记录器
    """
    if not log_dir:
        log_dir = Path("e:/Python/NewFTP/logs")
    else:
        log_dir = Path(log_dir)
    
    # 确保日志目录存在
    log_dir.mkdir(exist_ok=True)
    
    # 日志文件路径
    log_file = log_dir / "ftp_audit.log"
    
    if config_path and os.path.exists(config_path):
        # 从配置文件加载日志配置
        with open(config_path, 'r') as f:
            config = json.load(f)
        logging.config.dictConfig(config)
    else:
        # 使用默认配置
        logging.basicConfig(
            level=default_level,
            format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            handlers=[
                logging.StreamHandler(),  # 控制台输出
                logging.FileHandler(log_file)  # 文件输出
            ]
        )
    
    # 创建一个更详细的日志配置
    logging_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
            },
            'detailed': {
                'format': '%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s'
            },
            'json': {
                'format': '%(asctime)s %(levelname)s %(name)s %(filename)s %(lineno)d %(message)s',
                '()': 'common.logger.JsonFormatter'
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': 'INFO',
                'formatter': 'standard',
                'stream': 'ext://sys.stdout'
            },
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': 'DEBUG',
                'formatter': 'detailed',
                'filename': str(log_file),
                'maxBytes': 10485760,  # 10MB
                'backupCount': 5,
                'encoding': 'utf8'
            },
            'json_file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': 'INFO',
                'formatter': 'json',
                'filename': str(log_dir / "ftp_audit_json.log"),
                'maxBytes': 10485760,  # 10MB
                'backupCount': 5,
                'encoding': 'utf8'
            }
        },
        'loggers': {
            '': {  # 根记录器
                'handlers': ['console', 'file'],
                'level': 'DEBUG',
                'propagate': True
            },
            'ftp.audit': {  # 审计日志记录器
                'handlers': ['json_file'],
                'level': 'INFO',
                'propagate': False
            }
        }
    }
    
    logging.config.dictConfig(logging_config)
    
    return logging.getLogger()

class JsonFormatter(logging.Formatter):
    """JSON格式日志格式化器"""
    
    def format(self, record):
        """
        将日志记录格式化为JSON
        
        Args:
            record: 日志记录
            
        Returns:
            str: JSON格式的日志
        """
        log_data = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'file': record.filename,
            'line': record.lineno,
            'message': record.getMessage()
        }
        
        # 添加额外的字段
        if hasattr(record, 'ip'):
            log_data['ip'] = record.ip
        if hasattr(record, 'user'):
            log_data['user'] = record.user
        if hasattr(record, 'operation'):
            log_data['operation'] = record.operation
        if hasattr(record, 'duration'):
            log_data['duration'] = record.duration
        if hasattr(record, 'status'):
            log_data['status'] = record.status
            
        return json.dumps(log_data)

class AuditLogger:
    """审计日志记录器"""
    
    def __init__(self):
        """初始化审计日志记录器"""
        self.logger = logging.getLogger('ftp.audit')
    
    def log_action(self, ip, user, operation, duration=0, status="success", **kwargs):
        """
        记录审计日志
        
        Args:
            ip (str): 客户端IP地址
            user (str): 用户名
            operation (str): 操作描述
            duration (float): 操作耗时（秒）
            status (str): 操作状态
            **kwargs: 其他字段
        """
        extra = {
            'ip': ip,
            'user': user,
            'operation': operation,
            'duration': duration,
            'status': status
        }
        
        # 添加额外字段
        extra.update(kwargs)
        
        record = logging.makeLogRecord({
            'name': self.logger.name,
            'level': logging.INFO,
            'msg': f"{user}@{ip} {operation} {status} in {duration:.3f}s"
        })
        
        for key, value in extra.items():
            setattr(record, key, value)
            
        self.logger.handle(record)

# 单例模式
audit_logger = AuditLogger()
