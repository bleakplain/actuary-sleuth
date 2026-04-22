"""记忆上下文压缩。"""
from __future__ import annotations

from typing import Dict, List


def compress_memory_context(
    memories: List[Dict],
    max_chars: int = 2000,
) -> str:
    """按相关性智能选择记忆并压缩上下文。

    Args:
        memories: 记忆列表，每条记忆应包含 memory、created_at、score 字段
        max_chars: 最大字符数限制

    Returns:
        压缩后的记忆上下文字符串
    """
    if not memories:
        return ""

    sorted_memories = sorted(
        memories,
        key=lambda m: m.get("score", 0) or 0,
        reverse=True,
    )

    lines: List[str] = []
    total_chars = 0

    for m in sorted_memories:
        text = m.get("memory", "")
        created_at = m.get("created_at", "")
        date_str = created_at[:10] if created_at else ""

        line = f"- {text}"
        if date_str:
            line += f" (记录于 {date_str})"

        if total_chars + len(line) + 1 <= max_chars:
            lines.append(line)
            total_chars += len(line) + 1
        else:
            break

    return "\n".join(lines)
