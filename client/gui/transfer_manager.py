"""FTP客户端传输管理器组件"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
                           QTableWidgetItem, QPushButton, QHeaderView,
                           QProgressBar, QLabel, QMenu, QMessageBox)
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor
import logging

from client.transfer_queue import TaskStatus

logger = logging.getLogger(__name__)

class TransferManager(QWidget):
    """传输管理器组件，用于显示和管理传输任务"""
    
    # 信号定义
    cancelRequested = pyqtSignal(str)  # 任务ID
    clearCompletedRequested = pyqtSignal()  # 清除完成的任务
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 初始化界面
        self.setup_ui()
        
        # 任务ID到行索引的映射
        self.task_rows = {}
    
    def setup_ui(self):
        """设置界面"""
        # 主布局
        main_layout = QVBoxLayout(self)
        
        # 传输任务表
        self.task_table = QTableWidget()
        self.task_table.setColumnCount(7)
        self.task_table.setHorizontalHeaderLabels(
            ["ID", "类型", "源", "目标", "状态", "进度", "操作"]
        )
        self.task_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.task_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.task_table.setContextMenuPolicy(Qt.CustomContextMenu)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        self.clear_button = QPushButton("清除已完成")
        self.cancel_all_button = QPushButton("取消所有")
        
        button_layout.addWidget(self.clear_button)
        button_layout.addWidget(self.cancel_all_button)
        button_layout.addStretch()
        
        # 状态标签
        self.status_label = QLabel("准备就绪")
        
        # 添加到主布局
        main_layout.addWidget(self.task_table)
        main_layout.addLayout(button_layout)
        main_layout.addWidget(self.status_label)
        
        # 连接信号
        self.task_table.customContextMenuRequested.connect(self.show_context_menu)
        self.clear_button.clicked.connect(self.clearCompletedRequested)
        self.cancel_all_button.clicked.connect(self.cancel_all_tasks)
    
    def add_task(self, task):
        """
        添加任务到表格
        
        Args:
            task: TransferTask对象
        """
        row = self.task_table.rowCount()
        self.task_table.insertRow(row)
        
        # 保存任务ID到行索引的映射
        self.task_rows[task.id] = row
        
        # 设置单元格
        self.task_table.setItem(row, 0, QTableWidgetItem(task.id))
        self.task_table.setItem(row, 1, QTableWidgetItem(self.get_task_type_name(task.type.name)))
        
        # 源路径
        if task.type.name == "UPLOAD":
            source = task.args[0]
        else:
            source = task.args[0] if task.args else "-"
        self.task_table.setItem(row, 2, QTableWidgetItem(source))
        
        # 目标路径
        if task.type.name == "UPLOAD":
            target = task.args[1] if len(task.args) > 1 else "-"
        elif task.type.name == "DOWNLOAD":
            target = task.args[1] if len(task.args) > 1 else "-"
        else:
            target = "-"
        self.task_table.setItem(row, 3, QTableWidgetItem(target))
        
        # 状态
        self.task_table.setItem(row, 4, QTableWidgetItem(self.get_status_name(task.status.name)))
        
        # 进度条
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(int(task.progress))
        progress_bar.setTextVisible(True)
        progress_bar.setFormat("%p%")
        self.task_table.setCellWidget(row, 5, progress_bar)
        
        # 操作按钮
        cancel_button = QPushButton("取消")
        cancel_button.setProperty("task_id", task.id)
        cancel_button.clicked.connect(lambda: self.cancel_task(task.id))
        
        self.task_table.setCellWidget(row, 6, cancel_button)
        
        # 设置样色以标识任务状态
        self.update_row_color(row, task.status)
    
    def update_task(self, task):
        """
        更新任务状态
        
        Args:
            task: TransferTask对象
        """
        if task.id not in self.task_rows:
            self.add_task(task)
            return
        
        row = self.task_rows[task.id]
        
        # 更新状态
        self.task_table.item(row, 4).setText(self.get_status_name(task.status.name))
        
        # 更新进度条
        progress_bar = self.task_table.cellWidget(row, 5)
        if progress_bar:
            progress_bar.setValue(int(task.progress))
        
        # 更新行颜色
        self.update_row_color(row, task.status)
        
        # 如果任务已完成或失败，禁用取消按钮
        if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED]:
            cancel_button = self.task_table.cellWidget(row, 6)
            if cancel_button:
                cancel_button.setEnabled(False)
    
    def update_row_color(self, row, status):
        """
        根据任务状态更新行颜色
        
        Args:
            row: 行索引
            status: 任务状态
        """
        color = QColor(255, 255, 255)  # 默认白色
        
        if status == TaskStatus.RUNNING:
            color = QColor(173, 216, 230)  # 淡蓝色
        elif status == TaskStatus.COMPLETED:
            color = QColor(144, 238, 144)  # 淡绿色
        elif status == TaskStatus.FAILED:
            color = QColor(255, 192, 203)  # 淡红色
        elif status == TaskStatus.CANCELED:
            color = QColor(211, 211, 211)  # 淡灰色
        
        for col in range(self.task_table.columnCount()):
            item = self.task_table.item(row, col)
            if item:
                item.setBackground(color)
    
    def get_status_name(self, status_name):
        """获取状态的中文名称"""
        status_names = {
            "PENDING": "等待中",
            "RUNNING": "传输中",
            "COMPLETED": "已完成",
            "FAILED": "失败",
            "CANCELED": "已取消",
            "PAUSED": "已暂停",
            "RETRYING": "重试中"
        }
        return status_names.get(status_name, status_name)
    
    def get_task_type_name(self, type_name):
        """获取任务类型的中文名称"""
        type_names = {
            "UPLOAD": "上传",
            "DOWNLOAD": "下载",
            "DELETE": "删除",
            "RENAME": "重命名",
            "MKDIR": "创建目录",
            "RMDIR": "删除目录",
            "LIST": "列表"
        }
        return type_names.get(type_name, type_name)
    
    def cancel_task(self, task_id):
        """取消任务"""
        reply = QMessageBox.question(
            self, "确认取消", f"确定要取消任务 {task_id} 吗？", 
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.cancelRequested.emit(task_id)
            
            # 禁用取消按钮
            if task_id in self.task_rows:
                row = self.task_rows[task_id]
                cancel_button = self.task_table.cellWidget(row, 6)
                if cancel_button:
                    cancel_button.setEnabled(False)
    
    def cancel_all_tasks(self):
        """取消所有任务"""
        reply = QMessageBox.question(
            self, "确认取消", "确定要取消所有任务吗？", 
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            for task_id in list(self.task_rows.keys()):
                self.cancelRequested.emit(task_id)
    
    def show_context_menu(self, position):
        """显示上下文菜单"""
        menu = QMenu(self)
        cancel_action = menu.addAction("取消")
        
        action = menu.exec_(self.task_table.viewport().mapToGlobal(position))
        
        if action == cancel_action:
            index = self.task_table.indexAt(position)
            if index.isValid():
                task_id = self.task_table.item(index.row(), 0).text()
                self.cancel_task(task_id)
    
    def clear_completed_tasks(self):
        """清除已完成的任务"""
        for row in range(self.task_table.rowCount() - 1, -1, -1):
            status = self.task_table.item(row, 4).text()
            if status in ["已完成", "已取消"]:
                task_id = self.task_table.item(row, 0).text()
                self.task_rows.pop(task_id, None)
                self.task_table.removeRow(row)
    
    def update_status_label(self, active_count, pending_count, completed_count):
        """更新状态标签"""
        status = f"活动任务: {active_count} | 等待任务: {pending_count} | 已完成任务: {completed_count}"
        self.status_label.setText(status)
