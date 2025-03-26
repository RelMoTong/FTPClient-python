class FTPError(Exception):
    """FTP基础异常类"""
    def __init__(self, message, code=None):
        self.message = message
        self.code = code
        super().__init__(self.message)

class AuthenticationError(FTPError):
    """认证相关错误"""
    pass

class PermissionError(FTPError):
    """权限相关错误"""
    pass

class ConnectionError(FTPError):
    """连接相关错误"""
    pass

class FileTransferError(FTPError):
    """文件传输相关错误"""
    pass

class CommandError(FTPError):
    """命令执行相关错误"""
    pass

class ConfigError(FTPError):
    """配置相关错误"""
    pass

class QueueError(FTPError):
    """队列处理相关错误"""
    pass

class ChecksumError(FileTransferError):
    """校验和错误"""
    pass

class ReconnectionError(ConnectionError):
    """重连失败错误"""
    pass

class SessionError(FTPError):
    """会话管理相关错误"""
    pass

class RateLimitError(FTPError):
    """速率限制相关错误"""
    pass

class InvalidResponseError(FTPError):
    """无效响应错误"""
    pass

class TransferAbortedError(FileTransferError):
    """传输中止错误"""
    pass

class TimeoutError(ConnectionError):
    """超时错误"""
    pass
