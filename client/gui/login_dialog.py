"""FTP客户端登录对话框"""

from PyQt5.QtWidgets import (QDialog, QLabel, QLineEdit, QPushButton, QCheckBox, 
                           QFormLayout, QVBoxLayout, QHBoxLayout, QSpinBox,
                           QDialogButtonBox, QMessageBox)
from PyQt5.QtCore import Qt, QSettings
import logging

logger = logging.getLogger(__name__)

class LoginDialog(QDialog):
    """FTP登录对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("连接到FTP服务器")
        self.resize(400, 250)
        
        # 创建控件
        self.setup_ui()
        
        # 加载保存的设置
        self.load_settings()
    
    def setup_ui(self):
        """设置界面"""
        # 创建表单布局
        form_layout = QFormLayout()
        
        # 主机和端口
        self.host_edit = QLineEdit()
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(21)
        
        port_layout = QHBoxLayout()
        port_layout.addWidget(self.port_spin)
        port_layout.addStretch(1)
        
        form_layout.addRow("主机:", self.host_edit)
        form_layout.addRow("端口:", port_layout)
        
        # 用户名和密码
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        
        form_layout.addRow("用户名:", self.username_edit)
        form_layout.addRow("密码:", self.password_edit)
        
        # 连接选项
        self.ssl_check = QCheckBox("使用SSL/TLS")
        self.passive_check = QCheckBox("被动模式")
        self.passive_check.setChecked(True)
        self.anonymous_check = QCheckBox("匿名登录")
        
        form_layout.addRow("", self.ssl_check)
        form_layout.addRow("", self.passive_check)
        form_layout.addRow("", self.anonymous_check)
        
        # 记住设置
        self.save_settings_check = QCheckBox("记住这些设置")
        self.save_settings_check.setChecked(True)
        form_layout.addRow("", self.save_settings_check)
        
        # 按钮
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        
        # 主布局
        main_layout = QVBoxLayout()
        main_layout.addLayout(form_layout)
        main_layout.addWidget(self.button_box)
        
        self.setLayout(main_layout)
        
        # 连接信号
        self.anonymous_check.toggled.connect(self.on_anonymous_toggled)
    
    def on_anonymous_toggled(self, checked):
        """处理匿名登录复选框状态变化"""
        if checked:
            self.username_edit.setText("anonymous")
            self.password_edit.setText("")
            self.username_edit.setEnabled(False)
            self.password_edit.setEnabled(False)
        else:
            if self.username_edit.text() == "anonymous":
                self.username_edit.setText("")
            self.username_edit.setEnabled(True)
            self.password_edit.setEnabled(True)
    
    def load_settings(self):
        """加载保存的设置"""
        settings = QSettings("NewFTP", "FTPClient")
        self.host_edit.setText(settings.value("connection/host", ""))
        self.port_spin.setValue(int(settings.value("connection/port", 21)))
        self.username_edit.setText(settings.value("connection/username", ""))
        self.password_edit.setText(settings.value("connection/password", ""))
        self.ssl_check.setChecked(settings.value("connection/ssl", False, type=bool))
        self.passive_check.setChecked(settings.value("connection/passive", True, type=bool))
        
        # 如果用户名是anonymous，勾选匿名登录
        if self.username_edit.text() == "anonymous":
            self.anonymous_check.setChecked(True)
    
    def save_settings(self):
        """保存设置"""
        if not self.save_settings_check.isChecked():
            return
            
        settings = QSettings("NewFTP", "FTPClient")
        settings.setValue("connection/host", self.host_edit.text())
        settings.setValue("connection/port", self.port_spin.value())
        settings.setValue("connection/username", self.username_edit.text())
        settings.setValue("connection/password", self.password_edit.text())
        settings.setValue("connection/ssl", self.ssl_check.isChecked())
        settings.setValue("connection/passive", self.passive_check.isChecked())
    
    def get_connection_info(self):
        """获取连接信息"""
        return {
            "host": self.host_edit.text(),
            "port": self.port_spin.value(),
            "username": self.username_edit.text(),
            "password": self.password_edit.text(),
            "enable_ssl": self.ssl_check.isChecked(),
            "passive_mode": self.passive_check.isChecked()
        }
    
    def accept(self):
        """确认按钮处理"""
        # 验证输入
        if not self.host_edit.text().strip():
            QMessageBox.warning(self, "输入错误", "请输入FTP服务器地址")
            return
            
        if not self.anonymous_check.isChecked() and not self.username_edit.text().strip():
            QMessageBox.warning(self, "输入错误", "请输入用户名或选择匿名登录")
            return
        
        # 保存设置
        self.save_settings()
        
        logger.info(f"准备连接到FTP服务器: {self.host_edit.text()}:{self.port_spin.value()}")
        super().accept()
