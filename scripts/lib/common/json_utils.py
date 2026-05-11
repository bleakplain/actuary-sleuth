"""JSON 解析工具"""
import re


def extract_json_array(text: str) -> str | None:
    """从 LLM 输出中提取 JSON 数组字符串

    处理 LLM 可能返回的格式：纯 JSON、带 markdown 代码块、混合文本等。
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # 尝试直接解析
    if text.startswith('['):
        bracket_count = 0
        for i, c in enumerate(text):
            if c == '[':
                bracket_count += 1
            elif c == ']':
                bracket_count -= 1
                if bracket_count == 0:
                    return text[:i + 1]
        return text + ']'

    # 提取 markdown 代码块中的 JSON
    code_block_match = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
    if code_block_match:
        return code_block_match.group(1).strip()

    # 查找第一个 [ 到最后一个 ]
    start = text.find('[')
    end = text.rfind(']')
    if start >= 0 and end > start:
        return text[start:end + 1]

    return None
