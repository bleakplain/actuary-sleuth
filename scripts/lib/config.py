#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置模块 - 提供统一的配置管理接口

使用示例：
    from lib.config import get_config

    config = get_config()
    app_id = config.feishu_app_id
    db_path = config.sqlite_db_path
"""
import json
import os
import sys
import threading
from pathlib import Path
from typing import Dict, Any, Optional


# 路径常量
SCRIPTS_DIR = Path(__file__).parent.parent
CONFIG_PATH = SCRIPTS_DIR / 'config' / 'settings.json'


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
        return self._config.get('app_id')

    @property
    def app_secret(self) -> Optional[str]:
        return self._config.get('app_secret')

    @property
    def enabled(self) -> bool:
        """检查飞书配置是否完整"""
        return bool(self.app_id and self.app_secret)

    @property
    def target_group_id(self) -> Optional[str]:
        """获取飞书目标群组ID"""
        return self._config.get('target_group_id')


class OllamaConfig:
    """Ollama 配置"""

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('ollama', {})

    @property
    def host(self) -> str:
        """Ollama 服务地址"""
        return self._config.get('host', 'http://localhost:11434')

    @property
    def timeout(self) -> int:
        """Ollama 超时时间（秒）"""
        return self._config.get('timeout', 120)


class LLMConfig:
    """LLM 场景配置（按用途选择 provider）"""

    _SCENES = ('qa', 'audit', 'eval', 'embed', 'name_parser', 'ocr')

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('llm', {})
        self._ollama = OllamaConfig(config_dict)
        self._zhipu = ZhipuConfig(config_dict)

    def _build(self, scene: str) -> Dict[str, Any]:
        scene_cfg = self._config.get(scene, {})
        provider = scene_cfg.get('provider', 'zhipu')
        timeout = scene_cfg.get('timeout') or (
            self._ollama.timeout if provider == 'ollama' else self._zhipu.timeout
        )
        config: Dict[str, Any] = {
            'provider': provider,
            'model': scene_cfg.get('model', ''),
            'timeout': timeout,
        }
        if provider == 'ollama':
            config['host'] = self._ollama.host
        else:
            config['api_key'] = self._zhipu.api_key
            config['base_url'] = self._zhipu.base_url
        return config

    @property
    def qa(self) -> Dict[str, Any]:
        return self._build('qa')

    @property
    def audit(self) -> Dict[str, Any]:
        return self._build('audit')

    @property
    def eval(self) -> Dict[str, Any]:
        return self._build('eval')

    @property
    def embed(self) -> Dict[str, Any]:
        return self._build('embed')

    @property
    def name_parser(self) -> Dict[str, Any]:
        return self._build('name_parser')

    @property
    def ocr(self) -> Dict[str, Any]:
        return self._build('ocr')


class ZhipuConfig:
    """智谱 API 配置"""

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('zhipu', {})

    @property
    def api_key(self) -> Optional[str]:
        return self._config.get('api_key')

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


class DatabaseConfig:
    """数据库路径配置"""

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('data_paths', {})

    @property
    def sqlite_db(self) -> str:
        """SQLite 数据库路径"""
        return self._config.get('sqlite_db', '../../data/actuary.db')

    @property
    def regulations_dir(self) -> str:
        """法规文件目录"""
        return self._config.get('regulations_dir', 'references')

    @property
    def kb_version_dir(self) -> str:
        """知识库版本目录"""
        return self._config.get('kb_version_dir', 'lib/rag_engine/data/kb')


# ===== 主配置类 =====

class Config:
    """
    配置管理类

    提供业务语义化的配置访问接口，支持：
    - 业务属性 (feishu_app_id, sqlite_db_path, ...)
    - 环境变量覆盖
    - 通用 get() 方法支持点号分隔的嵌套键

    使用示例：
        config = get_config()
        app_id = config.feishu_app_id
        db_path = config.sqlite_db_path
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
        """加载配置文件并合并环境变量"""
        if self._config_path.exists():
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load config from {self._config_path}: {e}", file=sys.stderr)
                self._config = {}
        else:
            self._config = {}

        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        """环境变量覆盖配置文件值（集中声明所有环境变量映射）"""
        _ENV_OVERRIDES = [
            # (section, key, env_var)
            ('feishu', 'app_id', 'FEISHU_APP_ID'),
            ('feishu', 'app_secret', 'FEISHU_APP_SECRET'),
            ('feishu', 'target_group_id', 'FEISHU_TARGET_GROUP_ID'),
            ('zhipu', 'api_key', 'ZHIPU_API_KEY'),
            ('openclaw', 'bin', 'OPENCLAW_BIN'),
        ]
        for section, key, env_var in _ENV_OVERRIDES:
            env_val = os.getenv(env_var)
            if env_val:
                self._config.setdefault(section, {})[key] = env_val

    def _init_nested_configs(self) -> None:
        """初始化嵌套配置对象（仅内部使用）"""
        self._feishu = FeishuConfig(self._config)
        self._ollama = OllamaConfig(self._config)
        self._zhipu = ZhipuConfig(self._config)
        self._llm = LLMConfig(self._config)
        self._data_paths = DatabaseConfig(self._config)

    # ===== 嵌套配置属性 =====

    @property
    def feishu(self) -> FeishuConfig:
        return self._feishu

    @property
    def llm(self) -> LLMConfig:
        return self._llm

    # ===== 业务属性 =====

    @property
    def feishu_app_id(self) -> Optional[str]:
        """飞书应用 ID"""
        return self._feishu.app_id

    @property
    def feishu_app_secret(self) -> Optional[str]:
        """飞书应用密钥"""
        return self._feishu.app_secret

    @property
    def feishu_group_id(self) -> Optional[str]:
        """飞书目标群组 ID"""
        return self._feishu.target_group_id

    @property
    def feishu_enabled(self) -> bool:
        """飞书配置是否完整"""
        return self._feishu.enabled

    @property
    def sqlite_db_path(self) -> str:
        """SQLite 数据库路径"""
        return self._data_paths.sqlite_db

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
        value: Any = self._config

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

    def _resolve_path(self, rel_path: str) -> str:
        """将配置路径解析为绝对路径（相对路径基于 scripts/ 目录）。"""
        p = Path(rel_path)
        if p.is_absolute():
            return rel_path
        return str(SCRIPTS_DIR / p)

    def get_regulations_dir(self) -> str:
        """获取法规文件目录的绝对路径。"""
        return self._resolve_path(self._data_paths.regulations_dir)

    def get_kb_version_dir(self) -> str:
        """获取知识库版本目录的绝对路径。"""
        return self._resolve_path(self._data_paths.kb_version_dir)

    def get_sqlite_db_path(self) -> str:
        """获取 SQLite 数据库的绝对路径。"""
        return self._resolve_path(self._data_paths.sqlite_db)


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


# ===== 模块级快捷函数 =====

def get_sqlite_db_path() -> str:
    """获取 SQLite 数据库的绝对路径。"""
    return get_config().get_sqlite_db_path()

def get_regulations_dir() -> str:
    """获取法规文件目录的绝对路径。"""
    return get_config().get_regulations_dir()

def get_kb_version_dir() -> str:
    """获取知识库版本目录的绝对路径。"""
    return get_config().get_kb_version_dir()

def get_llm_config() -> 'LLMConfig':
    """获取 LLM 配置。"""
    return get_config().llm


def get_qa_llm_config() -> Dict[str, Any]:
    return get_llm_config().qa

def get_audit_llm_config() -> Dict[str, Any]:
    return get_llm_config().audit

def get_eval_llm_config() -> Dict[str, Any]:
    return get_llm_config().eval

def get_embed_llm_config() -> Dict[str, Any]:
    return get_llm_config().embed

def get_name_parser_llm_config() -> Dict[str, Any]:
    return get_llm_config().name_parser

def get_ocr_llm_config() -> Dict[str, Any]:
    return get_llm_config().ocr

def get_feishu_config() -> 'FeishuConfig':
    """获取飞书配置。"""
    return get_config().feishu

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
