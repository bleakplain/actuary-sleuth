#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Any, Optional

from dotenv import load_dotenv

SCRIPTS_DIR = Path(__file__).parent.parent
load_dotenv(SCRIPTS_DIR / ".env")


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


class MemoryConfig:

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('memory', {})

    @property
    def ttl_days(self) -> int:
        return self._config.get('ttl_days', 30)

    @property
    def similarity_threshold(self) -> float:
        return self._config.get('similarity_threshold', 0.9)

    @property
    def confidence_threshold(self) -> float:
        return self._config.get('confidence_threshold', 0.6)


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
    def memory_dir(self) -> str:
        return self._config.get('memory_dir', '')


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

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._load()
        self._init_nested_configs()

    def _load(self) -> None:
        # 优先从环境变量读取所有配置，不再依赖 JSON 配置文件
        self._config = {
            # data_paths
            'data_paths': {
                'sqlite_db': os.getenv('DATA_PATHS_SQLITE_DB', '/root/work/actuary-assets/db/actuary.db'),
                'regulations_dir': os.getenv('DATA_PATHS_REGULATIONS_DIR', '/root/work/actuary-assets/kb/references'),
                'kb_version_dir': os.getenv('DATA_PATHS_KB_VERSION_DIR', '/root/work/actuary-assets/kb'),
                'eval_snapshots_dir': os.getenv('DATA_PATHS_EVAL_SNAPSHOTS_DIR', '/root/work/actuary-assets/eval/snapshots'),
                'models_dir': os.getenv('DATA_PATHS_MODELS_DIR', '/root/work/actuary-assets/models/reranker'),
                'memory_dir': os.getenv('DATA_PATHS_MEMORY_DIR', '/root/work/actuary-assets/memory'),
            },
            # ollama
            'ollama': {
                'host': os.getenv('OLLAMA_HOST', 'http://localhost:11434'),
                'timeout': int(os.getenv('OLLAMA_TIMEOUT', '120')),
            },
            # zhipu
            'zhipu': {
                'base_url': os.getenv('ZHIPU_BASE_URL', 'https://open.bigmodel.cn/api/paas/v4/'),
                'timeout': int(os.getenv('ZHIPU_TIMEOUT', '60')),
                'temperature': float(os.getenv('ZHIPU_TEMPERATURE', '0.1')),
                'max_tokens': int(os.getenv('ZHIPU_MAX_TOKENS', '16384')),
                'api_key': os.getenv('ZHIPU_API_KEY', ''),
            },
            # minmax
            'minmax': {
                'base_url': os.getenv('MINMAX_BASE_URL', 'https://api.minimaxi.com/v1'),
                'timeout': int(os.getenv('MINMAX_TIMEOUT', '60')),
                'temperature': float(os.getenv('MINMAX_TEMPERATURE', '0.1')),
                'max_tokens': int(os.getenv('MINMAX_MAX_TOKENS', '16384')),
                'api_key': os.getenv('MinMax_API_KEY', ''),
            },
            # llm
            'llm': {
                'embed': {
                    'provider': os.getenv('LLM_EMBED_PROVIDER', 'ollama'),
                    'model': os.getenv('LLM_EMBED_MODEL', 'qllama/bge-m3:q4_k_m'),
                },
                'eval': {
                    'provider': os.getenv('LLM_EVAL_PROVIDER', 'zhipu'),
                    'model': os.getenv('LLM_EVAL_MODEL', 'glm-4-flash'),
                    'timeout': int(os.getenv('LLM_EVAL_TIMEOUT', '180')),
                },
                'audit': {
                    'provider': os.getenv('LLM_AUDIT_PROVIDER', 'zhipu'),
                    'model': os.getenv('LLM_AUDIT_MODEL', 'glm-4-flash'),
                    'timeout': int(os.getenv('LLM_AUDIT_TIMEOUT', '120')),
                },
                'qa': {
                    'provider': os.getenv('LLM_QA_PROVIDER', 'zhipu'),
                    'model': os.getenv('LLM_QA_MODEL', 'glm-4-flash'),
                },
                'name_parser': {
                    'provider': os.getenv('LLM_NAME_PARSER_PROVIDER', 'zhipu'),
                    'model': os.getenv('LLM_NAME_PARSER_MODEL', 'glm-4-flash'),
                    'timeout': int(os.getenv('LLM_NAME_PARSER_TIMEOUT', '120')),
                },
                'ocr': {
                    'provider': os.getenv('LLM_OCR_PROVIDER', 'zhipu'),
                    'model': os.getenv('LLM_OCR_MODEL', 'glm-4-flash'),
                    'timeout': int(os.getenv('LLM_OCR_TIMEOUT', '120')),
                },
            },
            # feishu
            'feishu': {
                'app_id': os.getenv('FEISHU_APP_ID', ''),
                'app_secret': os.getenv('FEISHU_APP_SECRET', ''),
                'target_group_id': os.getenv('FEISHU_TARGET_GROUP_ID', ''),
            },
            # memory
            'memory': {
                'ttl_days': int(os.getenv('MEMORY_TTL_DAYS', '30')),
                'similarity_threshold': float(os.getenv('MEMORY_SIMILARITY_THRESHOLD', '0.9')),
                'confidence_threshold': float(os.getenv('MEMORY_CONFIDENCE_THRESHOLD', '0.6')),
            },
            # debug
            'debug': os.getenv('DEBUG', 'false').lower() == 'true',
            # cache
            'enable_cache': os.getenv('CACHE_ENABLED', 'false').lower() == 'true',
            'cache': {
                'embedding_ttl': int(os.getenv('CACHE_EMBEDDING_TTL', '86400')),
                'retrieval_ttl': int(os.getenv('CACHE_RETRIEVAL_TTL', '3600')),
                'generation_ttl': int(os.getenv('CACHE_GENERATION_TTL', '3600')),
            },
        }

    def _init_nested_configs(self) -> None:
        self._feishu = FeishuConfig(self._config)
        self._ollama = OllamaConfig(self._config)
        self._zhipu = ZhipuConfig(self._config)
        self._minimax = MinimaxConfig(self._config)
        self._llm = LLMConfig(self._config)
        self._data_paths = DatabaseConfig(self._config)
        self._memory = MemoryConfig(self._config)

    @property
    def feishu(self) -> FeishuConfig:
        return self._feishu

    @property
    def llm(self) -> LLMConfig:
        return self._llm

    @property
    def memory(self) -> MemoryConfig:
        return self._memory

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

    @property
    def debug(self) -> bool:
        return self._config.get('debug', False)

    @property
    def enable_cache(self) -> bool:
        return self._config.get('enable_cache', False)

    @property
    def cache(self) -> dict:
        return self._config.get('cache', {})

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

    def get_memory_dir(self) -> str:
        return self._resolve_path(self._data_paths.memory_dir)


# ===== 全局配置实例（单例模式）=====

_global_config: Optional[Config] = None
_config_lock = threading.Lock()


def _get_config() -> Config:
    global _global_config

    if _global_config is None:
        with _config_lock:
            if _global_config is None:
                _global_config = Config()

    return _global_config


# ===== 模块级快捷函数 =====

def is_debug() -> bool:
    return _get_config().debug

def get_sqlite_db_path() -> str:
    return _get_config().get_sqlite_db_path()

def get_regulations_dir() -> str:
    return _get_config().get_regulations_dir()

def get_kb_version_dir() -> str:
    return _get_config().get_kb_version_dir()

def get_eval_snapshots_dir() -> str:
    return _get_config().get_eval_snapshots_dir()

def get_models_dir() -> str:
    return _get_config().get_models_dir()

def get_memory_dir() -> str:
    return _get_config().get_memory_dir()

def get_llm_config() -> LLMConfig:
    return _get_config().llm

def is_cache_enabled() -> bool:
    return _get_config().enable_cache

def get_embedding_cache_ttl() -> int:
    return _get_config().cache.get("embedding_ttl", 86400)

def get_retrieval_cache_ttl() -> int:
    return _get_config().cache.get("retrieval_ttl", 3600)

def get_generation_cache_ttl() -> int:
    return _get_config().cache.get("generation_ttl", 3600)


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
    return _get_config().feishu

def get_memory_config() -> MemoryConfig:
    return _get_config().memory
