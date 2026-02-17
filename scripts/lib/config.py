#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置模块 - 嵌套结构版本
提供统一的配置管理接口，支持按需读取配置项

使用示例：
    config = get_config()
    app_id = config.feishu.app_id
    export_enabled = config.report.export_feishu
"""
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional


# 配置文件路径（相对于脚本目录）
CONFIG_PATH = Path(__file__).parent.parent / 'config' / 'settings.json'


# ===== 嵌套配置类 =====

class FeishuConfig:
    """飞书配置"""

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('feishu', {})

    @property
    def app_id(self) -> Optional[str]:
        """获取飞书应用 ID"""
        return self._config.get('app_id') or os.getenv('FEISHU_APP_ID')

    @property
    def app_secret(self) -> Optional[str]:
        """获取飞书应用密钥"""
        return self._config.get('app_secret') or os.getenv('FEISHU_APP_SECRET')

    @property
    def enabled(self) -> bool:
        """检查飞书配置是否完整"""
        return bool(self.app_id and self.app_secret)


class ReportConfig:
    """报告配置"""

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('report', {})

    @property
    def export_feishu(self) -> bool:
        """是否自动导出飞书文档"""
        return self._config.get('export_feishu', False)

    @property
    def output_dir(self) -> str:
        """报告输出目录"""
        return self._config.get('output_dir', './reports')

    @property
    def default_format(self) -> str:
        """默认报告格式"""
        return self._config.get('default_format', 'feishu')


class AuditConfig:
    """审核配置"""

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('audit', {})

    @property
    def scoring_weights(self) -> Dict[str, int]:
        """审核评分权重"""
        return self._config.get('scoring_weights', {
            'high': 10,
            'medium': 5,
            'low': 2
        })

    @property
    def thresholds(self) -> Dict[str, int]:
        """审核评级阈值"""
        return self._config.get('thresholds', {
            'excellent': 90,
            'good': 75,
            'pass': 60
        })


class OllamaConfig:
    """Ollama 配置"""

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('ollama', {})

    @property
    def host(self) -> str:
        """Ollama 服务地址"""
        return self._config.get('host', 'http://localhost:11434')

    @property
    def chat_model(self) -> str:
        """Ollama 聊天模型"""
        return self._config.get('chat_model', 'qwen2:7b')

    @property
    def embed_model(self) -> str:
        """Ollama 嵌入模型"""
        return self._config.get('embed_model', 'nomic-embed-text')

    @property
    def timeout(self) -> int:
        """Ollama 超时时间（秒）"""
        return self._config.get('timeout', 120)


class DataPathsConfig:
    """数据路径配置"""

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('data_paths', {})

    @property
    def sqlite_db(self) -> str:
        """SQLite 数据库路径"""
        return self._config.get('sqlite_db', '../../data/actuary.db')

    @property
    def lancedb_uri(self) -> str:
        """LanceDB 连接字符串"""
        return self._config.get('lancedb_uri', '../../data/lancedb')

    @property
    def negative_list(self) -> str:
        """负面清单文件路径"""
        return self._config.get('negative_list', 'data/negative_list.json')

    @property
    def industry_standards(self) -> str:
        """行业标准文件路径"""
        return self._config.get('industry_standards', 'data/industry_standards.json')

    @property
    def audit_logs(self) -> str:
        """审核日志文件路径"""
        return self._config.get('audit_logs', 'data/audit_logs.json')


class RegulationSearchConfig:
    """法规搜索配置"""

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('regulation_search', {})

    @property
    def data_dir(self) -> str:
        """法规数据目录"""
        return self._config.get('data_dir', '../../references')

    @property
    def default_top_k(self) -> int:
        """法规搜索默认返回数量"""
        return self._config.get('default_top_k', 5)


# ===== 主配置类 =====

class Config:
    """
    配置管理类（嵌套结构版本）

    提供类型安全的嵌套配置访问接口，支持：
    - 按需读取配置项
    - 类型提示和默认值
    - 环境变量回退
    - 配置验证

    使用示例：
        config = get_config()
        app_id = config.feishu.app_id
        export_enabled = config.report.export_feishu
    """

    def __init__(self, config_path: Optional[Path] = None):
        """
        初始化配置

        Args:
            config_path: 配置文件路径，默认使用 scripts/config/settings.json
        """
        self._config_path = config_path or CONFIG_PATH
        self._config: Dict[str, Any] = {}
        self._load()
        self._init_nested_configs()

    def _load(self) -> None:
        """加载配置文件"""
        if self._config_path.exists():
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load config from {self._config_path}: {e}", file=sys.stderr)
                self._config = {}
        else:
            self._config = {}

    def _init_nested_configs(self) -> None:
        """初始化嵌套配置对象"""
        self._feishu = FeishuConfig(self._config)
        self._report = ReportConfig(self._config)
        self._audit = AuditConfig(self._config)
        self._ollama = OllamaConfig(self._config)
        self._data_paths = DataPathsConfig(self._config)
        self._regulation_search = RegulationSearchConfig(self._config)

    # ===== 嵌套配置属性 =====

    @property
    def feishu(self) -> FeishuConfig:
        """飞书配置"""
        return self._feishu

    @property
    def report(self) -> ReportConfig:
        """报告配置"""
        return self._report

    @property
    def audit(self) -> AuditConfig:
        """审核配置"""
        return self._audit

    @property
    def ollama(self) -> OllamaConfig:
        """Ollama 配置"""
        return self._ollama

    @property
    def data_paths(self) -> DataPathsConfig:
        """数据路径配置"""
        return self._data_paths

    @property
    def regulation_search(self) -> RegulationSearchConfig:
        """法规搜索配置"""
        return self._regulation_search

    # ===== 通用方法 =====

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置项（通用方法）

        Args:
            key: 配置键，支持点号分隔的嵌套键（如 'feishu.app_id'）
            default: 默认值

        Returns:
            配置值，如果不存在则返回默认值

        使用示例：
            value = config.get('feishu.app_id')
            value = config.get('unknown.key', 'default_value')
        """
        keys = key.split('.')
        value = self._config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default

        return value if value is not None else default

    def reload(self) -> None:
        """重新加载配置文件"""
        self._load()
        self._init_nested_configs()

    @property
    def version(self) -> str:
        """配置版本"""
        return self._config.get('version', 'unknown')


# ===== 全局配置实例（单例模式）=====

_global_config: Optional[Config] = None


def get_config(config_path: Optional[Path] = None) -> Config:
    """
    获取全局配置实例（单例模式）

    Args:
        config_path: 可选的自定义配置路径

    Returns:
        Config: 配置实例
    """
    global _global_config

    if _global_config is None or config_path is not None:
        _global_config = Config(config_path)

    return _global_config


def reset_config() -> None:
    """重置全局配置（主要用于测试）"""
    global _global_config
    _global_config = None


# ===== 兼容旧代码的函数 =====

def load_config() -> Dict[str, Any]:
    """
    加载配置文件（兼容函数，返回原始字典）

    Deprecated: 建议使用 Config 类或 get_config() 函数

    Returns:
        dict: 配置字典
    """
    config = get_config()
    return config._config
