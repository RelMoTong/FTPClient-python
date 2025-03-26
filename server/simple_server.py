import os
import sys
import logging
import argparse
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.append(str(Path(__file__).parent.parent))

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
from common.config import Config

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("SimpleServer")

def start_server(host='127.0.0.1', port=2121, root_dir=None, 
                allow_anonymous=True, users=None, passive_ports=None):
    """
    启动一个简单的FTP服务器
    
    Args:
        host (str): 监听地址
        port (int): 监听端口
        root_dir (str): FTP根目录
        allow_anonymous (bool): 是否允许匿名访问
        users (list): 用户列表 [(username, password, directory, permissions), ...]
        passive_ports (tuple): 被动模式端口范围 (min, max)
    """
    # 确定根目录
    if root_dir is None:
        root_dir = str(Path.home() / "ftp_root")
        # 如果目录不存在则创建
        Path(root_dir).mkdir(exist_ok=True)
        logger.info(f"使用默认FTP根目录: {root_dir}")
    
    # 创建认证器
    authorizer = DummyAuthorizer()
    
    # 添加匿名用户
    if allow_anonymous:
        perm = "elradfmwMT"  # 所有权限
        authorizer.add_anonymous(root_dir, perm=perm)
        logger.info(f"已添加匿名用户访问权限: {root_dir}")
    
    # 添加具名用户
    if users:
        for username, password, directory, permissions in users:
            user_dir = directory or root_dir
            Path(user_dir).mkdir(exist_ok=True)
            authorizer.add_user(username, password, user_dir, perm=permissions)
            logger.info(f"已添加用户 '{username}' 访问权限: {user_dir}")
    else:
        # 添加默认测试用户
        test_user_dir = os.path.join(root_dir, "test_user")
        Path(test_user_dir).mkdir(exist_ok=True)
        authorizer.add_user("user", "password", test_user_dir, perm="elradfmwMT")
        logger.info(f"已添加默认测试用户 'user' (密码: 'password') 访问权限: {test_user_dir}")
    
    # 设置处理器
    handler = FTPHandler
    handler.authorizer = authorizer
    
    # 设置被动模式端口
    if passive_ports:
        handler.passive_ports = range(passive_ports[0], passive_ports[1] + 1)
        logger.info(f"被动模式端口范围: {passive_ports}")
    
    # 启动服务器
    server = FTPServer((host, port), handler)
    logger.info(f"启动FTP服务器: {host}:{port}")
    
    # 运行服务器
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("接收到中断信号，服务器正在关闭...")
        server.close_all()
        sys.exit(0)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="简单的FTP测试服务器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=2121, help="监听端口")
    parser.add_argument("--root", help="FTP根目录")
    parser.add_argument("--no-anonymous", action="store_true", help="禁用匿名访问")
    parser.add_argument("--config", help="配置文件路径")
    
    args = parser.parse_args()
    
    # 如果指定了配置文件，从配置加载
    config_params = {}
    if args.config:
        try:
            config = Config(args.config)
            config_params["host"] = config.get("host", "127.0.0.1")
            config_params["port"] = int(config.get("port", 2121))
            config_params["passive_ports"] = (
                config.get("pasv_ports", [60000, 60100])[0],
                config.get("pasv_ports", [60000, 60100])[1]
            )
            logger.info(f"已从配置文件加载设置: {args.config}")
        except Exception as e:
            logger.warning(f"无法从配置文件加载: {e}")
    
    # 命令行参数覆盖配置文件
    if args.host:
        config_params["host"] = args.host
    if args.port:
        config_params["port"] = args.port
    if args.root:
        config_params["root_dir"] = args.root
    
    config_params["allow_anonymous"] = not args.no_anonymous
    
    print("\n========== 简易FTP服务器 ==========")
    print(f"监听地址: {config_params.get('host', '127.0.0.1')}:{config_params.get('port', 2121)}")
    print(f"根目录: {config_params.get('root_dir', '自动创建')}")
    print(f"匿名访问: {'已禁用' if args.no_anonymous else '已启用'}")
    print("===================================\n")
    
    print("服务器已启动，按 Ctrl+C 停止\n")
    
    # 启动服务器
    start_server(**config_params)

if __name__ == "__main__":
    main()
