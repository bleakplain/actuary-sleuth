"""规则意图分类器。

判定用户问题属于检索类还是元数据类（catalog/count/metadata）。
默认 content，未命中规则的都走现有 RAG 检索。
"""
import re
from typing import Literal, Optional, Tuple

IntentType = Literal["catalog", "count", "metadata", "content"]

_CATALOG_PATTERNS = [
    r'有哪些法规', r'有什么法规', r'都有什么法规',
    r'法规列表', r'法规目录', r'法规清单',
    r'包含哪些', r'包含什么', r'收录了哪些', r'收录了什么',
    r'知识库.{0,5}有哪些', r'都有哪些',
]

_COUNT_PATTERNS = [
    r'多少(部|个|条|项)法规', r'共几(部|个|条|项)',
    r'法规总数', r'法规数量', r'有多少法规',
    r'知识库.{0,5}多少', r'一共.{0,5}多少',
]

# 形如 "{法规名}什么时候实施" / "XX办法哪年发布" 等
# 结尾词覆盖常见法规类型；问题模式覆盖时间/机关/文号三类
_LAW_SUFFIX = r'(?:办法|规定|条例|保险法|通知|公告|清单|规范|指引|细则|意见|决定|令)'

_METADATA_PATTERNS = [
    re.compile(rf'(?P<law>.{{0,40}}{_LAW_SUFFIX}(?:\s*\d{{4}}\s*版)?).{{0,8}}(?:什么时候|哪年|哪一年|发布日期|实施时间|施行时间|生效时间|什么时候发布|什么时候实施|什么时候施行)'),
    re.compile(rf'(?P<law>.{{0,40}}{_LAW_SUFFIX}(?:\s*\d{{4}}\s*版)?).{{0,8}}(?:发布机关|发文机关|谁发的|哪个部门|监管部门|主管部门)'),
    re.compile(rf'(?P<law>.{{0,40}}{_LAW_SUFFIX}(?:\s*\d{{4}}\s*版)?).{{0,8}}(?:文号|第\s*\d+\s*号)'),
    # 单部法规的条款数查询："保险法有多少条" / "健康保险管理办法共几条"
    re.compile(rf'(?P<law>.{{0,40}}{_LAW_SUFFIX}(?:\s*\d{{4}}\s*版)?).{{0,5}}(?:有多少条|共几条|共多少条|多少条款|条款数|几条)'),
]

_CATALOG_RE = [re.compile(p) for p in _CATALOG_PATTERNS]
_COUNT_RE = [re.compile(p) for p in _COUNT_PATTERNS]


def classify_intent(question: str) -> Tuple[IntentType, Optional[str]]:
    """返回 (意图类型, 元数据类问题中提及的法规名)。

    优先级：metadata（含具体法规名） > catalog > count > content
    这样"健康保险管理办法共几条"会走 metadata 而非 count。

    Args:
        question: 用户问题

    Returns:
        (intent, law_name)
        - intent: catalog / count / metadata / content
        - law_name: 仅 metadata 意图时返回匹配到的法规名，其他为 None
    """
    q = question.strip()

    for p in _METADATA_PATTERNS:
        m = p.search(q)
        if m:
            law = m.group("law").strip()
            return "metadata", law

    for p in _CATALOG_RE:
        if p.search(q):
            return "catalog", None

    for p in _COUNT_RE:
        if p.search(q):
            return "count", None

    return "content", None
