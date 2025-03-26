import json
import os
import logging
from pathlib import Path

class Config:
    """配置管理类，负责加载和提供配置项访问"""
    
    def __init__(self, config_file):
        """
        初始化配置对象
        
        Args:
            config_file (str): 配置文件路径
        """
        # 确保路径格式正确
        if isinstance(config_file, str):
            # 处理Windows路径中可能缺少反斜杠的情况 (如 e:Python 应该是 e:\Python)
            if len(config_file) >= 2 and config_file[0].isalpha() and config_file[1] == ':':
                if len(config_file) == 2 or (config_file[2] != '\\' and config_file[2] != '/'):
                    config_file = f"{config_file[0:2]}\\{config_file[2:]}"
                    
            # 标准化路径分隔符
            config_file = config_file.replace('/', os.sep).replace('\\', os.sep)
            
            # 确保路径是绝对路径
            if not os.path.isabs(config_file):
                # 如果是相对路径，则相对于当前工作目录
                config_file = os.path.abspath(config_file)
                
            logging.debug(f"规范化后的配置文件路径: {config_file}")
        
        self.config_file = Path(config_file)
        self.config = {}
        self.last_modified = 0
        self.load_config()
        
    def load_config(self):
        """加载配置文件"""
        try:
            # 检查文件是否存在
            if not self.config_file.exists():
                logging.warning(f"配置文件不存在: {self.config_file}")
                # 尝试创建默认配置
                self._create_default_config()
                return False
            
            # 检查文件是否被修改
            try:
                current_mtime = os.path.getmtime(self.config_file)
                if current_mtime <= self.last_modified:
                    return False  # 文件未修改
            except (FileNotFoundError, PermissionError) as e:
                logging.error(f"检查文件修改时间失败: {e}")
                return False
                
            logging.info(f"正在加载配置文件: {self.config_file}")
            with open(self.config_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                # 处理可能的JSON注释(以//开头的行)
                lines = [line for line in content.splitlines() if not line.strip().startswith('//')]
                clean_content = '\n'.join(lines)
                self.config = json.loads(clean_content)
                
            self.last_modified = current_mtime
            logging.info(f"成功加载配置文件: {self.config_file}")
            return True
        except json.JSONDecodeError as e:
            logging.error(f"配置文件格式错误: {e}")
            return False
        except Exception as e:
            logging.error(f"加载配置文件失败: {e}")
            return False
    
    def _create_default_config(self):
        """创建默认配置文件"""
        try:
            # 确保目录存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 根据文件名决定创建哪种默认配置
            if self.config_file.name == 'client_config.json':
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
            else:
                # 通用默认配置
                default_config = {}
            
            # 写入默认配置
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4)
            
            self.config = default_config
            self.last_modified = os.path.getmtime(self.config_file)
            logging.info(f"已创建默认配置文件: {self.config_file}")
            return True
        except Exception as e:
            logging.error(f"创建默认配置文件失败: {e}")
            return False
    
    def reload_if_modified(self):
        """如果文件被修改则重新加载"""
        return self.load_config()
    
    def get(self, key, default=None):
        """
        获取配置项
        
        Args:
            key (str): 配置项名称
            default: 默认值，如果配置项不存在则返回此值
            
        Returns:
            配置项的值
        """
        return self.config.get(key, default)
    
    def set(self, key, value):
        """
        设置配置项
        
        Args:
            key (str): 配置项名称
            value: 配置项的值
        """
        self.config[key] = value
    
    def save(self):
        """保存配置到文件"""
        try:
            # 确保目录存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4)
                
            self.last_modified = os.path.getmtime(self.config_file)
            logging.info(f"成功保存配置到: {self.config_file}")
            return True
        except Exception as e:
            logging.error(f"保存配置失败: {e}")
            return False
