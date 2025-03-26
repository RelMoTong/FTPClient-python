"""FTP客户端设置对话框"""

from PyQt5.QtWidgets import (QDialog, QTabWidget, QVBoxLayout, QHBoxLayout, 
                           QFormLayout, QLabel, QLineEdit, QSpinBox, 
                           QCheckBox, QPushButton, QGroupBox, QDialogButtonBox,
                           QWidget)
from PyQt5.QtCore import QSettings, Qt
import logging

logger = logging.getLogger(__name__)

class SettingsDialog(QDialog):
    """FTP客户端设置对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(500, 400)
        
        # 创建界面
        self.setup_ui()
        
        # 加载设置
        self.load_settings()
    
    def setup_ui(self):
        """设置界面"""
        # 主布局
        main_layout = QVBoxLayout(self)
        
        # 创建选项卡
        tab_widget = QTabWidget()
        
        # 常规设置选项卡
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        
        # 连接设置组
        connection_group = QGroupBox("连接设置")
        connection_form = QFormLayout(connection_group)
        
        self.default_host_edit = QLineEdit()
        self.default_port_spin = QSpinBox()
        self.default_port_spin.setRange(1, 65535)
        self.default_port_spin.setValue(21)
        self.default_username_edit = QLineEdit()
        self.default_ssl_check = QCheckBox("默认使用SSL/TLS")
        self.passive_mode_check = QCheckBox("默认使用被动模式")
        self.passive_mode_check.setChecked(True)
        
        connection_form.addRow("默认主机:", self.default_host_edit)
        connection_form.addRow("默认端口:", self.default_port_spin)
        connection_form.addRow("默认用户名:", self.default_username_edit)
        connection_form.addRow("", self.default_ssl_check)
        connection_form.addRow("", self.passive_mode_check)
        
        general_layout.addWidget(connection_group)
        
        # 传输设置组
        transfer_group = QGroupBox("传输设置")
        transfer_form = QFormLayout(transfer_group)
        
        self.max_connections_spin = QSpinBox()
        self.max_connections_spin.setRange(1, 10)
        self.max_connections_spin.setValue(3)
        
        self.retry_count_spin = QSpinBox()
        self.retry_count_spin.setRange(0, 10)
        self.retry_count_spin.setValue(3)
        
        self.retry_delay_spin = QSpinBox()
        self.retry_delay_spin.setRange(1, 60)
        self.retry_delay_spin.setValue(5)
        
        transfer_form.addRow("最大并发任务数:", self.max_connections_spin)
        transfer_form.addRow("自动重试次数:", self.retry_count_spin)
        transfer_form.addRow("重试延迟(秒):", self.retry_delay_spin)
        
        general_layout.addWidget(transfer_group)
        general_layout.addStretch()
        
        # 添加选项卡
        tab_widget.addTab(general_tab, "常规")
        
        # 按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        # 添加到主布局
        main_layout.addWidget(tab_widget)
        main_layout.addWidget(button_box)
    
    def load_settings(self):
        """加载设置"""
        settings = QSettings("NewFTP", "FTPClient")
        
        # 连接设置
        self.default_host_edit.setText(settings.value("defaults/host", ""))
        self.default_port_spin.setValue(int(settings.value("defaults/port", 21)))
        self.default_username_edit.setText(settings.value("defaults/username", ""))
        self.default_ssl_check.setChecked(settings.value("defaults/ssl", False, type=bool))
        self.passive_mode_check.setChecked(settings.value("defaults/passive", True, type=bool))
        
        # 传输设置
        self.max_connections_spin.setValue(int(settings.value("transfer/max_connections", 3)))
        self.retry_count_spin.setValue(int(settings.value("transfer/retry_count", 3)))
        self.retry_delay_spin.setValue(int(settings.value("transfer/retry_delay", 5)))
    
    def save_settings(self):
        """保存设置"""
        settings = QSettings("NewFTP", "FTPClient")
        
        # 连接设置
        settings.setValue("defaults/host", self.default_host_edit.text())
        settings.setValue("defaults/port", self.default_port_spin.value())
        settings.setValue("defaults/username", self.default_username_edit.text())
        settings.setValue("defaults/ssl", self.default_ssl_check.isChecked())
        settings.setValue("defaults/passive", self.passive_mode_check.isChecked())
        
        # 传输设置
        settings.setValue("transfer/max_connections", self.max_connections_spin.value())
        settings.setValue("transfer/retry_count", self.retry_count_spin.value())
        settings.setValue("transfer/retry_delay", self.retry_delay_spin.value())
    
    def accept(self):
        """确定按钮处理"""
        # 保存设置
        self.save_settings()
        super().accept()
