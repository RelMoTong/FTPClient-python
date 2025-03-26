"""FTP客户端主窗口"""

import os
import sys
import logging
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QTabWidget, 
                           QAction, QMessageBox, QFileDialog, QInputDialog,
                           QToolBar, QStatusBar, QSplitter, QStyle, QProgressDialog, QApplication)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot, QMetaType
from PyQt5.QtGui import QIcon

from client.gui.login_dialog import LoginDialog
from client.gui.file_browser import FileBrowser
from client.gui.transfer_manager import TransferManager
from client.advanced_client import AdvancedFTPClient, TaskType, TaskPriority, TaskStatus

logger = logging.getLogger(__name__)

# 注册Qt元类型，解决Cannot queue arguments of type 'QVector<int>'问题
def register_meta_types():
    try:
        # 正确方式是通过QMetaType注册类型
        QMetaType.type("QVector<int>")
        QMetaType.type("QVector<QModelIndex>")
        
        # 如果需要使用qRegisterMetaType，需要明确导入
        from PyQt5.QtCore import qRegisterMetaType
        qRegisterMetaType("QVector<int>")
        qRegisterMetaType("QVector<QModelIndex>")
    except Exception as e:
        logger.warning(f"注册Qt元类型失败: {e}")

class MainWindow(QMainWindow):
    """FTP客户端主窗口"""
    
    def __init__(self):
        super().__init__()
        
        # 注册Qt元类型
        register_meta_types()
        
        self.setWindowTitle("NewFTP客户端")
        self.resize(1024, 768)
        
        # FTP客户端
        self.client = AdvancedFTPClient(max_concurrent_tasks=3)  # 减少并发任务数量避免频繁连接断开
        
        # 创建界面
        self.setup_ui()
        
        # 连接信号
        self.connect_signals()
        
        # 任务状态刷新定时器
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_task_status)
        self.timer.start(2000)  # 降低刷新频率，减少负载
        
        # 当前连接状态
        self.connected = False
        
        # 显示连接对话框
        QTimer.singleShot(100, self.show_login_dialog)
    
    def setup_ui(self):
        """设置界面"""
        # 中心部件
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        
        # 创建选项卡窗口部件
        self.tab_widget = QTabWidget()
        
        # 文件浏览器选项卡
        self.file_browser = FileBrowser()
        self.tab_widget.addTab(self.file_browser, "文件浏览")
        
        # 传输管理器选项卡
        self.transfer_manager = TransferManager()
        self.tab_widget.addTab(self.transfer_manager, "传输队列")
        
        main_layout.addWidget(self.tab_widget)
        self.setCentralWidget(central_widget)
        
        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")
        
        # 重要：在使用图标之前先加载
        self.load_icons()
        
        # 创建菜单
        self.setup_menu()
        
        # 创建工具栏
        self.setup_toolbar()
    
    def load_icons(self):
        """加载图标"""
        # 使用标准图标
        style = self.style()
        self.icons = {
            'connect': style.standardIcon(QStyle.SP_ComputerIcon),
            'disconnect': style.standardIcon(QStyle.SP_BrowserStop),
            'refresh': style.standardIcon(QStyle.SP_BrowserReload),
            'upload': style.standardIcon(QStyle.SP_ArrowUp),
            'download': style.standardIcon(QStyle.SP_ArrowDown),
            'folder': style.standardIcon(QStyle.SP_DirIcon),
            'file': style.standardIcon(QStyle.SP_FileIcon),
            'delete': style.standardIcon(QStyle.SP_TrashIcon),
            # 修改设置图标，使用一个更合适的替代品
            'settings': style.standardIcon(QStyle.SP_FileDialogDetailedView),
            'exit': style.standardIcon(QStyle.SP_DialogCloseButton),
            'bookmark': style.standardIcon(QStyle.SP_DialogSaveButton)
        }

    def setup_menu(self):
        """设置菜单"""
        # 文件菜单
        file_menu = self.menuBar().addMenu("文件(&F)")
        
        connect_action = QAction(self.icons['connect'], "连接(&C)...", self)
        connect_action.triggered.connect(self.show_login_dialog)
        file_menu.addAction(connect_action)
        
        bookmarks_action = QAction(self.icons['bookmark'], "书签(&B)...", self)
        bookmarks_action.triggered.connect(self.show_bookmarks)
        file_menu.addAction(bookmarks_action)
        
        disconnect_action = QAction(self.icons['disconnect'], "断开连接(&D)", self)
        disconnect_action.triggered.connect(self.disconnect)
        file_menu.addAction(disconnect_action)
        
        file_menu.addSeparator()
        
        settings_action = QAction(self.icons['settings'], "设置(&S)...", self)
        settings_action.triggered.connect(self.show_settings)
        file_menu.addAction(settings_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction(self.icons['exit'], "退出(&X)", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 传输菜单
        transfer_menu = self.menuBar().addMenu("传输(&T)")
        
        upload_action = QAction(self.icons['upload'], "上传文件(&U)...", self)
        upload_action.triggered.connect(self.upload_file_dialog)
        transfer_menu.addAction(upload_action)
        
        download_action = QAction(self.icons['download'], "下载文件(&D)...", self)
        download_action.triggered.connect(self.download_file_dialog)
        transfer_menu.addAction(download_action)
        
        transfer_menu.addSeparator()
        
        clear_action = QAction(self.icons['delete'], "清除已完成的传输(&C)", self)
        clear_action.triggered.connect(self.transfer_manager.clear_completed_tasks)
        transfer_menu.addAction(clear_action)
        
        # 操作菜单
        operation_menu = self.menuBar().addMenu("操作(&O)")
        
        refresh_action = QAction("刷新(&R)", self)
        refresh_action.triggered.connect(self.refresh_remote)
        operation_menu.addAction(refresh_action)
        
        mkdir_action = QAction("新建文件夹(&N)...", self)
        mkdir_action.triggered.connect(self.create_remote_directory)
        operation_menu.addAction(mkdir_action)
        
        # 帮助菜单
        help_menu = self.menuBar().addMenu("帮助(&H)")
        
        about_action = QAction("关于(&A)...", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def setup_toolbar(self):
        """设置工具栏"""
        toolbar = QToolBar("主工具栏", self)
        self.addToolBar(toolbar)
        
        connect_action = QAction(self.icons['connect'], "连接", self)
        connect_action.triggered.connect(self.show_login_dialog)
        toolbar.addAction(connect_action)
        
        disconnect_action = QAction(self.icons['disconnect'], "断开", self)
        disconnect_action.triggered.connect(self.disconnect)
        toolbar.addAction(disconnect_action)
        
        toolbar.addSeparator()
        
        refresh_action = QAction(self.icons['refresh'], "刷新", self)
        refresh_action.triggered.connect(self.refresh_remote)
        toolbar.addAction(refresh_action)
        
        toolbar.addSeparator()
        
        upload_action = QAction(self.icons['upload'], "上传", self)
        upload_action.triggered.connect(self.upload_file_dialog)
        toolbar.addAction(upload_action)
        
        download_action = QAction(self.icons['download'], "下载", self)
        download_action.triggered.connect(self.download_file_dialog)
        toolbar.addAction(download_action)
    
    def connect_signals(self):
        """连接信号"""
        # 文件浏览器信号 - 使用QueuedConnection确保线程安全
        self.file_browser.uploadRequested.connect(self.upload_file, Qt.QueuedConnection)
        self.file_browser.downloadRequested.connect(self.download_file, Qt.QueuedConnection)
        self.file_browser.deleteRequested.connect(self.delete_remote, Qt.QueuedConnection)
        self.file_browser.mkdirRequested.connect(self.create_remote_directory_path, Qt.QueuedConnection)
        self.file_browser.refreshRequested.connect(self.refresh_remote, Qt.QueuedConnection)
        
        # 传输管理器信号
        self.transfer_manager.cancelRequested.connect(self.cancel_task, Qt.QueuedConnection)
        self.transfer_manager.clearCompletedRequested.connect(self.clear_completed_tasks, Qt.QueuedConnection)
    
    def show_login_dialog(self):
        """显示登录对话框"""
        dialog = LoginDialog(self)
        if dialog.exec_():
            conn_info = dialog.get_connection_info()
            self.connect_to_server(**conn_info)
    
    def connect_to_server(self, host, port, username, password, enable_ssl=False, passive_mode=True):
        """连接到FTP服务器"""
        try:
            self.status_bar.showMessage(f"正在连接到 {host}:{port}...")
            
            # 断开可能存在的连接
            if self.client and self.connected:
                self.client.disconnect()
                # 给服务器一点时间处理断开连接
                QApplication.processEvents()
            
            # 优化连接参数
            self.client.set_connection_options(
                retry_count=2,   # 减少重试次数
                retry_delay=1,   # 减少重试延迟
                timeout=10,      # 设置较短的超时
                keep_alive=True  # 保持连接
            )
            
            # 连接服务器
            self.client.connect(
                host=host,
                port=port,
                username=username,
                password=password,
                enable_ssl=enable_ssl,
                passive_mode=passive_mode
            )
            
            self.connected = True
            self.status_bar.showMessage(f"已连接到 {host}:{port}")
            
            # 刷新远程文件列表
            self.refresh_remote()
            
        except Exception as e:
            logger.error(f"连接失败: {str(e)}")
            QMessageBox.critical(self, "连接失败", f"无法连接到FTP服务器: {str(e)}")
            self.status_bar.showMessage("连接失败")
    
    def disconnect(self):
        """断开连接"""
        if not self.connected:
            return
            
        try:
            self.client.disconnect()
            self.connected = False
            self.status_bar.showMessage("已断开连接")
            
            # 清空远程文件列表
            self.file_browser.update_remote_tree([])
            
        except Exception as e:
            logger.error(f"断开连接时出错: {str(e)}")
            QMessageBox.warning(self, "错误", f"断开连接时出错: {str(e)}")
    
    def check_connection(self):
        """检查连接状态"""
        if not self.connected:
            QMessageBox.warning(self, "未连接", "请先连接到FTP服务器")
            return False
        return True
    
    def refresh_remote(self):
        """刷新远程文件列表"""
        if not self.check_connection():
            return
            
        current_path = self.file_browser.remote_path_edit.text()
        if not current_path:
            current_path = "/"
            self.file_browser.set_remote_path(current_path)
        
        task_id = self.client.list_directory(
            remote_path=current_path,
            on_complete=self.on_list_completed,
            on_error=self.on_task_error
        )
        
        self.status_bar.showMessage(f"正在刷新目录 {current_path}...")
    
    def on_list_completed(self, task):
        """列表任务完成回调"""
        result = task.result
        if result and result.get('success'):
            listing = result.get('listing', [])
            path = result.get('remote_path', '/')
            
            # 更新文件浏览器
            self.file_browser.update_remote_tree(listing)
            self.file_browser.set_remote_path(path)
            
            self.status_bar.showMessage(f"已加载目录 {path}")
        else:
            QMessageBox.warning(self, "错误", "获取目录列表失败")
    
    def upload_file_dialog(self):
        """显示上传文件对话框"""
        if not self.check_connection():
            return
            
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择要上传的文件"
        )
        
        if files:
            remote_path = self.file_browser.remote_path_edit.text()
            for file_path in files:
                self.upload_file(file_path, os.path.join(remote_path, os.path.basename(file_path)))
    
    def upload_file(self, local_path, remote_path):
        """上传文件"""
        if not self.check_connection():
            return
            
        # 修正路径分隔符
        remote_path = remote_path.replace('\\', '/')
        
        # 创建上传任务
        task_id = self.client.upload(
            local_path=local_path,
            remote_path=remote_path,
            on_progress=self.on_progress,
            on_complete=self.on_upload_completed,
            on_error=self.on_task_error
        )
        
        # 添加任务到传输管理器
        task = self.client.get_task_status(task_id)
        if task:
            self.transfer_manager.add_task(task)
            self.status_bar.showMessage(f"已添加上传任务: {os.path.basename(local_path)}")
            
            # 切换到传输队列选项卡
            self.tab_widget.setCurrentWidget(self.transfer_manager)
        else:
            QMessageBox.warning(self, "错误", "创建上传任务失败")
    
    def download_file_dialog(self):
        """显示下载文件对话框"""
        if not self.check_connection():
            return
            
        # 获取选中的远程文件
        indexes = self.file_browser.remote_tree.selectedIndexes()
        if not indexes:
            QMessageBox.information(self, "提示", "请先选择要下载的文件")
            return
            
        # 获取第一列的索引
        row = indexes[0].row()
        index = self.file_browser.remote_model.index(row, 0)
        name = self.file_browser.remote_model.data(index)
        
        if name == "..":
            return
            
        item = self.file_browser.remote_model.itemFromIndex(index)
        item_type = item.data(Qt.UserRole)
        
        # 获取文件保存路径
        current_path = self.file_browser.remote_path_edit.text()
        remote_path = os.path.join(current_path, name).replace('\\', '/')
        
        if item_type == "directory":
            # 处理目录下载
            self.file_browser.download_directory(remote_path)
            return
        
        # 处理单个文件下载
        local_path, _ = QFileDialog.getSaveFileName(
            self, "保存文件", name
        )
        
        if local_path:
            self.download_file(remote_path, local_path)

    def download_file(self, remote_path, local_path):
        """下载文件或目录"""
        if not self.check_connection():
            return
        
        # 检查是否是目录下载请求
        if remote_path.startswith("DIR:"):
            self.download_directory(remote_path[4:], local_path)
            return
                
        # 创建下载任务
        task_id = self.client.download(
            remote_path=remote_path,
            local_path=local_path,
            on_progress=self.on_progress,
            on_complete=self.on_download_completed,
            on_error=self.on_task_error
        )
        
        # 添加任务到传输管理器
        task = self.client.get_task_status(task_id)
        if task:
            self.transfer_manager.add_task(task)
            self.status_bar.showMessage(f"已添加下载任务: {os.path.basename(remote_path)}")
            
            # 切换到传输队列选项卡
            self.tab_widget.setCurrentWidget(self.transfer_manager)
        else:
            QMessageBox.warning(self, "错误", "创建下载任务失败")

    def download_directory(self, remote_dir, local_dir):
        """下载整个目录"""
        if not self.check_connection():
            return
                
        # 显示进度对话框
        progress_dialog = QProgressDialog("准备下载目录...", "取消", 0, 0, self)
        progress_dialog.setWindowTitle("下载目录")
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.show()
        QApplication.processEvents()
        
        # 开始下载目录
        try:
            task_ids = self.client.download_directory(
                remote_dir=remote_dir,
                local_dir=local_dir,
                on_progress=self.on_progress,
                on_complete=self.on_download_completed,
                on_error=self.on_task_error
            )
            
            # 更新提示信息
            progress_dialog.setLabelText(f"已创建 {len(task_ids)} 个下载任务")
            QApplication.processEvents()
            
            # 等待一会儿然后关闭对话框
            QTimer.singleShot(2000, progress_dialog.close)
            
            # 切换到传输队列选项卡
            self.tab_widget.setCurrentWidget(self.transfer_manager)
            self.status_bar.showMessage(f"已添加 {len(task_ids)} 个文件到下载队列")
        
        except Exception as e:
            progress_dialog.close()
            logger.error(f"下载目录失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"下载目录失败: {str(e)}")
    
    def on_progress(self, task, transferred, total, elapsed):        
        """进度回调"""
        # 更新传输管理器中的任务
        self.transfer_manager.update_task(task)
    
    def on_upload_completed(self, task):
        """上传完成回调"""
        self.transfer_manager.update_task(task)
        self.status_bar.showMessage(f"上传完成: {os.path.basename(task.args[0])}")
        
        # 自动刷新当前目录    
        self.refresh_remote()
        
    def on_download_completed(self, task):
        """下载完成回调"""
        self.transfer_manager.update_task(task)
        self.status_bar.showMessage(f"下载完成: {os.path.basename(task.args[0])}")
    
    def on_task_error(self, task):
        """任务错误回调"""
        self.transfer_manager.update_task(task)
        error_msg = str(task.error) if task.error else "未知错误"
        self.status_bar.showMessage(f"任务失败: {error_msg}")
        logger.error(f"任务 {task.id} 失败: {error_msg}")
    
    def create_remote_directory(self):
        """创建远程目录"""
        if not self.check_connection():
            return
        
        dir_name, ok = QInputDialog.getText(
            self, "创建目录", "请输入新目录名称:"
        )
        
        if ok and dir_name:    
            current_path = self.file_browser.remote_path_edit.text()
            new_path = os.path.join(current_path, dir_name).replace('\\', '/')
            self.create_remote_directory_path(new_path)
    
    def create_remote_directory_path(self, path):
        """创建指定路径的远程目录"""
        if not self.check_connection():
            return
        
        task_id = self.client.mkdir(
            path,
            on_complete=self.on_mkdir_completed,
            on_error=self.on_task_error
        )
    
    def on_mkdir_completed(self, task):
        """创建目录完成回调"""
        result = task.result
        if result and result.get('success'):
            path = result.get('remote_path', '')
            self.status_bar.showMessage(f"已创建目录: {path}")
            
            # 刷新当前目录
            self.refresh_remote()
        else:
            QMessageBox.warning(self, "错误", "创建目录失败")
    
    def delete_remote(self, path, is_dir):
        """删除远程文件或目录"""
        if not self.check_connection():
            return
        
        if is_dir:
            task_id = self.client.rmdir(
                path,
                on_complete=self.on_delete_completed,
                on_error=self.on_task_error
            )
        else:
            task_id = self.client.delete(
                path,
                on_complete=self.on_delete_completed,
                on_error=self.on_task_error
            )
    
    def on_delete_completed(self, task):
        """删除完成回调"""
        result = task.result
        if result and result.get('success'):
            path = result.get('remote_path', '')
            self.status_bar.showMessage(f"已删除: {path}")
            
            # 刷新当前目录
            self.refresh_remote()
        else:
            QMessageBox.warning(self, "错误", "删除失败")
    
    def cancel_task(self, task_id):
        """取消任务"""
        if self.client.cancel_task(task_id):
            self.status_bar.showMessage(f"已取消任务: {task_id}")
            
            # 更新任务状态
            task = self.client.get_task_status(task_id)
            if task:
                self.transfer_manager.update_task(task)
    
    def clear_completed_tasks(self):
        """清除已完成的任务"""
        self.transfer_manager.clear_completed_tasks()
        self.status_bar.showMessage("已清除已完成的任务")
    
    def refresh_task_status(self):
        """刷新任务状态"""
        if not self.connected:
            return
            
        try:
            # 获取所有任务
            tasks = self.client.get_all_tasks()
            
            # 更新传输管理器状态标签
            active_count = len(tasks['active'])
            pending_count = tasks['queue_size']
            completed_count = len(tasks['completed'])
            self.transfer_manager.update_status_label(active_count, pending_count, completed_count)
            
            # 更新活动任务，但减少频率避免界面卡顿
            for task_id, task_data in list(tasks['active'].items())[:3]:  # 每次最多更新3个任务
                task = self.client.get_task_status(task_id)
                if task:
                    # 使用QMetaObject.invokeMethod确保UI更新在主线程进行
                    self.transfer_manager.update_task(task)
        except Exception as e:
            logger.debug(f"刷新任务状态时出错: {str(e)}")  # 降低日志级别，避免日志过多
    
    def show_about(self):
        """显示关于对话框"""
        QMessageBox.about(
            self,
            "关于NewFTP客户端",
            "NewFTP客户端 v1.0\n\n一个基于PyQt5的FTP客户端应用。"
        )
    
    def show_settings(self):
        """显示设置对话框"""
        from client.gui.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self)
        if dialog.exec_():
            # 可以在这里应用某些设置，例如更新最大并发任务数
            QMessageBox.information(self, "设置", "设置已保存，部分设置在重启后生效")

    def show_bookmarks(self):
        """显示书签管理对话框"""
        from client.gui.bookmarks import BookmarkManagerDialog
        dialog = BookmarkManagerDialog(self)
        dialog.bookmarkSelected.connect(self.connect_to_bookmark)
        dialog.exec_()

    def connect_to_bookmark(self, bookmark):
        """连接到书签"""
        try:
            self.connect_to_server(
                host=bookmark.host,
                port=bookmark.port,
                username=bookmark.username,
                password=bookmark.password,
                enable_ssl=bookmark.enable_ssl,
                passive_mode=bookmark.passive_mode
            )
        except Exception as e:
            logger.error(f"连接到书签失败: {str(e)}")
            QMessageBox.critical(self, "连接失败", f"无法连接到书签服务器: {str(e)}")

    def closeEvent(self, event):
        """关闭事件处理"""
        if self.connected:
            reply = QMessageBox.question(
                self, "确认退出", 
                "你当前已连接到FTP服务器，确定要断开连接并退出吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                try:
                    self.client.disconnect()
                except Exception:
                    pass
                # 给Qt足够时间清理所有线程
                QTimer.singleShot(500, self.perform_exit)
                event.ignore()  # 我们将在定时器回调中退出
            else:
                event.ignore()
        else:
            event.accept()
            
    def perform_exit(self):
        """执行退出操作"""
        # 确保线程已清理
        if hasattr(self.client, 'cleanup'):
            self.client.cleanup()
        QApplication.quit()