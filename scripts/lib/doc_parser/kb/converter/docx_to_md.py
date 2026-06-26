#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DOCX 法规手册 -> Markdown 知识库转换脚本.

将《产品开发相关法律法规手册2026.4.docx》按法规章节拆分为结构化 Markdown 文件。
解析 TOC 获取章节->部分映射，在正文中用 font size + 位置映射定位章节边界。
"""
import argparse
import logging
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
_SENTENCE_ENDS = set('。；！？!?;')

_SECTION_TO_COLLECTION = {
    "第一部分": "00_保险法",
    "第二部分": "01_负面清单检查",
    "第三部分": "02_条款费率管理办法",
    "第四部分": "03_健康保险管理办法",
    "第五部分": "04_普通型人身保险",
    "第六部分": "05_分红型人身保险",
    "第七部分": "06_短期健康保险",
    "第八部分": "07_意外伤害保险",
    "第九部分": "08_互联网保险产品",
    "第十部分": "09_税优健康险",
    "第十一部分": "11_万能型人身保险",
    "第十二部分": "12_其他险种",
    "第十三部分": "10_其他监管规定",
}

_NON_INSURANCE_TYPE_DIRS = {
    "00_保险法", "01_负面清单检查", "02_条款费率管理办法",
    "10_其他监管规定", "12_其他险种",
}

# Patterns for filtering non-title large-font paragraphs
_DECOR_FILE_PATTERNS = [
    r'^中国保险监督管理委员会文件$',
    r'^中国银保监会办公厅文件$',
    r'^国家金融监督管理总局文件$',
    r'^国家金融监督管理总局人身保险监管司$',
]
_SUBSECTION_PAT = re.compile(r'^第[一二三四五六七八九十]+部分\s')
_TABLE_PAT = re.compile(r'XXXX|格式[一二三四五六七八九十]')
_NOISE_PAT = re.compile(r'修订内容\s*对比表|产品信息表$|经营情况报告|答记者问|令$')
_SECTION_DESC_PAT = re.compile(r'相关监管规定')


@dataclass
class _Paragraph:
    index: int
    font_size: Optional[int]
    text: str


@dataclass
class _TocEntry:
    chapter_num: int
    title: str
    section_name: str


@dataclass
class _Chapter:
    chapter_num: int
    title: str
    section_name: str
    collection: str
    body_text: str


def _nc(ch: str) -> str:
    if ch in ' \t\n\r《》""''〔〕':
        return ''
    if ch in '（(':
        return '('
    if ch in '）)':
        return ')'
    return ch


def _norm(s: str) -> str:
    return ''.join(_nc(c) for c in s)


def _extract_paragraphs(docx_path: str) -> List[_Paragraph]:
    with zipfile.ZipFile(docx_path) as z:
        with z.open('word/document.xml') as f:
            data = f.read()
    tree = ET.fromstring(data)
    raw = tree.findall('.//w:p', _NS)
    result = []
    for i, p in enumerate(raw):
        runs = p.findall('.//w:r', _NS)
        texts = [r.find('w:t', _NS).text for r in runs if r.find('w:t', _NS) is not None]
        text = ''.join(t for t in texts if t)
        sz = None
        for r in runs:
            rpr = r.find('w:rPr', _NS)
            if rpr is not None:
                e = rpr.find('w:sz', _NS)
                if e is not None:
                    v = e.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
                    if v:
                        sz = int(v)
                        break
        result.append(_Paragraph(index=i, font_size=sz, text=text))
    return result


def parse_toc(paragraphs: List[_Paragraph]) -> List[_TocEntry]:
    sections: Dict[str, str] = {}
    current_section = ""
    chapter_data: List[Tuple[int, str]] = []

    for p in paragraphs:
        if p.font_size not in (22, 19):
            continue
        text = p.text.strip()
        if not text:
            continue
        if p.font_size == 22:
            m = re.match(r'(第[一二三四五六七八九十]+部分)', text)
            if m:
                current_section = m.group(1)
            continue
        if p.font_size == 19:
            m = re.match(r'\s*第\s*(\d+)\s*章\s+(.*?)\s*[\.\s]*\d*\s*$', text)
            if m:
                ch_num = int(m.group(1))
                title = m.group(2).strip()
                title = re.sub(r'\.{2,}.*$', '', title).strip()
                title = re.sub(r'\s+', ' ', title)
                chapter_data.append((ch_num, title))
                sections[str(ch_num)] = current_section

    entries = []
    for ch_num, title in chapter_data:
        entries.append(_TocEntry(chapter_num=ch_num, title=title, section_name=sections.get(str(ch_num), "")))
    entries.sort(key=lambda e: e.chapter_num)
    return entries


def _get_collection(section_name: str) -> str:
    return _SECTION_TO_COLLECTION.get(section_name, "10_其他监管规定")


def _is_section_header(p: _Paragraph) -> bool:
    if p.font_size != 44:
        return False
    return bool(re.match(r'第[一二三四五六七八九十]+部分', p.text.strip()))


def _is_decorative(text: str, font_size: Optional[int]) -> bool:
    if font_size is not None and font_size >= 60:
        return True
    stripped = text.strip()
    if any(re.match(pat, stripped) for pat in _DECOR_FILE_PATTERNS):
        return True
    # Short agency names without regulation title (e.g., "国家金融监督管理总局" alone)
    if re.match(r'^(中国银行保险监督管理委员会|中国保险监督管理委员会|国家金融监督管理总局)$', stripped):
        return True
    return False


def _collect_title_groups(
    paragraphs: List[_Paragraph], start: int, end: int,
    skip_section_header: bool = True,
) -> List[Tuple[int, int, str]]:
    """Collect groups of consecutive large-font paragraphs within a range."""
    groups: List[Tuple[int, int, str]] = []
    i = start
    while i < end:
        p = paragraphs[i]
        if p.font_size is not None and p.font_size >= 34 and p.text.strip():
            # Skip section header paragraphs within body
            if skip_section_header and _is_section_header(p):
                i += 1
                continue
            # Merge consecutive large-font paragraphs
            grp_start = i
            grp_end = i
            texts = [p.text.strip()]
            j = i + 1
            while j < end and j - grp_end <= 3:
                pj = paragraphs[j]
                if pj.font_size is not None and pj.font_size >= 34 and pj.text.strip():
                    if skip_section_header and _is_section_header(pj):
                        break
                    grp_end = j
                    texts.append(pj.text.strip())
                    j += 1
                elif not pj.text.strip() or pj.font_size is None:
                    j += 1
                else:
                    break
            combined = ' '.join(texts)
            groups.append((grp_start, grp_end, combined))
            i = j
        else:
            i += 1
    return groups


def _filter_title_groups(
    groups: List[Tuple[int, int, str]],
    section_header_idx: int,
    paragraphs: List[_Paragraph],
) -> List[Tuple[int, int, str]]:
    """Remove non-title groups: decorative, sub-sections, tables, noise, section descriptions."""
    filtered = []
    for gs, ge, gtext in groups:
        # Skip decorative elements
        if _is_decorative(gtext, paragraphs[gs].font_size):
            continue
        # Skip sub-sections within regulations (e.g., "第一部分 总则" inside 分红保险精算规定)
        if _SUBSECTION_PAT.match(gtext):
            continue
        # Skip tables/forms
        if _TABLE_PAT.search(gtext):
            continue
        # Skip noise (对比表, 信息表, 答记者问, etc.)
        if _NOISE_PAT.search(gtext):
            continue
        # Skip section description (first group after section header containing "相关监管规定")
        if gs - section_header_idx <= 5 and _SECTION_DESC_PAT.search(gtext):
            continue
        filtered.append((gs, ge, gtext))
    return filtered


def _deduplicate_groups(groups: List[Tuple[int, int, str]]) -> List[Tuple[int, int, str]]:
    """Remove groups with similar normalized text within 300 paragraphs of each other."""
    result: List[Tuple[int, int, str]] = []
    for gs, ge, gtext in groups:
        norm_prefix = _norm(gtext)[:24]
        is_dup = False
        for rs, _, rtext in result:
            if abs(gs - rs) < 300 and _norm(rtext)[:24] == norm_prefix:
                is_dup = True
                break
        if not is_dup:
            result.append((gs, ge, gtext))
    return result


def _match_to_toc(
    groups: List[Tuple[int, int, str]],
    toc_entries: List[_TocEntry],
    section_name: str,
) -> List[Tuple[int, int, _TocEntry]]:
    """Match title groups to TOC entries by positional order with text validation."""
    matches: List[Tuple[int, int, _TocEntry]] = []
    toc_idx = 0

    def _short_core(norm_title: str) -> str:
        """Extract short core from normalized TOC title for matching."""
        core = re.sub(r'[（(].*$', '', norm_title).strip()
        # Strip common agency prefixes
        for prefix in ['中国银保监会人身险部关于印发', '中国银保监会办公厅关于印发',
                        '中国银保监会关于印发', '中国银保监会办公厅关于',
                        '中国银保监会关于', '中国银保监会',
                        '中国保监会关于印发', '中国保监会办公厅关于',
                        '中国保监会关于', '中国保监会',
                        '国家金融监督管理总局关于', '国家金融监督管理总局',
                        '最高人民法院']:
            if core.startswith(prefix):
                core = core[len(prefix):]
                break
        return core.strip()

    for gi, (gs, ge, gtext) in enumerate(groups):
        norm_g = _norm(gtext)
        norm_g_core = re.sub(r'[（(].*$', '', norm_g).strip()
        found = False
        for ti in range(toc_idx, len(toc_entries)):
            entry = toc_entries[ti]
            norm_t = _norm(entry.title)
            core = re.sub(r'[（(].*$', '', norm_t).strip()
            short_core = _short_core(norm_t)
            # Direct match: TOC core in group text
            if len(core) >= 6 and core in norm_g:
                matches.append((gs, ge, entry))
                toc_idx = ti + 1
                found = True
                break
            # Short core match (after removing agency prefix)
            if len(short_core) >= 4 and short_core in norm_g:
                matches.append((gs, ge, entry))
                toc_idx = ti + 1
                found = True
                break
            # Reverse match: group core in TOC core
            if len(norm_g_core) >= 6 and norm_g_core in core:
                matches.append((gs, ge, entry))
                toc_idx = ti + 1
                found = True
                break
        if not found:
            ch_num = 900 + gi
            matches.append((gs, ge, _TocEntry(chapter_num=ch_num, title=gtext[:80], section_name=section_name)))

    return matches


def _find_chapter_boundaries(
    paragraphs: List[_Paragraph], toc_entries: List[_TocEntry],
) -> List[Tuple[int, int, int, _TocEntry]]:
    body_start = None
    for p in paragraphs:
        if _is_section_header(p):
            body_start = p.index
            break
    if body_start is None:
        body_start = 182
    body_end = len(paragraphs)

    # Find section headers and build section ranges
    sec_pos: List[Tuple[str, int]] = []
    for p in paragraphs:
        if p.index < body_start:
            continue
        if _is_section_header(p):
            m = re.match(r'(第[一二三四五六七八九十]+部分)', p.text.strip())
            if m:
                sec_pos.append((m.group(1), p.index))

    sec_ranges: List[Tuple[str, int, int]] = []
    for i, (sn, sp) in enumerate(sec_pos):
        end = sec_pos[i + 1][1] if i + 1 < len(sec_pos) else body_end
        sec_ranges.append((sn, sp, end))

    toc_by_sec: Dict[str, List[_TocEntry]] = {}
    for e in toc_entries:
        toc_by_sec.setdefault(e.section_name, []).append(e)

    all_matches: List[Tuple[int, int, _TocEntry]] = []

    for sn, ss, se in sec_ranges:
        toc_sec = toc_by_sec.get(sn, [])

        # Start after section header
        groups = _collect_title_groups(paragraphs, ss + 1, se)
        groups = _filter_title_groups(groups, ss, paragraphs)
        groups = _deduplicate_groups(groups)

        if not groups:
            continue

        # Match groups to TOC entries
        matched = _match_to_toc(groups, toc_sec, sn)
        all_matches.extend(matched)

    all_matches.sort(key=lambda x: x[0])

    result: List[Tuple[int, int, int, _TocEntry]] = []
    for i, (start, title_end, entry) in enumerate(all_matches):
        end = all_matches[i + 1][0] if i + 1 < len(all_matches) else body_end
        result.append((start, title_end, end, entry))

    logger.info(f"Matched: {len(result)}/{len(toc_entries)}")
    return result


def _extract_chapter_text(
    paragraphs: List[_Paragraph], start_idx: int, end_idx: int, title_end_idx: int,
) -> str:
    body_paras = []
    for i in range(title_end_idx + 1, end_idx):
        if i >= len(paragraphs):
            break
        p = paragraphs[i]
        text = p.text.strip()
        if not text:
            continue
        if p.font_size in (16, 28) and re.match(r'^[-\s]*\d+[-\s]*$', text):
            continue
        body_paras.append(p)

    merged: List[str] = []
    for p in body_paras:
        text = p.text.strip()
        if not text:
            continue
        if merged and merged[-1][-1] not in _SENTENCE_ENDS:
            prev = merged[-1]
            if prev[-1] in '：:' and re.match(r'[（(]', text):
                merged.append(text)
            else:
                merged[-1] = prev + text
        else:
            merged.append(text)
    return '\n'.join(merged)


def _extract_articles(text: str) -> List[Tuple[int, str]]:
    pattern = re.compile(r'第([一二三四五六七八九十百零]+条)\s*')
    matches = list(pattern.finditer(text))
    if not matches:
        return [(1, text.strip())] if text.strip() else []
    articles = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        articles.append((i + 1, m.group(0) + content))
    return articles


def _extract_negative_list_items(text: str) -> List[Tuple[int, str]]:
    pattern = re.compile(r'[（(]\s*([一二三四五六七八九十百零]+)\s*[）)]')
    matches = list(pattern.finditer(text))
    if not matches:
        return [(1, text.strip())] if text.strip() else []
    items = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        items.append((i + 1, text[start:end].strip()))
    return items


def _safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*（）【】《》、，。！？；：""\'\'…—〔〕「」]', '', name)
    name = re.sub(r'\s*&\s*', '&', name)
    name = re.sub(r'[\s]+', '_', name)
    encoded = name.encode("utf-8")
    if len(encoded) > 240:
        encoded = encoded[:240]
        name = encoded.decode("utf-8", errors="ignore")
    return name.strip("_")


def _generate_frontmatter(collection: str, regulation: str, tags: List[str], parsed_info: Optional[dict] = None) -> str:
    import yaml
    insurance_type = ""
    if collection and collection not in _NON_INSURANCE_TYPE_DIRS and "_" in collection:
        insurance_type = collection.split("_", 1)[1]
    data = {"collection": collection, "regulation": regulation, "tags": tags}
    if insurance_type:
        data["险种类型"] = insurance_type
    if parsed_info:
        if parsed_info.get("agencies"):
            data["发文机关"] = parsed_info["agencies"]
        if parsed_info.get("doc_numbers"):
            data["文号"] = parsed_info["doc_numbers"]
        if parsed_info.get("extra_info"):
            data["备注"] = parsed_info["extra_info"]
    return "---\n" + yaml.dump(data, allow_unicode=True, default_flow_style=False) + "---\n"


def convert_docx_to_markdown(docx_path: str, output_dir: str, skip_llm: bool = False) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    logger.info("Parsing DOCX...")
    paragraphs = _extract_paragraphs(docx_path)
    logger.info(f"Extracted {len(paragraphs)} paragraphs")

    toc_entries = parse_toc(paragraphs)
    logger.info(f"TOC: {len(toc_entries)} chapters")

    boundaries = _find_chapter_boundaries(paragraphs, toc_entries)
    logger.info(f"Boundaries: {len(boundaries)}")

    chapters: List[_Chapter] = []
    for start, title_end, end, entry in boundaries:
        body_text = _extract_chapter_text(paragraphs, start, end, title_end)
        collection = _get_collection(entry.section_name)
        chapters.append(_Chapter(
            chapter_num=entry.chapter_num, title=entry.title,
            section_name=entry.section_name, collection=collection,
            body_text=body_text,
        ))

    parsed_map: Dict[str, dict] = {}
    if not skip_llm:
        from .excel_to_md import parse_regulation_names
        parsed_map = parse_regulation_names([ch.title for ch in chapters])
        logger.info(f"LLM parsed {len(parsed_map)}/{len(chapters)} names")

    for d in output_path.iterdir():
        if d.is_dir():
            shutil.rmtree(d)

    md_count = 0
    for ch in chapters:
        if not ch.body_text.strip():
            continue
        collection_dir = output_path / ch.collection
        collection_dir.mkdir(parents=True, exist_ok=True)

        parsed_info = parsed_map.get(ch.title)
        safe_name = parsed_info.get("short_name", ch.title) if parsed_info else ch.title
        from .excel_to_md import _simplify_regulation_name
        safe_name = _simplify_regulation_name(safe_name)
        safe_name = _safe_filename(safe_name)

        fm = _generate_frontmatter(ch.collection, ch.title, [ch.title], parsed_info)
        items = _extract_negative_list_items(ch.body_text) if ch.collection == "01_负面清单检查" else _extract_articles(ch.body_text)
        if not items:
            continue

        lines = [fm, f"# {ch.title}", ""]
        for seq, content in items:
            lines.append(f"## 第{seq}项")
            lines.append(content)
            lines.append("")
        md_path = collection_dir / f"{safe_name}.md"
        md_path.write_text("\n".join(lines), encoding="utf-8")
        md_count += 1
        logger.info(f"Generated: {md_path.relative_to(output_path)} ({len(items)} items)")

    logger.info(f"Done: {md_count} documents")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="DOCX regulation handbook -> Markdown KB")
    parser.add_argument("--input", required=True, help="DOCX file path")
    parser.add_argument("--output", default=None, help="Output directory")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM name parsing")
    args = parser.parse_args()

    output = args.output
    if not output:
        repo_root = Path(__file__).parent.parent.parent.parent.parent
        output = str(repo_root / "references")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    convert_docx_to_markdown(docx_path=args.input, output_dir=output, skip_llm=args.skip_llm)


if __name__ == "__main__":
    main()
