import os
import sys
import logging
import argparse
import getpass
from datetime import datetime

from common.logger import setup_logging
from common.config import Config
from client.ftp_client import FTPClient
from common.protocol import TransferMode, ConnectionMode
from common.utils import format_size, calculate_transfer_speed

def setup_cli():
    """设置命令行参数解析"""
    parser = argparse.ArgumentParser(description='FTP客户端命令行工具')
    
    # 连接参数
    parser.add_argument('--host', help='服务器主机名或IP')
    parser.add_argument('--port', type=int, default=21, help='服务器端口')
    parser.add_argument('--user', help='用户名')
    parser.add_argument('--password', help='密码')
    parser.add_argument('--ssl', action='store_true', help='使用SSL/TLS加密')
    parser.add_argument('--timeout', type=int, default=30, help='连接超时（秒）')
    parser.add_argument('--passive', action='store_true', default=True, help='使用被动模式')
    parser.add_argument('--active', action='store_true', help='使用主动模式')
    
    # 操作参数
    subparsers = parser.add_subparsers(dest='command', help='命令')
    
    # ls命令
    ls_parser = subparsers.add_parser('ls', help='列出目录内容')
    ls_parser.add_argument('path', nargs='?', default='.', help='要列出的目录路径')
    ls_parser.add_argument('-a', '--all', action='store_true', help='显示隐藏文件')
    ls_parser.add_argument('-l', '--long', action='store_true', help='使用详细格式显示')
    
    # cd命令
    cd_parser = subparsers.add_parser('cd', help='更改工作目录')
    cd_parser.add_argument('path', help='目标目录')
    
    # pwd命令
    pwd_parser = subparsers.add_parser('pwd', help='显示当前工作目录')
    
    # get命令
    get_parser = subparsers.add_parser('get', help='下载文件')
    get_parser.add_argument('remote_path', help='远程文件路径')
    get_parser.add_argument('local_path', nargs='?', help='本地保存路径')
    get_parser.add_argument('-r', '--resume', action='store_true', help='断点续传')
    get_parser.add_argument('-a', '--ascii', action='store_true', help='使用ASCII模式')
    
    # put命令
    put_parser = subparsers.add_parser('put', help='上传文件')
    put_parser.add_argument('local_path', help='本地文件路径')
    put_parser.add_argument('remote_path', nargs='?', help='远程保存路径')
    put_parser.add_argument('-r', '--resume', action='store_true', help='断点续传')
    put_parser.add_argument('-a', '--ascii', action='store_true', help='使用ASCII模式')
    
    # mkdir命令
    mkdir_parser = subparsers.add_parser('mkdir', help='创建目录')
    mkdir_parser.add_argument('path', help='要创建的目录名')
    
    # rmdir命令
    rmdir_parser = subparsers.add_parser('rmdir', help='删除目录')
    rmdir_parser.add_argument('path', help='要删除的目录名')
    
    # delete命令
    delete_parser = subparsers.add_parser('delete', help='删除文件')
    delete_parser.add_argument('path', help='要删除的文件路径')
    
    # rename命令
    rename_parser = subparsers.add_parser('rename', help='重命名文件或目录')
    rename_parser.add_argument('from_path', help='原路径')
    rename_parser.add_argument('to_path', help='新路径')
    
    return parser.parse_args()

def print_progress(transferred, total, elapsed):
    """显示传输进度"""
    if total > 0:
        percent = min(int(transferred * 100 / total), 100)
    else:
        percent = 0
    
    speed = calculate_transfer_speed(transferred, elapsed)
    sys.stdout.write(f"\r{transferred}/{total} 字节 ({percent}%) - {speed}")
    sys.stdout.flush()

def format_listing(items, long_format=False):
    """格式化目录列表输出"""
    if not items:
        return "目录为空"
    
    result = []
    
    if long_format:
        # 详细格式
        for item in items:
            if 'type' in item and item['type'] == 'dir':
                type_char = 'd'
            else:
                type_char = '-'
            
            size_str = format_size(item.get('size', 0))
            date_str = item.get('date', '')
            
            permissions = item.get('permissions', '?????????')
            name = item.get('name', '')
            
            result.append(f"{type_char}{permissions} {size_str:>8} {date_str} {name}")
    else:
        # 简单格式
        for item in items:
            name = item.get('name', '')
            if 'type' in item and item['type'] == 'dir':
                result.append(f"{name}/")
            else:
                result.append(name)
    
    return '\n'.join(result)

def main():
    """主函数"""
    # 设置日志
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # 解析命令行参数
    args = setup_cli()
    
    # 加载配置
    config_path = os.path.join("e:", "Python", "NewFTP", "config", "client_config.json")
    config = Config(config_path)
    
    # 获取连接参数
    host = args.host or config.get('default_host') or input("FTP服务器地址: ")
    port = args.port or config.get('default_port') or 21
    user = args.user or input("用户名 [anonymous]: ") or "anonymous"
    
    if args.password:
        password = args.password
    else:
        password = getpass.getpass(f"密码 (用户 {user}): ")
    
    ssl_enabled = args.ssl or config.get('enable_ssl') or False
    timeout = args.timeout or config.get('timeout') or 30
    
    # 确定连接模式
    if args.active:
        connection_mode = ConnectionMode.ACTIVE
    else:
        connection_mode = ConnectionMode.PASSIVE
    
    try:
        # 创建FTP客户端
        client = FTPClient(host=host, port=port, timeout=timeout, enable_ssl=ssl_enabled)
        
        # 设置连接模式
        client.set_connection_mode(connection_mode)
        
        # 设置进度回调
        client.set_progress_callback(print_progress)
        
        # 连接并登录
        client.connect()
        client.login(user, password)
        
        print(f"已连接到 {host}:{port}")
        
        # 执行命令
        if args.command == 'ls':
            try:
                items = client.list(args.path)
                print(format_listing(items, args.long))
            except Exception as e:
                print(f"列出目录失败: {str(e)}")
                
        elif args.command == 'cd':
            try:
                client.cwd(args.path)
                print(f"当前目录: {client.pwd()}")
            except Exception as e:
                print(f"更改目录失败: {str(e)}")
                
        elif args.command == 'pwd':
            try:
                pwd = client.pwd()
                print(f"当前目录: {pwd}")
            except Exception as e:
                print(f"获取当前目录失败: {str(e)}")
                
        elif args.command == 'get':
            try:
                # 如果未指定本地路径，使用远程文件名
                local_path = args.local_path
                if not local_path:
                    local_path = os.path.basename(args.remote_path)
                
                # 设置传输模式
                mode = TransferMode.ASCII if args.ascii else None
                
                # 下载文件
                print(f"正在下载 {args.remote_path} 到 {local_path}...")
                success, size, elapsed = client.download(
                    args.remote_path, 
                    local_path, 
                    mode=mode, 
                    resume=args.resume
                )
                
                print(f"\n下载完成，共 {format_size(size)}，耗时 {elapsed:.2f} 秒，"
                      f"平均速度 {calculate_transfer_speed(size, elapsed)}")
                
            except Exception as e:
                print(f"下载文件失败: {str(e)}")
                
        elif args.command == 'put':
            try:
                # 如果未指定远程路径，使用本地文件名
                remote_path = args.remote_path
                if not remote_path:
                    remote_path = os.path.basename(args.local_path)
                
                # 设置传输模式
                mode = TransferMode.ASCII if args.ascii else None
                
                # 上传文件
                print(f"正在上传 {args.local_path} 到 {remote_path}...")
                success, size, elapsed = client.upload(
                    args.local_path, 
                    remote_path, 
                    mode=mode, 
                    resume=args.resume
                )
                
                print(f"\n上传完成，共 {format_size(size)}，耗时 {elapsed:.2f} 秒，"
                      f"平均速度 {calculate_transfer_speed(size, elapsed)}")
                
            except Exception as e:
                print(f"上传文件失败: {str(e)}")
                
        elif args.command == 'mkdir':
            try:
                path = client.mkd(args.path)
                print(f"已创建目录: {path}")
            except Exception as e:
                print(f"创建目录失败: {str(e)}")
                
        elif args.command == 'rmdir':
            try:
                client.rmd(args.path)
                print(f"已删除目录: {args.path}")
            except Exception as e:
                print(f"删除目录失败: {str(e)}")
                
        elif args.command == 'delete':
            try:
                client.delete(args.path)
                print(f"已删除文件: {args.path}")
            except Exception as e:
                print(f"删除文件失败: {str(e)}")
                
        elif args.command == 'rename':
            try:
                client.rename(args.from_path, args.to_path)
                print(f"已将 {args.from_path} 重命名为 {args.to_path}")
            except Exception as e:
                print(f"重命名失败: {str(e)}")
        
        else:
            print("请指定要执行的命令。使用 --help 查看帮助。")
            
    except Exception as e:
        logger.error(f"发生错误: {str(e)}")
        print(f"错误: {str(e)}")
        sys.exit(1)
    finally:
        # 关闭连接
        if 'client' in locals() and hasattr(client, 'quit'):
            client.quit()

if __name__ == "__main__":
    main()
