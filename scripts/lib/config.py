#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Any, Optional


# 路径常量
SCRIPTS_DIR = Path(__file__).parent.parent
CONFIG_PATH = SCRIPTS_DIR / 'config' / 'settings.json'


# ===== 嵌套配置类 =====

class FeishuConfig:

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
        return bool(self.app_id and self.app_secret)

    @property
    def target_group_id(self) -> Optional[str]:
        return self._config.get('target_group_id')


class OllamaConfig:

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('ollama', {})

    @property
    def base_url(self) -> str:
        return self._config.get('host', 'http://localhost:11434')

    @property
    def api_key(self) -> str:
        return ''

    @property
    def temperature(self) -> float:
        return self._config.get('temperature', 0.1)

    @property
    def timeout(self) -> int:
        return self._config.get('timeout', 120)

    @property
    def max_tokens(self) -> int:
        return self._config.get('max_tokens', 8192)


class ZhipuConfig:

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('zhipu', {})

    @property
    def base_url(self) -> str:
        return self._config.get('base_url', 'https://open.bigmodel.cn/api/paas/v4/')

    @property
    def api_key(self) -> str:
        return self._config.get('api_key', '')

    @property
    def temperature(self) -> float:
        return self._config.get('temperature', 0.1)

    @property
    def timeout(self) -> int:
        return self._config.get('timeout', 30)

    @property
    def max_tokens(self) -> int:
        return self._config.get('max_tokens', 20000)


class MinimaxConfig:

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('minmax', {})

    @property
    def base_url(self) -> str:
        return self._config.get('base_url', 'https://api.minimaxi.com/v1')

    @property
    def api_key(self) -> str:
        return self._config.get('api_key', '')

    @property
    def temperature(self) -> float:
        return self._config.get('temperature', 0.1)

    @property
    def timeout(self) -> int:
        return self._config.get('timeout', 30)

    @property
    def max_tokens(self) -> int:
        return self._config.get('max_tokens', 16384)


class DatabaseConfig:

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('data_paths', {})

    @property
    def sqlite_db(self) -> str:
        return self._config.get('sqlite_db', '../../data/actuary.db')

    @property
    def regulations_dir(self) -> str:
        return self._config.get('regulations_dir', 'references')

    @property
    def kb_version_dir(self) -> str:
        return self._config.get('kb_version_dir', 'lib/rag_engine/data/kb')

    @property
    def eval_snapshots_dir(self) -> str:
        return self._config.get('eval_snapshots_dir', '')

    @property
    def models_dir(self) -> str:
        return self._config.get('models_dir', '')

    @property
    def tools_dir(self) -> str:
        return self._config.get('tools_dir', '')


# ===== 场景化 LLM 配置 =====

class LLMConfig:

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('llm', {})
        self._ollama = OllamaConfig(config_dict)
        self._zhipu = ZhipuConfig(config_dict)
        self._minimax = MinimaxConfig(config_dict)

    def _provider(self, provider: str):
        if provider == 'ollama':
            return self._ollama
        elif provider == 'minmax':
            return self._minimax
        elif provider == 'zhipu':
            return self._zhipu
        raise ValueError(f"Unsupported LLM provider: {provider}")

    def _build(self, scene: str) -> SimpleNamespace:
        scene_cfg = self._config.get(scene, {})
        provider = scene_cfg.get('provider', 'zhipu')
        p = self._provider(provider)
        return SimpleNamespace(
            provider=provider,
            base_url=p.base_url,
            api_key=p.api_key,
            model=scene_cfg.get('model', ''),
            temperature=p.temperature,
            timeout=p.timeout or scene_cfg.get('timeout'),
            max_tokens=p.max_tokens,
        )

    @property
    def qa(self) -> SimpleNamespace:
        return self._build('qa')

    @property
    def audit(self) -> SimpleNamespace:
        return self._build('audit')

    @property
    def eval(self) -> SimpleNamespace:
        return self._build('eval')

    @property
    def embed(self) -> SimpleNamespace:
        return self._build('embed')

    @property
    def name_parser(self) -> SimpleNamespace:
        return self._build('name_parser')

    @property
    def ocr(self) -> SimpleNamespace:
        return self._build('ocr')


# ===== 主配置类 =====

class Config:

    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = config_path or CONFIG_PATH
        self._config: Dict[str, Any] = {}
        self._load()
        self._init_nested_configs()

    def _load(self) -> None:
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
        _ENV_OVERRIDES = [
            ('feishu', 'app_id', 'FEISHU_APP_ID'),
            ('feishu', 'app_secret', 'FEISHU_APP_SECRET'),
            ('feishu', 'target_group_id', 'FEISHU_TARGET_GROUP_ID'),
            ('zhipu', 'api_key', 'ZHIPU_API_KEY'),
            ('minmax', 'api_key', 'MinMax_API_KEY'),
            ('openclaw', 'bin', 'OPENCLAW_BIN'),
        ]
        for section, key, env_var in _ENV_OVERRIDES:
            env_val = os.getenv(env_var)
            if env_val:
                self._config.setdefault(section, {})[key] = env_val

    def _init_nested_configs(self) -> None:
        self._feishu = FeishuConfig(self._config)
        self._ollama = OllamaConfig(self._config)
        self._zhipu = ZhipuConfig(self._config)
        self._minimax = MinimaxConfig(self._config)
        self._llm = LLMConfig(self._config)
        self._data_paths = DatabaseConfig(self._config)

    @property
    def feishu(self) -> FeishuConfig:
        return self._feishu

    @property
    def llm(self) -> LLMConfig:
        return self._llm

    @property
    def sqlite_db_path(self) -> str:
        return self._data_paths.sqlite_db

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split('.')
        value: Any = self._config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default

        return value if value is not None else default

    def reload(self) -> None:
        self._load()
        self._init_nested_configs()

    @property
    def version(self) -> str:
        return self._config.get('version', 'unknown')

    def _resolve_path(self, rel_path: str) -> str:
        p = Path(rel_path)
        if p.is_absolute():
            return rel_path
        return str(SCRIPTS_DIR / p)

    def get_regulations_dir(self) -> str:
        return self._resolve_path(self._data_paths.regulations_dir)

    def get_kb_version_dir(self) -> str:
        return self._resolve_path(self._data_paths.kb_version_dir)

    def get_sqlite_db_path(self) -> str:
        return self._resolve_path(self._data_paths.sqlite_db)

    def get_eval_snapshots_dir(self) -> str:
        return self._resolve_path(self._data_paths.eval_snapshots_dir)

    def get_models_dir(self) -> str:
        return self._resolve_path(self._data_paths.models_dir)

    def get_tools_dir(self) -> str:
        return self._resolve_path(self._data_paths.tools_dir)


# ===== 全局配置实例（单例模式）=====

_global_config: Optional[Config] = None
_config_lock = threading.Lock()


def get_config(config_path: Optional[Path] = None) -> Config:
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
    return get_config().get_sqlite_db_path()

def get_regulations_dir() -> str:
    return get_config().get_regulations_dir()

def get_kb_version_dir() -> str:
    return get_config().get_kb_version_dir()

def get_eval_snapshots_dir() -> str:
    return get_config().get_eval_snapshots_dir()

def get_models_dir() -> str:
    return get_config().get_models_dir()

def get_tools_dir() -> str:
    return get_config().get_tools_dir()

def get_llm_config() -> LLMConfig:
    return get_config().llm


def get_qa_llm_config() -> SimpleNamespace:
    return get_llm_config().qa

def get_audit_llm_config() -> SimpleNamespace:
    return get_llm_config().audit

def get_eval_llm_config() -> SimpleNamespace:
    return get_llm_config().eval

def get_embed_llm_config() -> SimpleNamespace:
    return get_llm_config().embed

def get_name_parser_llm_config() -> SimpleNamespace:
    return get_llm_config().name_parser

def get_ocr_llm_config() -> SimpleNamespace:
    return get_llm_config().ocr

def get_feishu_config() -> FeishuConfig:
    return get_config().feishu
