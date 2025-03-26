import os
import time
import logging
from pathlib import Path
from datetime import datetime

from common.logger import setup_logging
from client.advanced_client import AdvancedFTPClient, TaskPriority, TaskStatus

def demo_progress_callback(task, current, total, elapsed):
    """进度回调函数"""
    percent = int(task.progress)
    print(f"\r任务 {task.id} 进度: {percent}% ({current}/{total} 字节)", end="")

def demo_complete_callback(task):
    """完成回调函数"""
    print(f"\n任务 {task.id} 已完成，耗时: {task.duration:.2f} 秒")
    print(f"结果: {task.result}")

def demo_error_callback(task):
    """错误回调函数"""
    print(f"\n任务 {task.id} 失败: {task.error}")

def main():
    """主函数"""
    # 设置日志
    setup_logging()
    logger = logging.getLogger(__name__)
    
    print("高级FTP客户端示例")
    print("-" * 40)
    
    # 创建临时测试文件
    temp_dir = Path("e:/Python/NewFTP/temp")
    temp_dir.mkdir(exist_ok=True)
    
    test_file = temp_dir / "test_file.txt"
    with open(test_file, "w") as f:
        f.write("这是一个测试文件\n" * 1000)
    
    # 创建客户端
    client = AdvancedFTPClient(max_concurrent_tasks=3)
    
    try:
        # 连接服务器
        print("正在连接FTP服务器...")
        
        # 这里使用你自己的服务器信息
        client.connect(
            host="localhost",
            port=2121,
            username="user",
            password="password",
            enable_ssl=True
        )
        
        print("已连接到FTP服务器")
        
        # 列出目录
        print("\n列出目录内容:")
        list_task = client.list_directory(
            on_complete=demo_complete_callback,
            on_error=demo_error_callback
        )
        
        # 等待列表任务完成
        client.wait_for_task(list_task)
        
        # 创建目录
        print("\n创建测试目录:")
        test_dir = f"test_dir_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        mkdir_task = client.mkdir(
            test_dir,
            on_complete=demo_complete_callback,
            on_error=demo_error_callback
        )
        
        # 等待创建目录任务完成
        client.wait_for_task(mkdir_task)
        
        # 上传文件
        print("\n上传文件:")
        remote_path = f"{test_dir}/test_file.txt"
        upload_task = client.upload(
            str(test_file),
            remote_path,
            priority=TaskPriority.HIGH,
            verify=True,
            on_progress=demo_progress_callback,
            on_complete=demo_complete_callback,
            on_error=demo_error_callback
        )
        
        # 等待上传任务完成
        client.wait_for_task(upload_task)
        
        # 下载文件
        print("\n下载文件:")
        download_path = str(temp_dir / "downloaded_file.txt")
        download_task = client.download(
            remote_path,
            download_path,
            priority=TaskPriority.NORMAL,
            verify=True,
            on_progress=demo_progress_callback,
            on_complete=demo_complete_callback,
            on_error=demo_error_callback
        )
        
        # 等待下载任务完成
        client.wait_for_task(download_task)
        
        # 重命名文件
        print("\n重命名文件:")
        new_name = f"{test_dir}/renamed_file.txt"
        rename_task = client.rename(
            remote_path,
            new_name,
            on_complete=demo_complete_callback,
            on_error=demo_error_callback
        )
        
        # 等待重命名任务完成
        client.wait_for_task(rename_task)
        
        # 删除文件
        print("\n删除文件:")
        delete_task = client.delete(
            new_name,
            on_complete=demo_complete_callback,
            on_error=demo_error_callback
        )
        
        # 等待删除文件任务完成
        client.wait_for_task(delete_task)
        
        # 删除目录
        print("\n删除目录:")
        rmdir_task = client.rmdir(
            test_dir,
            on_complete=demo_complete_callback,
            on_error=demo_error_callback
        )
        
        # 等待删除目录任务完成
        client.wait_for_task(rmdir_task)
        
        # 等待所有任务完成
        print("\n等待所有任务完成...")
        client.wait_all()
        
        print("\n所有任务已完成")
        
        # 获取任务统计
        tasks = client.get_all_tasks()
        print(f"\n任务统计:")
        print(f"- 活动任务: {len(tasks['active'])}")
        print(f"- 已完成任务: {len(tasks['completed'])}")
        print(f"- 失败任务: {len(tasks['failed'])}")
        print(f"- 队列中任务: {tasks['queue_size']}")
        
    except Exception as e:
        logger.exception(f"发生错误: {e}")
        print(f"\n错误: {e}")
    finally:
        # 清理断开连接
        print("\n断开连接...")
        client.disconnect()
        
        print("删除临时文件...")
        try:
            if os.path.exists(test_file):
                os.remove(test_file)
            if os.path.exists(temp_dir / "downloaded_file.txt"):
                os.remove(temp_dir / "downloaded_file.txt")
        except Exception as e:
            print(f"删除临时文件时出错: {e}")
    
    print("\n示例结束")

if __name__ == "__main__":
    main()
