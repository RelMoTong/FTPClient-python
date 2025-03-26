import os
import sys
import json
import shutil
from pathlib import Path

def create_directory_structure():
    """创建项目目录结构"""
    base_dir = Path("e:/Python/NewFTP")
    
    # 创建目录
    directories = [
        "client",
        "server",
        "common",
        "config",
        "logs",
        "db",
        "tests"
    ]
    
    for directory in directories:
        dir_path = base_dir / directory
        dir_path.mkdir(exist_ok=True)
        print(f"创建目录: {dir_path}")
    
    # 创建配置文件
    create_default_configs(base_dir)
    
    print("项目初始化完成！")

def create_default_configs(base_dir):
    """创建默认配置文件"""
    config_dir = base_dir / "config"
    
    # 确保配置目录存在
    config_dir.mkdir(exist_ok=True)
    
    # 服务端配置
    server_config = {
        "host": "0.0.0.0",
        "port": 2121,
        "pasv_ports": [60000, 60100],
        "max_connections": 10,
        "timeout": 300,
        "enable_ssl": False,  # 改为False以暂时禁用SSL
        "cert_file": "config/server.crt",
        "key_file": "config/server.key",
        "db_file": "db/users.db",
        "allow_list": "config/allow_list.conf",
        "bandwidth_limit": 10485760,  # 10MB/s
        "log_level": "INFO"
    }
    
    with open(config_dir / "server_config.json", "w") as f:
        json.dump(server_config, f, indent=4)
    
    # 客户端配置
    client_config = {
        "default_host": "localhost",
        "default_port": 2121,
        "enable_ssl": False,  # 改为False以暂时禁用SSL,  # 改为False以暂时禁用SSL
        "timeout": 30,
        "retry_count": 3,
        "retry_delay": 5,
        "max_concurrent_transfers": 3,
        "log_level": "INFO"
    }
    
    with open(config_dir / "client_config.json", "w") as f:
        json.dump(client_config, f, indent=4)
    
    # IP白名单
    with open(config_dir / "allow_list.conf", "w") as f:
        f.write("# IP白名单配置文件\n")
        f.write("# 每行一个IP或CIDR格式的网段\n")
        f.write("127.0.0.1\n")
        f.write("::1\n")
        f.write("192.168.0.0/16\n")
    
    print("默认配置文件创建完成")

if __name__ == "__main__":
    create_directory_structure()
