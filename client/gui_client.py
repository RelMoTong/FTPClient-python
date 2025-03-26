#!/usr/bin/env python3
"""FTP客户端GUI应用入口点"""

import sys
import os
import logging
import traceback

# 动态添加项目根目录到Python路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)  # 使用insert(0, ...)确保优先搜索

# 打印调试信息
print(f"项目根目录: {BASE_DIR}")
print(f"Python路径: {sys.path}")
print(f"当前工作目录: {os.getcwd()}")

# 确保配置目录存在
config_dir = os.path.join(BASE_DIR, 'config')
if not os.path.exists(config_dir):
    try:
        os.makedirs(config_dir, exist_ok=True)
        print(f"已创建配置目录: {config_dir}")
    except Exception as e:
        print(f"无法创建配置目录: {e}")

# 检查common目录是否存在且可访问
common_dir = os.path.join(BASE_DIR, 'common')
print(f"common目录是否存在: {os.path.exists(common_dir)}")
if os.path.exists(common_dir):
    print(f"common目录内容: {os.listdir(common_dir)}")

try:
    # 创建默认客户端配置
    client_config_path = os.path.join(config_dir, 'client_config.json')
    if not os.path.exists(client_config_path):
        print(f"创建默认客户端配置: {client_config_path}")
        import json
        default_config = {
            "default_host": "localhost",
            "default_port": 2121,
            "enable_ssl": True,
            "timeout": 30,
            "retry_count": 3,
            "retry_delay": 5,
            "max_concurrent_transfers": 3,
            "log_level": "INFO"
        }
        with open(client_config_path, 'w') as f:
            json.dump(default_config, f, indent=4)
    
    # 立即初始化日志系统
    from common.logger import setup_logging
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # 将Qt相关导入放在日志初始化之后
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QDir, QCoreApplication, Qt
    
    # 设置应用程序属性防止冻结
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    from client.gui.main_window import MainWindow, register_meta_types
    
    def main():
        """主函数"""
        try:
            # 注册元类型
            register_meta_types()
            
            # 创建应用程序
            app = QApplication(sys.argv)
            app.setApplicationName("NewFTP客户端")
            
            # 设置组织信息用于QSettings
            app.setOrganizationName("NewFTP")
            app.setOrganizationDomain("newftp.example.com")
            
            # 设置样式表
            app.setStyle("Fusion")
            
            # 创建主窗口
            main_window = MainWindow()
            main_window.show()
            
            # 运行应用程序
            sys.exit(app.exec_())
            
        except Exception as e:
            logger.exception(f"应用程序启动失败: {str(e)}")
            print(f"错误: {str(e)}")
            print(f"调用堆栈: {traceback.format_exc()}")
            sys.exit(1)
    
    if __name__ == "__main__":
        main()
except ImportError as e:
    print(f"导入错误: {e}")
    print(f"Python版本: {sys.version}")
    print(f"Python可执行文件: {sys.executable}")
    print(f"调用堆栈: {traceback.format_exc()}")
    sys.exit(1)
