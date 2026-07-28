"""产品条款主题的确定性标签器。"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple


@lru_cache(maxsize=1)
def _load_keywords() -> Dict[str, Tuple[str, ...]]:
    path = Path(__file__).parent / "data" / "clause_topic_keywords.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {topic: tuple(words) for topic, words in raw.items()}


def tag_clause_topics(title: str, text: str) -> Tuple[str, ...]:
    """按标题优先、正文补充的方式返回受控主题代码。"""
    topics = []
    for topic, keywords in _load_keywords().items():
        if any(keyword in title for keyword in keywords):
            topics.append(topic)
    content = f"{title}\n{text}"
    if "续保" in content:
        if "不保证续保" in content:
            topics.append("renewal.non_guaranteed")
        elif "保证续保" in content:
            topics.append("renewal.guaranteed")
    return tuple(dict.fromkeys(topics))
