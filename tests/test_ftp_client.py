import unittest
import os
import sys
import socket
import threading
import time
from unittest.mock import MagicMock, patch, Mock

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from client.ftp_client import FTPClient, FTPConnectionPool, FTPPooledClient
from common.protocol import TransferMode, ConnectionMode
from common.exceptions import (
    FTPError, AuthenticationError, ConnectionError,
    FileTransferError, CommandError, TimeoutError
)

class MockSocket:
    """模拟套接字类，用于测试"""
    
    def __init__(self, responses=None):
        self.responses = responses or []
        self.sent_data = []
        self.closed = False
        self.response_index = 0
        
    def sendall(self, data):
        self.sent_data.append(data.decode('utf-8').strip())
        
    def recv(self, buffer_size):
        if self.response_index >= len(self.responses):
            return b''
        response = self.responses[self.response_index]
        self.response_index += 1
        return response
        
    def close(self):
        self.closed = True
        
    def getsockname(self):
        return ('127.0.0.1', 12345)


class TestFTPClient(unittest.TestCase):
    """FTPClient类单元测试"""
    
    def setUp(self):
        """测试前设置"""
        # 创建测试对象
        self.client = FTPClient('example.com', 21)
        
        # 准备模拟响应
        self.welcome_response = b'220 Welcome to FTP server\r\n'
        self.login_responses = [
            b'331 Username ok, need password\r\n',
            b'230 Login successful\r\n'
        ]
        self.pwd_response = b'257 "/home/user" is current directory\r\n'
        self.cwd_response = b'250 Directory changed\r\n'
        self.list_response_start = b'150 Opening data connection\r\n'
        self.list_data = b'-rw-r--r-- 1 user group 123 Jan 1 12:34 file.txt\r\n'
        self.list_response_end = b'226 Transfer complete\r\n'
        
    def tearDown(self):
        """测试后清理"""
        if self.client.cmd_socket and not isinstance(self.client.cmd_socket, MockSocket):
            self.client.quit()
    
    @patch('socket.create_connection')
    def test_connect(self, mock_create_connection):
        """测试连接功能"""
        # 配置模拟对象
        mock_socket = MockSocket([self.welcome_response])
        mock_create_connection.return_value = mock_socket
        
        # 执行连接
        result = self.client.connect()
        
        # 验证结果
        self.assertTrue(result)
        self.assertEqual(self.client.cmd_socket, mock_socket)
        mock_create_connection.assert_called_once_with(('example.com', 21), 30)
    
    @patch('socket.create_connection')
    def test_login(self, mock_create_connection):
        """测试登录功能"""
        # 配置模拟对象
        mock_socket = MockSocket([self.welcome_response] + self.login_responses)
        mock_create_connection.return_value = mock_socket
        
        # 执行连接和登录
        self.client.connect()
        result = self.client.login('user', 'password')
        
        # 验证结果
        self.assertTrue(result)
        self.assertEqual(self.client.username, 'user')
        self.assertTrue(self.client.logged_in)
        self.assertEqual(mock_socket.sent_data[0], 'USER user')
        self.assertEqual(mock_socket.sent_data[1], 'PASS password')
    
    @patch('socket.create_connection')
    def test_pwd(self, mock_create_connection):
        """测试PWD命令"""
        # 配置模拟对象
        mock_socket = MockSocket([self.welcome_response] + self.login_responses + [self.pwd_response])
        mock_create_connection.return_value = mock_socket
        
        # 执行连接、登录、PWD命令
        self.client.connect()
        self.client.login('user', 'password')
        pwd = self.client.pwd()
        
        # 验证结果
        self.assertEqual(pwd, '/home/user')
        self.assertEqual(self.client.working_directory, '/home/user')
        self.assertEqual(mock_socket.sent_data[2], 'PWD')
    
    @patch('socket.create_connection')
    def test_cwd(self, mock_create_connection):
        """测试CWD命令"""
        # 配置模拟对象
        mock_socket = MockSocket([self.welcome_response] + self.login_responses + [self.cwd_response, self.pwd_response])
        mock_create_connection.return_value = mock_socket
        
        # 执行连接、登录、CWD命令
        self.client.connect()
        self.client.login('user', 'password')
        result = self.client.cwd('/home/user/docs')
        
        # 验证结果
        self.assertTrue(result)
        self.assertEqual(mock_socket.sent_data[2], 'CWD /home/user/docs')
    
    @patch('socket.create_connection')
    def test_error_handling(self, mock_create_connection):
        """测试错误处理"""
        # 配置模拟对象
        mock_socket = MockSocket([self.welcome_response, b'530 Login incorrect\r\n'])
        mock_create_connection.return_value = mock_socket
        
        # 执行连接和登录
        self.client.connect()
        
        # 验证登录失败
        with self.assertRaises(AuthenticationError):
            self.client.login('invalid', 'invalid')
    
    @patch('socket.create_connection')
    def test_connection_timeout(self, mock_create_connection):
        """测试连接超时"""
        # 配置模拟抛出超时异常
        mock_create_connection.side_effect = socket.timeout('Connection timed out')
        
        # 验证连接超时异常
        with self.assertRaises(ConnectionError):
            self.client.connect()


class TestFTPConnectionPool(unittest.TestCase):
    """FTP连接池单元测试"""
    
    def setUp(self):
        """测试前设置"""
        # 模拟FTPClient
        self.mock_client = Mock()
        self.mock_client.connected = True
        self.mock_client.verify_connection.return_value = True
        self.mock_client.host = 'example.com'
        self.mock_client.port = 21
        
        # 创建测试对象
        with patch('client.ftp_client.FTPClient') as mock_ftp_client:
            mock_ftp_client.return_value = self.mock_client
            self.pool = FTPConnectionPool('example.com', 21, max_connections=2)
    
    def tearDown(self):
        """测试后清理"""
        if hasattr(self, 'pool'):
            self.pool.close_all()
    
    def test_get_connection(self):
        """测试获取连接"""
        # 获取连接
        client = self.pool.get_connection()
        
        # 验证结果
        self.assertEqual(client, self.mock_client)
        self.assertEqual(self.pool.active_connections, 1)
        self.assertEqual(self.pool.total_connections_created, 1)
    
    def test_release_connection(self):
        """测试释放连接"""
        # 获取连接后释放
        client = self.pool.get_connection()
        self.pool.release_connection(client)
        
        # 验证结果
        self.assertEqual(self.pool.active_connections, 0)
        self.assertEqual(len(self.pool.pool), 1)
    
    def test_max_connections(self):
        """测试最大连接数限制"""
        # 获取两个连接
        client1 = self.pool.get_connection()
        client2 = self.pool.get_connection()
        
        # 尝试获取第三个连接
        client3 = self.pool.get_connection()
        
        # 验证结果
        self.assertIsNotNone(client1)
        self.assertIsNotNone(client2)
        self.assertIsNone(client3)
        self.assertEqual(self.pool.active_connections, 2)
    
    def test_connection_reuse(self):
        """测试连接重用"""
        # 获取连接后释放
        client1 = self.pool.get_connection()
        self.pool.release_connection(client1)
        
        # 再次获取连接
        client2 = self.pool.get_connection()
        
        # 验证结果
        self.assertEqual(client2, self.mock_client)
        self.assertEqual(self.pool.total_connections_created, 1)
        self.assertEqual(self.pool.total_connections_reused, 1)


if __name__ == '__main__':
    unittest.main()
