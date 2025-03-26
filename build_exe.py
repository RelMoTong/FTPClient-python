import os
import sys
import shutil
import subprocess
from pathlib import Path

def clean_build_dirs():
    """清理构建目录"""
    dirs_to_clean = ['build', 'dist']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            print(f"正在清理目录: {dir_name}")
            shutil.rmtree(dir_name)

def build_cli_version():
    """构建命令行版本"""
    print("正在构建命令行版本...")
    
    # 命令行参数
    cmd = [
        'pyinstaller',
        '--name=NewFTP-CLI',
        '--onefile',  # 生成单文件
        '--console',  # 控制台应用
        '--icon=resources/ftp_icon.ico',
        '--add-data=config/client_config.json;config',
        '--clean',
        'client/ftp_cli.py'
    ]
    
    # 运行 PyInstaller
    subprocess.run(cmd)
    print("命令行版本构建完成")

def build_gui_version():
    """构建图形界面版本"""
    print("正在构建图形界面版本...")
    
    # 图形界面参数
    cmd = [
        'pyinstaller',
        '--name=NewFTP-GUI',
        '--onefile',  # 生成单文件
        '--windowed',  # GUI 应用，不显示控制台
        '--icon=resources/ftp_icon.ico',
        '--add-data=config/client_config.json;config',
        '--add-data=resources/*;resources',
        '--hidden-import=PyQt5.sip',
        '--clean',
        'client/gui_client.py'  # 使用现有的gui_client.py作为入口
    ]
    
    # 运行 PyInstaller
    subprocess.run(cmd)
    print("图形界面版本构建完成")

def ensure_directory_exists(directory_path):
    """确保目录存在，如果不存在则创建它及其所有父目录"""
    try:
        directory_path.mkdir(parents=True, exist_ok=True)
        print(f"已确保目录存在: {directory_path}")
        return True
    except PermissionError:
        print(f"错误: 没有权限创建目录: {directory_path}")
        return False
    except Exception as e:
        print(f"错误: 创建目录时出错: {directory_path}, {str(e)}")
        return False

def create_resources():
    """创建资源目录和图标文件"""
    base_dir = Path("e:/Python/NewFTP")
    resources_dir = base_dir / "resources"
    
    if not ensure_directory_exists(resources_dir):
        return False
    
    # 如果没有图标，创建一个简单的文本提示
    icon_path = resources_dir / "ftp_icon.ico"
    if not icon_path.exists():
        print("注意: 未找到图标文件。请将适合的 .ico 文件复制到 resources 目录下并命名为 ftp_icon.ico")
        with open(resources_dir / "README.txt", "w") as f:
            f.write("请将应用图标文件放在此目录下，并命名为 ftp_icon.ico")
    
    # 确保config目录也存在
    config_dir = base_dir / "config"
    if not ensure_directory_exists(config_dir):
        return False
        
    # 检查客户端配置文件是否存在
    client_config = config_dir / "client_config.json"
    if not client_config.exists():
        print("注意: 未找到客户端配置文件，将创建默认配置")
        with open(client_config, "w") as f:
            f.write('''{
    "default_host": "localhost",
    "default_port": 2121,
    "enable_ssl": true,
    "timeout": 30,
    "retry_count": 3,
    "retry_delay": 5,
    "max_concurrent_transfers": 3,
    "log_level": "INFO"
}''')
    
    return True

def check_project_structure():
    """检查项目结构并创建必要的目录"""
    base_dir = Path("e:/Python/NewFTP")
    directories = [
        base_dir / "client",
        base_dir / "client/gui", 
        base_dir / "common",
        base_dir / "config",
        base_dir / "logs",
        base_dir / "db",
        base_dir / "tests"
    ]
    
    all_success = True
    for directory in directories:
        if not ensure_directory_exists(directory):
            all_success = False
    
    return all_success

def create_main_entry():
    """创建GUI主入口文件"""
    gui_dir = Path("client/gui")
    gui_dir.mkdir(exist_ok=True)
    
    # 创建 main.py 作为 GUI 入口点
    main_path = gui_dir / "main.py"
    if not main_path.exists():
        print("创建 GUI 入口文件...")
        with open(main_path, "w") as f:
            f.write("""# filepath: client/gui/main.py
import sys
from PyQt5.QtWidgets import QApplication
from client.gui.main_window import MainWindow

def main():
    \"\"\"主函数\"\"\"
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
""")

def main():
    """主函数"""
    print("=== NewFTP 可执行文件构建工具 ===")
    
    # 检查并创建项目目录结构
    if not check_project_structure():
        print("错误: 无法创建必要的项目目录结构，构建已取消")
        return
    
    # 创建必要的资源文件
    if not create_resources():
        print("错误: 无法创建必要的资源文件，构建已取消")
        return
    
    # 清理旧的构建文件
    clean_build_dirs()
    
    # 构建两个版本
    build_mode = input("选择构建模式 (1=仅命令行, 2=仅GUI, 3=两者皆构建) [3]: ") or "3"
    
    try:
        if build_mode in ("1", "3"):
            build_cli_version()
        
        if build_mode in ("2", "3"):
            build_gui_version()
        
        print("\n构建完成！可执行文件位于 dist 目录下：")
        if build_mode in ("1", "3"):
            print("- NewFTP-CLI.exe (命令行版本)")
        if build_mode in ("2", "3"):
            print("- NewFTP-GUI.exe (图形界面版本)")
    except Exception as e:
        print(f"构建过程中出错: {str(e)}")

if __name__ == "__main__":
    main()
