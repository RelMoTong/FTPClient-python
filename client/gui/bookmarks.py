"""FTP客户端书签管理"""

import json
import os
from PyQt5.QtWidgets import (QDialog, QListWidget, QListWidgetItem, QPushButton,
                           QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, 
                           QLineEdit, QSpinBox, QCheckBox, QGroupBox, 
                           QMessageBox, QDialogButtonBox)
from PyQt5.QtCore import QSettings, Qt, pyqtSignal
import logging

logger = logging.getLogger(__name__)

class Bookmark:
    """书签类，包含FTP连接信息"""
    
    def __init__(self, name, host, port=21, username="anonymous", password="", 
                enable_ssl=False, passive_mode=True):
        self.name = name
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.enable_ssl = enable_ssl
        self.passive_mode = passive_mode
    
    def to_dict(self):
        """转换为字典"""
        return {
            'name': self.name,
            'host': self.host,
            'port': self.port,
            'username': self.username,
            'password': self.password,
            'enable_ssl': self.enable_ssl,
            'passive_mode': self.passive_mode
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建书签"""
        return cls(
            name=data.get('name', ''),
            host=data.get('host', ''),
            port=data.get('port', 21),
            username=data.get('username', 'anonymous'),
            password=data.get('password', ''),
            enable_ssl=data.get('enable_ssl', False),
            passive_mode=data.get('passive_mode', True)
        )

class BookmarkManager:
    """书签管理器，负责保存和加载书签"""
    
    def __init__(self):
        self.bookmarks = []
        self.load_bookmarks()
    
    def load_bookmarks(self):
        """加载书签"""
        settings = QSettings("NewFTP", "FTPClient")
        bookmarks_data = settings.value("bookmarks", [])
        
        if isinstance(bookmarks_data, str):
            try:
                bookmarks_data = json.loads(bookmarks_data)
            except:
                bookmarks_data = []
        
        self.bookmarks = []
        for data in bookmarks_data:
            try:
                bookmark = Bookmark.from_dict(data)
                self.bookmarks.append(bookmark)
            except Exception as e:
                logger.error(f"加载书签失败: {str(e)}")
    
    def save_bookmarks(self):
        """保存书签"""
        settings = QSettings("NewFTP", "FTPClient")
        bookmarks_data = [bookmark.to_dict() for bookmark in self.bookmarks]
        settings.setValue("bookmarks", json.dumps(bookmarks_data))
    
    def add_bookmark(self, bookmark):
        """添加书签"""
        self.bookmarks.append(bookmark)
        self.save_bookmarks()
    
    def update_bookmark(self, index, bookmark):
        """更新书签"""
        if 0 <= index < len(self.bookmarks):
            self.bookmarks[index] = bookmark
            self.save_bookmarks()
    
    def delete_bookmark(self, index):
        """删除书签"""
        if 0 <= index < len(self.bookmarks):
            del self.bookmarks[index]
            self.save_bookmarks()
    
    def get_bookmark(self, index):
        """获取书签"""
        if 0 <= index < len(self.bookmarks):
            return self.bookmarks[index]
        return None

class BookmarkDialog(QDialog):
    """书签编辑对话框"""
    
    def __init__(self, bookmark=None, parent=None):
        super().__init__(parent)
        
        self.bookmark = bookmark
        self.setWindowTitle("编辑书签" if bookmark else "新建书签")
        self.resize(400, 300)
        
        # 创建界面
        self.setup_ui()
        
        # 如果是编辑，填充数据
        if bookmark:
            self.fill_data(bookmark)
    
    def setup_ui(self):
        """设置界面"""
        # 主布局
        main_layout = QVBoxLayout(self)
        
        # 表单布局
        form_layout = QFormLayout()
        
        # 名称
        self.name_edit = QLineEdit()
        form_layout.addRow("名称:", self.name_edit)
        
        # 主机和端口
        self.host_edit = QLineEdit()
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(21)
        
        form_layout.addRow("主机:", self.host_edit)
        form_layout.addRow("端口:", self.port_spin)
        
        # 用户名和密码
        self.username_edit = QLineEdit()
        self.username_edit.setText("anonymous")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        
        form_layout.addRow("用户名:", self.username_edit)
        form_layout.addRow("密码:", self.password_edit)
        
        # 选项
        self.ssl_check = QCheckBox("使用SSL/TLS")
        self.passive_check = QCheckBox("被动模式")
        self.passive_check.setChecked(True)
        
        form_layout.addRow("", self.ssl_check)
        form_layout.addRow("", self.passive_check)
        
        # 按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        # 添加到主布局
        main_layout.addLayout(form_layout)
        main_layout.addWidget(button_box)
    
    def fill_data(self, bookmark):
        """填充书签数据"""
        self.name_edit.setText(bookmark.name)
        self.host_edit.setText(bookmark.host)
        self.port_spin.setValue(bookmark.port)
        self.username_edit.setText(bookmark.username)
        self.password_edit.setText(bookmark.password)
        self.ssl_check.setChecked(bookmark.enable_ssl)
        self.passive_check.setChecked(bookmark.passive_mode)
    
    def get_bookmark(self):
        """获取编辑后的书签"""
        return Bookmark(
            name=self.name_edit.text(),
            host=self.host_edit.text(),
            port=self.port_spin.value(),
            username=self.username_edit.text(),
            password=self.password_edit.text(),
            enable_ssl=self.ssl_check.isChecked(),
            passive_mode=self.passive_check.isChecked()
        )
    
    def accept(self):
        """确定按钮处理"""
        # 验证输入
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "输入错误", "书签名称不能为空")
            return
            
        if not self.host_edit.text().strip():
            QMessageBox.warning(self, "输入错误", "主机地址不能为空")
            return
        
        super().accept()

class BookmarkManagerDialog(QDialog):
    """书签管理对话框"""
    
    bookmarkSelected = pyqtSignal(Bookmark)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setWindowTitle("书签管理")
        self.resize(600, 400)
        
        # 书签管理器
        self.manager = BookmarkManager()
        
        # 创建界面
        self.setup_ui()
        
        # 加载书签列表
        self.load_bookmarks()
    
    def setup_ui(self):
        """设置界面"""
        # 主布局
        main_layout = QHBoxLayout(self)
        
        # 左侧列表
        self.bookmark_list = QListWidget()
        self.bookmark_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        
        # 右侧按钮
        button_layout = QVBoxLayout()
        self.connect_button = QPushButton("连接")
        self.add_button = QPushButton("添加")
        self.edit_button = QPushButton("编辑")
        self.delete_button = QPushButton("删除")
        self.close_button = QPushButton("关闭")
        
        button_layout.addWidget(self.connect_button)
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addStretch()
        button_layout.addWidget(self.close_button)
        
        # 添加到主布局
        main_layout.addWidget(self.bookmark_list, 3)
        main_layout.addLayout(button_layout, 1)
        
        # 连接信号
        self.connect_button.clicked.connect(self.on_connect)
        self.add_button.clicked.connect(self.on_add)
        self.edit_button.clicked.connect(self.on_edit)
        self.delete_button.clicked.connect(self.on_delete)
        self.close_button.clicked.connect(self.reject)
    
    def load_bookmarks(self):
        """加载书签到列表"""
        self.bookmark_list.clear()
        
        for bookmark in self.manager.bookmarks:
            item = QListWidgetItem(bookmark.name)
            item.setToolTip(f"{bookmark.username}@{bookmark.host}:{bookmark.port}")
            self.bookmark_list.addItem(item)
    
    def on_connect(self):
        """连接到选中的书签"""
        current_row = self.bookmark_list.currentRow()
        if current_row < 0:
            QMessageBox.information(self, "提示", "请先选择一个书签")
            return
            
        bookmark = self.manager.get_bookmark(current_row)
        if bookmark:
            self.bookmarkSelected.emit(bookmark)
            self.accept()
    
    def on_add(self):
        """添加新书签"""
        dialog = BookmarkDialog(parent=self)
        if dialog.exec_():
            bookmark = dialog.get_bookmark()
            self.manager.add_bookmark(bookmark)
            self.load_bookmarks()
    
    def on_edit(self):
        """编辑选中的书签"""
        current_row = self.bookmark_list.currentRow()
        if current_row < 0:
            QMessageBox.information(self, "提示", "请先选择一个书签")
            return
            
        bookmark = self.manager.get_bookmark(current_row)
        if bookmark:
            dialog = BookmarkDialog(bookmark, parent=self)
            if dialog.exec_():
                updated_bookmark = dialog.get_bookmark()
                self.manager.update_bookmark(current_row, updated_bookmark)
                self.load_bookmarks()
    
    def on_delete(self):
        """删除选中的书签"""
        current_row = self.bookmark_list.currentRow()
        if current_row < 0:
            QMessageBox.information(self, "提示", "请先选择一个书签")
            return
            
        reply = QMessageBox.question(
            self, "确认删除", 
            f"确定要删除书签 {self.bookmark_list.currentItem().text()} 吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.manager.delete_bookmark(current_row)
            self.load_bookmarks()
    
    def on_item_double_clicked(self, item):
        """双击列表项"""
        self.on_connect()
