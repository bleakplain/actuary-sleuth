"""LLM 工具函数 — 获取客户端和解析响应的共享实现。"""
import json
import logging
from typing import Dict

logger = logging.getLogger(__name__)


def get_llm_client():
    """获取 LLM 客户端，延迟导入避免循环依赖。"""
    from api.app import rag_engine
    if rag_engine is None:
        raise RuntimeError("RAG 引擎未就绪")
    return rag_engine.llm_provider()


def parse_llm_json_response(text: str) -> Dict:
    """从 LLM 响应中提取 JSON，处理 markdown 代码块包裹。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)
