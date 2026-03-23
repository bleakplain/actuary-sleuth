#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置模块 - 提供统一的配置管理接口

使用示例：
    from lib.config import get_config

    config = get_config()
    app_id = config.feishu.app_id
    export_enabled = config.report.export_feishu
"""
import json
import os
import re
import sys
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple


# 配置文件路径
CONFIG_PATH = Path(__file__).parent.parent / 'config' / 'settings.json'


# ===== 嵌套配置类 =====

class FeishuConfig:
    """飞书配置"""

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('feishu', {})
        self._validate_no_secrets_in_config()

    def _validate_no_secrets_in_config(self) -> None:
        if 'app_secret' in self._config and self._config['app_secret']:
            import warnings
            warnings.warn(
                "配置文件中检测到 app_secret。出于安全考虑，飞书应用密钥必须通过环境变量设置。",
                DeprecationWarning,
                stacklevel=2
            )

    @property
    def app_id(self) -> Optional[str]:
        env_app_id = os.getenv('FEISHU_APP_ID')
        if env_app_id:
            return env_app_id
        return self._config.get('app_id')

    @property
    def app_secret(self) -> Optional[str]:
        return os.getenv('FEISHU_APP_SECRET')

    @property
    def enabled(self) -> bool:
        """检查飞书配置是否完整"""
        return bool(self.app_id and self.app_secret)

    @property
    def target_group_id(self) -> Optional[str]:
        """获取飞书目标群组ID"""
        return self._config.get('target_group_id') or os.getenv('FEISHU_TARGET_GROUP_ID')


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

    @property
    def grade_thresholds(self) -> List[Tuple[int, str]]:
        """获取评级阈值"""
        default_thresholds = [(90, '优秀'), (75, '良好'), (60, '合格')]
        thresholds_config = self._config.get('grading', {}).get('thresholds', [])
        if thresholds_config:
            return [(t.get('score'), t.get('grade')) for t in thresholds_config]
        return default_thresholds

    @property
    def default_grade(self) -> str:
        """获取默认评级"""
        return self._config.get('grading', {}).get('default_grade', '不合格')

    @property
    def high_violations_limit(self) -> int:
        """获取严重违规限制"""
        return self._config.get('violations', {}).get('high_limit', 20)

    @property
    def medium_violations_limit(self) -> int:
        """获取中等违规限制"""
        return self._config.get('violations', {}).get('medium_limit', 10)

    @property
    def p1_remediation_limit(self) -> int:
        """获取 P1 整改限制"""
        return self._config.get('violations', {}).get('p1_remediation_limit', 5)

    def get_product_thresholds(self, product_category: str) -> Optional[List[Tuple[int, str]]]:
        """获取产品特定的评级阈值"""
        product_config = self._config.get('product_specific', {}).get(product_category)
        if product_config and 'grading' in product_config:
            thresholds_config = product_config['grading'].get('thresholds', [])
            return [(t.get('score'), t.get('grade')) for t in thresholds_config]
        return None

    def get_product_violation_limits(self, product_category: str) -> Optional[Dict[str, int]]:
        """获取产品特定的违规限制"""
        product_config = self._config.get('product_specific', {}).get(product_category)
        if product_config and 'violations' in product_config:
            return product_config['violations']
        return None


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


class LLMConfig:
    """LLM 配置（支持多种提供商）"""

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('llm', {})

    @property
    def provider(self) -> str:
        """LLM 提供商：zhipu, ollama"""
        return self._config.get('provider', 'zhipu')

    @property
    def model(self) -> str:
        """模型名称"""
        return self._config.get('model', 'glm-4-flash')

    @property
    def api_key(self) -> Optional[str]:
        return os.getenv('ZHIPU_API_KEY')

    @property
    def base_url(self) -> str:
        """API 基础URL"""
        return self._config.get('base_url', 'https://open.bigmodel.cn/api/paas/v4/')

    @property
    def timeout(self) -> int:
        """请求超时时间（秒）"""
        return self._config.get('timeout', 30)

    @property
    def temperature(self) -> float:
        """生成温度参数"""
        return self._config.get('temperature', 0.1)

    @property
    def max_tokens(self) -> int:
        """最大生成token数"""
        return self._config.get('max_tokens', 20000)

    def to_client_config(self) -> Dict[str, Any]:
        """转换为客户端配置字典"""
        config = {
            'provider': self.provider,
            'model': self.model,
            'timeout': self.timeout,
            'max_tokens': self.max_tokens
        }

        if self.provider == 'zhipu':
            config['api_key'] = self.api_key
            config['base_url'] = self.base_url
        elif self.provider == 'ollama':
            config['host'] = self._config.get('host', 'http://localhost:11434')

        return config


class DatabaseConfig:
    """数据库路径配置"""

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


class OpenClawConfig:
    """OpenClaw配置"""

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('openclaw', {})

    @property
    def bin(self) -> str:
        """OpenClaw二进制文件路径"""
        return self._config.get('bin', '/usr/bin/openclaw') or os.getenv('OPENCLAW_BIN', '/usr/bin/openclaw')


# ===== 主配置类 =====

class Config:
    """
    配置管理类

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
            config_path: 配置文件路径，默认使用 lib/config/settings.json
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
        self._llm = LLMConfig(self._config)
        self._data_paths = DatabaseConfig(self._config)
        self._regulation_search = RegulationSearchConfig(self._config)
        self._openclaw = OpenClawConfig(self._config)

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
    def llm(self) -> LLMConfig:
        """LLM 配置"""
        return self._llm

    @property
    def data_paths(self) -> DatabaseConfig:
        """数据库路径配置"""
        return self._data_paths

    @property
    def regulation_search(self) -> RegulationSearchConfig:
        """法规搜索配置"""
        return self._regulation_search

    @property
    def openclaw(self) -> 'OpenClawConfig':
        """OpenClaw配置"""
        return self._openclaw

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
_config_lock = threading.Lock()


def get_config(config_path: Optional[Path] = None) -> Config:
    """
    获取全局配置实例（线程安全单例模式）

    Args:
        config_path: 可选的自定义配置路径

    Returns:
        Config: 配置实例
    """
    global _global_config

    if _global_config is None or (config_path is not None and config_path != _global_config._config_path):
        with _config_lock:
            if _global_config is None or config_path is not None:
                if config_path is not None and _global_config is not None:
                    if config_path != _global_config._config_path:
                        _global_config = Config(config_path)
                else:
                    _global_config = Config(config_path)

    return _global_config


def reset_config() -> None:
    """重置全局配置（线程安全）"""
    global _global_config
    with _config_lock:
        _global_config = None


def reload_config() -> Config:
    """重新加载配置文件（线程安全）"""
    global _global_config
    with _config_lock:
        if _global_config is not None:
            config_path = _global_config._config_path
            _global_config = Config(config_path)
        else:
            _global_config = Config()
    return _global_config


def load_config() -> Dict[str, Any]:
    """
    加载配置文件并返回原始字典

    提供对底层配置数据的直接访问，用于需要字典格式的场景。

    Returns:
        dict: 配置字典，包含所有配置项的原始数据
    """
    config = get_config()
    return config._config
