import socket
import time
import logging
import ssl
import sys
import os
import argparse
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.append(str(Path(__file__).parent.parent))

from common.config import Config
from common.exceptions import ConnectionError, AuthenticationError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("连接测试")

def test_socket_connection(host, port, timeout=5):
    """测试简单的套接字连接"""
    logger.info(f"测试与 {host}:{port} 的TCP连接...")
    try:
        start_time = time.time()
        with socket.create_connection((host, port), timeout) as sock:
            elapsed = time.time() - start_time
            logger.info(f"✅ 成功连接，耗时 {elapsed:.3f} 秒")
            
            # 尝试读取欢迎消息
            try:
                data = sock.recv(1024)
                if data:
                    logger.info(f"收到服务器消息: {data.decode('utf-8', errors='ignore').strip()}")
                    return True, None
            except Exception as e:
                logger.warning(f"读取欢迎消息失败: {e}")
            return True, None
    except socket.timeout:
        logger.error(f"❌ 连接超时，服务器未响应 (超过 {timeout} 秒)")
        return False, "连接超时"
    except socket.gaierror as e:
        logger.error(f"❌ 域名解析失败: {e}")
        return False, f"域名解析失败: {e}"
    except ConnectionRefusedError:
        logger.error(f"❌ 连接被拒绝，端口可能未开放或被防火墙阻止")
        return False, "连接被拒绝"
    except Exception as e:
        logger.error(f"❌ 连接失败: {e}")
        return False, str(e)

def test_ftp_client(host, port, username="anonymous", password="", use_ssl=False, timeout=10):
    """使用FTP客户端库进行测试"""
    logger.info(f"测试FTP客户端连接 {'(带SSL)' if use_ssl else ''} 到 {host}:{port}...")
    
    try:
        import ftplib
        start_time = time.time()
        
        if use_ssl:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            client = ftplib.FTP_TLS(context=context)
        else:
            client = ftplib.FTP()
        
        client.connect(host, port, timeout)
        elapsed = time.time() - start_time
        logger.info(f"✅ 连接成功，耗时 {elapsed:.3f} 秒")
        
        # 显示欢迎消息
        logger.info(f"欢迎消息: {client.welcome}")
        
        # 尝试登录
        logger.info(f"尝试以用户名 '{username}' 登录...")
        client.login(username, password)
        logger.info("✅ 登录成功!")
        
        # 获取系统信息
        try:
            system_info = client.sendcmd("SYST")
            logger.info(f"系统信息: {system_info}")
        except:
            logger.warning("无法获取系统信息")
        
        # 列出目录
        try:
            logger.info("尝试列出根目录内容...")
            files = client.nlst()
            logger.info(f"✅ 目录列表获取成功: {files[:10]} " + ("..." if len(files) > 10 else ""))
        except Exception as e:
            logger.warning(f"列出目录失败: {e}")
        
        # 关闭连接
        client.quit()
        logger.info("FTP连接已正常关闭")
        return True, None
        
    except ftplib.error_perm as e:
        logger.error(f"❌ 权限错误: {e}")
        return False, f"权限错误: {e}"
    except ftplib.error_temp as e:
        logger.error(f"❌ 临时错误: {e}")
        return False, f"临时错误: {e}" 
    except ftplib.error_proto as e:
        logger.error(f"❌ 协议错误: {e}")
        return False, f"协议错误: {e}"
    except ssl.SSLError as e:
        logger.error(f"❌ SSL错误: {e}")
        return False, f"SSL错误: {e}"
    except socket.timeout as e:
        logger.error(f"❌ 连接超时: {e}")
        return False, f"连接超时: {e}"
    except Exception as e:
        logger.error(f"❌ 连接失败: {e}")
        return False, str(e)

def test_custom_client(host, port, username="anonymous", password="", use_ssl=False):
    """使用自定义FTP客户端进行测试"""
    logger.info(f"测试自定义FTP客户端连接到 {host}:{port}...")
    
    try:
        from client.ftp_client import FTPClient
        
        client = FTPClient(host=host, port=port, enable_ssl=use_ssl)
        
        # 连接
        logger.info("尝试连接...")
        client.connect()
        logger.info("✅ 连接成功!")
        
        # 登录
        logger.info(f"尝试以用户名 '{username}' 登录...")
        client.login(username, password)
        logger.info("✅ 登录成功!")
        
        # 发送NOOP命令测试
        logger.info("发送NOOP命令...")
        client._send_command("NOOP")
        response = client._read_response()
        logger.info(f"NOOP响应: {response}")
        
        # 获取当前目录
        logger.info("获取当前工作目录...")
        client.pwd()
        logger.info(f"✅ 当前目录: {client.current_directory}")
        
        # 列出目录
        logger.info("列出目录内容...")
        files = client.list()
        logger.info(f"✅ 目录列表: {files[:10]}" + ("..." if len(files) > 10 else ""))
        
        # 关闭连接
        client.quit()
        logger.info("FTP连接已正常关闭")
        return True, None
        
    except ConnectionError as e:
        logger.error(f"❌ 连接错误: {e}")
        return False, f"连接错误: {e}"
    except AuthenticationError as e:
        logger.error(f"❌ 认证错误: {e}")
        return False, f"认证错误: {e}"
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        return False, str(e)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="FTP连接测试工具")
    parser.add_argument("--host", default="localhost", help="FTP服务器主机")
    parser.add_argument("--port", type=int, default=2121, help="FTP服务器端口")
    parser.add_argument("--username", default="anonymous", help="FTP用户名")
    parser.add_argument("--password", default="", help="FTP密码")
    parser.add_argument("--ssl", action="store_true", help="使用SSL连接")
    parser.add_argument("--timeout", type=int, default=10, help="连接超时(秒)")
    parser.add_argument("--config", help="配置文件路径")
    
    args = parser.parse_args()
    
    # 如果指定了配置文件，从配置加载
    if args.config:
        try:
            config = Config(args.config)
            args.host = args.host or config.get('default_host')
            args.port = args.port or config.get('default_port')
            args.ssl = args.ssl or config.get('enable_ssl')
        except Exception as e:
            logger.warning(f"无法从配置文件加载: {e}")
    
    print("\n========== FTP连接测试 ==========")
    print(f"目标: {args.host}:{args.port}")
    print(f"用户名: {args.username}")
    print(f"使用SSL: {'是' if args.ssl else '否'}")
    print("=================================\n")
    
    # 测试1: 基本套接字连接
    socket_result, socket_error = test_socket_connection(args.host, args.port, args.timeout)
    print()
    
    # 测试2: 标准FTP客户端
    ftp_result, ftp_error = test_ftp_client(args.host, args.port, args.username, args.password, args.ssl, args.timeout)
    print()
    
    # 测试3: 自定义FTP客户端
    try:
        custom_result, custom_error = test_custom_client(args.host, args.port, args.username, args.password, args.ssl)
    except ModuleNotFoundError:
        logger.warning("❌ 自定义FTP客户端模块未找到，跳过测试")
        custom_result, custom_error = False, "模块未找到"
    print()
    
    # 总结报告
    print("\n========== 测试结果摘要 ==========")
    print(f"基本套接字连接: {'✅ 成功' if socket_result else '❌ 失败'}")
    if not socket_result:
        print(f"  - 原因: {socket_error}")
    
    print(f"标准FTP客户端: {'✅ 成功' if ftp_result else '❌ 失败'}")
    if not ftp_result:
        print(f"  - 原因: {ftp_error}")
    
    print(f"自定义FTP客户端: {'✅ 成功' if custom_result else '❌ 失败'}")
    if not custom_result:
        print(f"  - 原因: {custom_error}")
    print("==================================")
    
    # 建议
    print("\n诊断建议:")
    if not socket_result:
        print(" - 检查目标服务器是否在运行")
        print(" - 检查防火墙是否允许连接到该端口")
        print(" - 验证主机名和端口是否正确")
    elif not ftp_result:
        print(" - FTP服务可能已启动但配置问题导致无法正确响应")
        print(" - 检查用户名和密码是否正确")
        if args.ssl:
            print(" - SSL证书配置可能有问题，尝试禁用SSL")
    elif not custom_result:
        print(" - 自定义FTP客户端可能有逻辑错误")
        print(" - 检查自定义FTP客户端代码")

if __name__ == "__main__":
    main()
