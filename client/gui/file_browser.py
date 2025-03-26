"""FTP客户端文件浏览器组件"""

import os
import threading
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTreeView, QHeaderView,
                           QLabel, QLineEdit, QPushButton, QToolBar, QAction,
                           QFileDialog, QMenu, QInputDialog, QMessageBox, QSplitter, QStyle)
from PyQt5.QtCore import (Qt, QModelIndex, QDir, pyqtSignal, QItemSelectionModel, 
                         QEvent, QThread, QObject, QTimer)
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QIcon
import logging

logger = logging.getLogger(__name__)

class DragDropHelper(QObject):
    """辅助处理拖放操作，避免线程问题"""
    
    uploadDirectoryRequested = pyqtSignal(str, str)
    uploadFileRequested = pyqtSignal(str, str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.RLock()
    
    def handleDrop(self, urls, remote_path):
        """处理拖放事件，分发到主线程"""
        for url in urls:
            local_path = url.toLocalFile()
            if os.path.isfile(local_path):
                file_name = os.path.basename(local_path)
                remote_file = os.path.join(remote_path, file_name).replace('\\', '/')
                # 使用信号发送到主线程
                self.uploadFileRequested.emit(local_path, remote_file)
            elif os.path.isdir(local_path):
                # 处理目录上传
                dir_name = os.path.basename(local_path)
                remote_dir = os.path.join(remote_path, dir_name).replace('\\', '/')
                self.uploadDirectoryRequested.emit(local_path, remote_dir)

class FileBrowser(QWidget):
    """
    文件浏览器组件，显示本地和远程文件系统
    """
    
    # 信号定义
    uploadRequested = pyqtSignal(str, str)  # 本地路径, 远程路径
    downloadRequested = pyqtSignal(str, str)  # 远程路径, 本地路径
    deleteRequested = pyqtSignal(str, bool)  # 路径, 是否是目录
    mkdirRequested = pyqtSignal(str)  # 远程目录路径
    refreshRequested = pyqtSignal()  # 刷新请求
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 创建拖放助手
        self.drag_drop_helper = DragDropHelper(self)
        self.drag_drop_helper.uploadFileRequested.connect(
            self.uploadRequested.emit, Qt.QueuedConnection)
        self.drag_drop_helper.uploadDirectoryRequested.connect(
            self.on_upload_directory_requested, Qt.QueuedConnection)
        
        # 初始化界面
        self.setup_ui()
        
        # 设置模型
        self.setup_models()
        
        # 连接信号槽
        self.connect_signals()
        
        # 启用拖放
        self.setup_drag_drop()
    
    def setup_ui(self):
        """设置界面"""
        # 主布局
        main_layout = QVBoxLayout(self)
        
        # 创建拆分器
        splitter = QSplitter(Qt.Horizontal)
        
        # 本地文件部分
        local_widget = QWidget()
        local_layout = QVBoxLayout(local_widget)
        
        local_header = QHBoxLayout()
        local_header.addWidget(QLabel("本地文件系统"))
        local_layout.addLayout(local_header)
        
        # 本地地址栏
        local_path_layout = QHBoxLayout()
        self.local_path_edit = QLineEdit()
        self.local_path_edit.setReadOnly(True)
        self.local_browse_button = QPushButton("...")
        local_path_layout.addWidget(self.local_path_edit)
        local_path_layout.addWidget(self.local_browse_button)
        local_layout.addLayout(local_path_layout)
        
        # 本地文件树
        self.local_tree = QTreeView()
        self.local_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        local_layout.addWidget(self.local_tree)
        
        # 远程文件部分
        remote_widget = QWidget()
        remote_layout = QVBoxLayout(remote_widget)
        
        remote_header = QHBoxLayout()
        remote_header.addWidget(QLabel("远程文件系统"))
        self.remote_path_label = QLabel("/")
        remote_header.addWidget(self.remote_path_label)
        remote_layout.addLayout(remote_header)
        
        # 远程地址栏
        remote_path_layout = QHBoxLayout()
        self.remote_path_edit = QLineEdit()
        self.remote_refresh_button = QPushButton("刷新")
        remote_path_layout.addWidget(self.remote_path_edit)
        remote_path_layout.addWidget(self.remote_refresh_button)
        remote_layout.addLayout(remote_path_layout)
        
        # 远程文件树
        self.remote_tree = QTreeView()
        self.remote_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        remote_layout.addWidget(self.remote_tree)
        
        # 添加到拆分器
        splitter.addWidget(local_widget)
        splitter.addWidget(remote_widget)
        splitter.setSizes([int(self.width() * 0.5), int(self.width() * 0.5)])
        
        main_layout.addWidget(splitter)
        
        # 创建工具栏
        toolbar = QToolBar()
        
        self.action_upload = QAction("上传", self)
        self.action_download = QAction("下载", self)
        self.action_refresh = QAction("刷新", self)
        self.action_new_folder = QAction("新建文件夹", self)
        self.action_delete = QAction("删除", self)
        
        toolbar.addAction(self.action_upload)
        toolbar.addAction(self.action_download)
        toolbar.addAction(self.action_refresh)
        toolbar.addAction(self.action_new_folder)
        toolbar.addAction(self.action_delete)
        
        main_layout.addWidget(toolbar)
    
    def setup_drag_drop(self):
        """设置拖放支持"""
        # 本地文件树支持拖出
        self.local_tree.setDragEnabled(True)
        
        # 远程文件树支持拖入
        self.remote_tree.setAcceptDrops(True)
        self.remote_tree.setDropIndicatorShown(True)
        self.remote_tree.setDragDropMode(QTreeView.DropOnly)
        
        # 安装事件过滤器来处理拖放
        self.remote_tree.installEventFilter(self)

    def eventFilter(self, obj, event):
        """事件过滤器，用于处理拖放事件"""
        if obj == self.remote_tree:
            # 处理拖放
            if event.type() == QEvent.DragEnter:
                # 拖入开始
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True
                    
            elif event.type() == QEvent.Drop:
                # 拖放释放
                if event.mimeData().hasUrls():
                    # 获取所有被拖放的文件URL
                    urls = event.mimeData().urls()
                    remote_path = self.remote_path_edit.text()
                    
                    # 使用拖放助手处理，避免线程问题
                    self.drag_drop_helper.handleDrop(urls, remote_path)
                    
                    event.acceptProposedAction()
                    return True
        
        return super().eventFilter(obj, event)
    
    def on_upload_directory_requested(self, local_dir, remote_dir):
        """处理目录上传请求"""
        # 先创建远程目录
        self.mkdirRequested.emit(remote_dir)
        
        # 用计时器确保目录创建后再上传文件
        QTimer.singleShot(500, lambda: self.upload_directory_contents(local_dir, remote_dir))
    
    def upload_directory_contents(self, local_dir, remote_dir):
        """上传目录中的内容"""
        try:
            # 上传目录中的所有文件
            for item in os.listdir(local_dir):
                local_path = os.path.join(local_dir, item)
                if os.path.isfile(local_path):
                    # 上传文件
                    remote_path = os.path.join(remote_dir, item).replace('\\', '/')
                    self.uploadRequested.emit(local_path, remote_path)
                elif os.path.isdir(local_path):
                    # 递归处理子目录
                    sub_dir_name = os.path.basename(local_path)
                    sub_remote_dir = os.path.join(remote_dir, sub_dir_name).replace('\\', '/')
                    self.on_upload_directory_requested(local_path, sub_remote_dir)
        except Exception as e:
            logger.error(f"上传目录内容失败: {str(e)}")
            QMessageBox.warning(self, "上传错误", f"上传目录内容失败:\n{str(e)}")
    
    def setup_models(self):
        """设置模型"""
        # 本地文件模型
        from PyQt5.QtWidgets import QFileSystemModel
        self.local_model = QFileSystemModel()
        self.local_model.setRootPath(QDir.rootPath())
        self.local_tree.setModel(self.local_model)
        self.local_tree.setRootIndex(self.local_model.index(QDir.homePath()))
        # 设置只显示文件名列
        self.local_tree.setColumnWidth(0, 250)
        for i in range(1, 4):  # 隐藏大小、类型、日期列
            self.local_tree.hideColumn(i)
        
        # 远程文件模型
        self.remote_model = QStandardItemModel()
        self.remote_model.setHorizontalHeaderLabels(["名称", "大小", "修改日期", "权限"])
        self.remote_tree.setModel(self.remote_model)
        # 设置列宽
        self.remote_tree.setColumnWidth(0, 200)
        self.remote_tree.setColumnWidth(1, 100)
        self.remote_tree.setColumnWidth(2, 150)
        
        # 更新本地路径显示
        self.local_path_edit.setText(QDir.homePath())
            
        # 加载文件图标
        self.load_icons()
    
    def load_icons(self):
        """加载图标"""
        style = self.style()
        self.icons = {
            'folder': style.standardIcon(QStyle.SP_DirIcon),
            'file': style.standardIcon(QStyle.SP_FileIcon),
            'parent': style.standardIcon(QStyle.SP_FileDialogToParent)
        }
    
    def connect_signals(self):
        """连接信号槽"""
        # 本地文件系统事件
        self.local_browse_button.clicked.connect(self.browse_local_directory)
        self.local_tree.doubleClicked.connect(self.on_local_item_double_clicked)
        self.local_tree.customContextMenuRequested.connect(self.show_local_context_menu)
        self.local_tree.clicked.connect(self.on_local_item_clicked)
        
        # 远程文件系统事件
        self.remote_refresh_button.clicked.connect(self.refresh_remote)
        self.remote_tree.doubleClicked.connect(self.on_remote_item_double_clicked)
        self.remote_tree.customContextMenuRequested.connect(self.show_remote_context_menu)
        
        # 工具栏动作
        self.action_upload.triggered.connect(self.upload_selected)
        self.action_download.triggered.connect(self.download_selected)
        self.action_refresh.triggered.connect(self.refresh_remote)
        self.action_new_folder.triggered.connect(self.create_remote_directory)
        self.action_delete.triggered.connect(self.delete_remote_selected)
    
    def browse_local_directory(self):
        """浏览本地目录"""
        directory = QFileDialog.getExistingDirectory(
            self, "选择目录", self.local_path_edit.text()
        )
        
        if directory:
            self.local_tree.setRootIndex(self.local_model.index(directory))
            self.local_path_edit.setText(directory)
    
    def on_local_item_clicked(self, index):
        """处理本地项点击事件"""
        file_path = self.local_model.filePath(index)
        self.local_path_edit.setText(file_path)
    
    def on_local_item_double_clicked(self, index):
        """处理本地项双击事件"""
        file_path = self.local_model.filePath(index)
        
        if os.path.isdir(file_path):
            self.local_tree.setRootIndex(index)
            self.local_path_edit.setText(file_path)
    
    def show_local_context_menu(self, position):
        """显示本地文件系统上下文菜单"""
        index = self.local_tree.indexAt(position)
        
        if not index.isValid():
            return
        file_path = self.local_model.filePath(index)
        is_dir = os.path.isdir(file_path)
        
        menu = QMenu(self)
        
        upload_action = menu.addAction("上传")
        if is_dir:
            upload_action = menu.addAction("上传目录内容")
        browse_action = menu.addAction("浏览")
        
        action = menu.exec_(self.local_tree.viewport().mapToGlobal(position))
        
        if action == upload_action:
            self.upload_file(file_path)
        elif action == browse_action and is_dir:
            self.local_tree.setRootIndex(index)
            self.local_path_edit.setText(file_path)
    
    def set_remote_path(self, path):
        """设置远程路径"""
        self.remote_path_edit.setText(path)
        self.remote_path_label.setText(path)
    
    def update_remote_tree(self, items):
        """
        更新远程文件树
        
        Args:
            items (list): 文件项列表
        """
        self.remote_model.clear()
        self.remote_model.setHorizontalHeaderLabels(["名称", "大小", "修改日期", "权限"])
        
        # 添加父目录项
        parent_item = QStandardItem(self.icons['parent'], "..")
        parent_item.setData("directory", Qt.UserRole)
        self.remote_model.appendRow([parent_item])
        
        for item in items:
            name = item.get('name', '')
            if name in ['.', '..']:
                continue
                
            item_type = item.get('type', 'file')
            size = item.get('size', 0)
            date = item.get('date', '')
            perms = item.get('permissions', '')
            
            # 根据类型设置图标
            if item_type == 'dir':
                icon = self.icons['folder']
            else:
                icon = self.icons['file']
                
            name_item = QStandardItem(icon, name)
            name_item.setData(item_type, Qt.UserRole)
            size_item = QStandardItem(self.format_size(size) if item_type != 'dir' else '<目录>')
            date_item = QStandardItem(date)
            perms_item = QStandardItem(perms)
            
            self.remote_model.appendRow([name_item, size_item, date_item, perms_item])
    
    def format_size(self, size):
        """格式化文件大小"""
        from common.utils import format_size
        return format_size(size)
    
    def on_remote_item_double_clicked(self, index):
        """处理远程项双击事件"""
        if not index.isValid():
            return
        
        item = self.remote_model.itemFromIndex(index)
        name = item.text()
        item_type = item.data(Qt.UserRole)
        
        if item_type == "directory" or name == "..":
            current_path = self.remote_path_edit.text()
            
            if name == "..":
                # 导航到父目录
                parent_path = os.path.dirname(current_path.rstrip('/'))
                if not parent_path:
                    parent_path = "/"
                self.set_remote_path(parent_path)
            else:
                # 导航到子目录
                new_path = os.path.join(current_path, name).replace('\\', '/')
                self.set_remote_path(new_path)
                
            self.refreshRequested.emit()
    
    def show_remote_context_menu(self, position):
        """显示远程文件系统上下文菜单"""
        index = self.remote_tree.indexAt(position)
        
        if not index.isValid():
            return   
            
        item = self.remote_model.itemFromIndex(index)
        name = item.text()
        if name == "..":
            return
            
        item_type = item.data(Qt.UserRole)
        current_path = self.remote_path_edit.text()
        remote_path = os.path.join(current_path, name).replace('\\', '/')
        
        menu = QMenu(self)
        
        if item_type == "directory":
            download_dir_action = menu.addAction("下载目录")
            enter_dir_action = menu.addAction("进入目录")
            menu.addSeparator()
        else:
            download_action = menu.addAction("下载")
        
        delete_action = menu.addAction("删除")
        
        action = menu.exec_(self.remote_tree.viewport().mapToGlobal(position))
        
        if item_type == "directory":
            if action == download_dir_action:
                self.download_directory(remote_path)
            elif action == enter_dir_action:
                self.set_remote_path(remote_path)
                self.refreshRequested.emit()
        elif action == download_action:
            self.download_file(remote_path)
        
        if action == delete_action:
            self.delete_remote(remote_path, item_type == "directory")
    
    def upload_file(self, local_path):
        """上传文件"""
        if not local_path:
            return
            
        # 检查文件是否存在
        if not os.path.exists(local_path):
            QMessageBox.critical(
                self, 
                "文件错误", 
                f"文件不存在:\n{local_path}"
            )
            return
                
        remote_path = self.remote_path_edit.text()
        
        if os.path.isdir(local_path):
            # 对于目录，上传其中的内容
            for item in os.listdir(local_path):
                item_path = os.path.join(local_path, item)
                if os.path.isfile(item_path):
                    # 检查文件是否可读
                    try:
                        with open(item_path, 'rb') as f:
                            pass  # 测试文件是否可打开
                        remote_file = os.path.join(remote_path, item).replace('\\', '/')
                        self.uploadRequested.emit(item_path, remote_file)
                    except IOError:
                        QMessageBox.warning(
                            self, 
                            "文件错误", 
                            f"无法打开文件:\n{item_path}"
                        )
        else:
            # 对于单个文件直接上传
            try:
                # 检查文件是否可读
                with open(local_path, 'rb') as f:
                    pass  # 测试文件是否可打开
                    
                file_name = os.path.basename(local_path)
                remote_file = os.path.join(remote_path, file_name).replace('\\', '/')
                self.uploadRequested.emit(local_path, remote_file)
            except IOError:
                QMessageBox.critical(
                    self, 
                    "文件错误", 
                    f"无法打开文件:\n{local_path}"
                )
    
    def upload_selected(self):
        """上传选中的文件"""
        indexes = self.local_tree.selectedIndexes()
        if not indexes:
            QMessageBox.information(self, "提示", "请先选择要上传的文件或目录")
            return
            
        file_path = self.local_model.filePath(indexes[0])
        self.upload_file(file_path)
    
    def download_file(self, remote_path):
        """下载文件"""
        if not remote_path:
            return
            
        file_name = os.path.basename(remote_path)
        local_dir = self.local_path_edit.text()
        local_path = os.path.join(local_dir, file_name)
        
        self.downloadRequested.emit(remote_path, local_path)
    
    def download_directory(self, remote_dir):
        """下载目录"""
        # 选择本地保存目录
        local_dir = QFileDialog.getExistingDirectory(
            self, "选择保存目录", self.local_path_edit.text()
        )
        
        if not local_dir:
            return
            
        # 在本地目录下创建与远程目录同名的目录
        dir_name = os.path.basename(remote_dir)
        if dir_name:
            local_save_dir = os.path.join(local_dir, dir_name)
        else:
            # 如果是根目录，则使用远程主机名作为目录名
            local_save_dir = os.path.join(local_dir, "ftp-download")
        
        # 创建目录
        os.makedirs(local_save_dir, exist_ok=True)
        
        # 发出递归下载信号，使用特殊格式表示这是目录下载
        self.downloadRequested.emit(f"DIR:{remote_dir}", local_save_dir)
    
    def download_selected(self):
        """下载选中的文件"""
        indexes = self.remote_tree.selectedIndexes()
        if not indexes:
            QMessageBox.information(self, "提示", "请先选择要下载的文件")
            return
        
        # 获取第一列的索引
        row = indexes[0].row()
        index = self.remote_model.index(row, 0)
        name = self.remote_model.data(index)
        
        if name == "..":
            return
            
        item = self.remote_model.itemFromIndex(index)
        item_type = item.data(Qt.UserRole)
        current_path = self.remote_path_edit.text()
        remote_path = os.path.join(current_path, name).replace('\\', '/')
        
        if item_type == "directory":
            self.download_directory(remote_path)
        else:
            self.download_file(remote_path)
    
    def refresh_remote(self):
        """刷新远程目录"""
        self.refreshRequested.emit()
    
    def create_remote_directory(self):
        """创建远程目录"""
        dir_name, ok = QInputDialog.getText(
            self, "创建目录", "请输入新目录名称:"
        )
        
        if ok and dir_name:
            current_path = self.remote_path_edit.text()
            new_path = os.path.join(current_path, dir_name).replace('\\', '/')
            self.mkdirRequested.emit(new_path)
    
    def delete_remote(self, path, is_dir):
        """删除远程文件或目录"""
        message = f"确定要删除{'目录' if is_dir else '文件'} '{os.path.basename(path)}' 吗？"
        
        if is_dir:
            message += "\n注意: 这将删除目录及其所有内容！"
            
        reply = QMessageBox.question(
            self, "确认删除", message, 
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.deleteRequested.emit(path, is_dir)
    
    def delete_remote_selected(self):
        """删除选中的远程文件或目录"""
        indexes = self.remote_tree.selectedIndexes()
        if not indexes:
            QMessageBox.information(self, "提示", "请先选择要删除的文件或目录")
            return
        
        # 获取第一列的索引
        row = indexes[0].row()
        index = self.remote_model.index(row, 0)
        name = self.remote_model.data(index)
        
        if name == "..":
            return
            
        item = self.remote_model.itemFromIndex(index)
        item_type = item.data(Qt.UserRole)
        current_path = self.remote_path_edit.text()
        remote_path = os.path.join(current_path, name).replace('\\', '/')
        
        self.delete_remote(remote_path, item_type == "directory")
