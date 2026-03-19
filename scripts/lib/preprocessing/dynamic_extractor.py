#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态提取器

用于动态通道的完整提取，使用动态 Prompt 和专用提取器。
支持大文件分块处理。
"""
import json
import logging
import re
from typing import Dict, List, Any, Optional

from .models import NormalizedDocument, ExtractResult
from .classifier import ProductClassifier
from .prompt_builder import PromptBuilder
from .product_types import get_extraction_focus, get_output_schema
from .utils.json_parser import parse_llm_json_response
from .utils.constants import config


logger = logging.getLogger(__name__)


class PremiumTableExtractor:
    """费率表专用提取器"""

    TABLE_PROMPT = """你是保险费率表提取专家。

**任务**: 从以下表格内容中提取结构化数据。

**要求**:
1. 识别表格的列名和单位
2. 提取所有数据行
3. 识别费率的计算方式

**输出格式** (JSON):
{{
    "headers": ["年龄", "性别", "费率"],
    "units": {{"age": "岁", "rate": "元/份"}},
    "data": [
        {{"age": "0", "gender": "男", "rate": 1200}},
        {{"age": "0", "gender": "女", "rate": 1100}}
    ]
}}

表格内容:
{table_content}
"""

    def __init__(self, llm_client):
        self.llm_client = llm_client

    def extract(self, content: str) -> Dict[str, Any]:
        """提取费率表"""
        prompt = self.TABLE_PROMPT.format(
            table_content=content[:config.TABLE_CONTENT_MAX_CHARS]
        )

        try:
            response = self.llm_client.generate(
                prompt,
                max_tokens=config.TABLE_EXTRACTION_MAX_TOKENS,
                temperature=0.1
            )
            return parse_llm_json_response(response)
        except Exception as e:
            logger.warning(f"费率表提取失败: {e}")
            return {}


class ClauseExtractor:
    """条款专用提取器 - 自适应动态提取"""

    def __init__(self, llm_client):
        self.llm_client = llm_client

    def _analyze_structure(self, content: str) -> Dict[str, Any]:
        """分析文档结构，返回特征信息"""
        # 采样分析（前 5000 字符）
        sample = content[:5000]

        # 检测各种可能的条款编号模式
        patterns = {
            'html_bold_number': r'\*\*\d+\.\d+\*\*',
            'chapter_dot': r'第[一二三四五六七八九十\d]+\s*章',
            'clause_number': r'第[一二三四五六七八九十\d]+\s*条',
            'decimal_number': r'^\d+\.\d+\s',
            'parenthesis_number': r'^\d+\)',
            'chinese_number': r'[一二三四五六七八九十]+、',
        }

        detected = {}
        for name, pattern in patterns.items():
            matches = re.findall(pattern, sample, re.MULTILINE)
            if matches:
                detected[name] = len(matches)

        # 检测 HTML 表格
        has_table = '<table>' in content or '<tr>' in content

        # 检测章节标题
        headings = re.findall(r'^#{1,3}\s+.+$', sample, re.MULTILINE)

        return {
            'detected_patterns': detected,
            'has_table': has_table,
            'has_headings': len(headings) > 0,
            'total_length': len(content)
        }

    def _build_prompt(self, content: str, structure: Dict[str, Any]) -> str:
        """动态构建提取 Prompt"""
        detected = structure['detected_patterns']

        # 构建格式说明
        format_desc = []
        if 'html_bold_number' in detected:
            format_desc.append(f"- HTML 表格中的粗体数字编号（如 **2.1**），检测到约 {detected['html_bold_number']} 处")
        if 'chapter_dot' in detected:
            format_desc.append(f"- 章节格式（如 第一章、第1章），检测到约 {detected['chapter_dot']} 处")
        if 'clause_number' in detected:
            format_desc.append(f"- 条款格式（如 第一条、第1条），检测到约 {detected['clause_number']} 处")
        if 'decimal_number' in detected:
            format_desc.append(f"- 小数点编号（如 1.1、2.3），检测到约 {detected['decimal_number']} 处")
        if 'parenthesis_number' in detected:
            format_desc.append(f"- 括号编号（如 1)、2)），检测到约 {detected['parenthesis_number']} 处")

        format_info = "检测到的条款格式模式：\n" + "\n".join(format_desc) if format_desc else "未检测到明确的条款编号模式，请根据文档结构自行识别"

        # 计算需要的输出规模
        estimated_clauses = sum(detected.values()) if detected else 50
        size_note = f"\n\n**注意**: 文档共 {structure['total_length']} 字符，预计包含约 {estimated_clauses} 个条款项，请确保提取完整，不要遗漏。" if structure['total_length'] > 10000 else ""

        # HTML 表格特殊处理说明
        table_note = ""
        if structure.get('has_table') and 'html_bold_number' in detected:
            table_note = """

**HTML 表格格式解析说明**:
文档包含 HTML 表格格式的条款，条款格式如下：
- <td>**2.1**</td><td>**保险期间** 本合同保险期间为终身。</td>
- 条款编号 **2.1** 在一个 <td> 中，标题和内容在另一个 <td> 中
- 请忽略 HTML 标签，专注于提取 **数字.数字** 格式的条款编号及其后的标题和内容
- 每个 **数字.数字** 格式都是一个独立的条款，必须全部提取
"""

        return f"""你是保险条款提取专家，能够自适应识别各种文档格式的条款结构。

**任务**: 从保险产品文档中提取所有条款内容。

{format_info}{size_note}{table_note}

**提取要求**:
1. **完整性优先**: 必须提取文档中的所有条款，不要遗漏任何一项
2. **保持结构**: 保留条款的编号、标题和完整内容
3. **层级识别**: 正确识别章节、条款、子条款的层级关系
4. **内容完整**: 条款内容要包含所有细节、条件和说明
5. **逐一提取**: 对文档中的每个 **数字.数字** 格式编号，都要提取对应的条款，不要跳过

**过滤规则**（不要提取这些内容）:
- 阅读指引、投保须知、提示说明、客户服务信息等非条款内容
- 目录、索引、附录
- 附表、费率表（除非是条款的一部分）
- 页眉、页脚、页码等格式信息
- 联系方式、公司地址等行政信息

**输出格式** (JSON):
{{
    "clauses": [
        {{
            "number": "条款编号（如 2.3, 第一条, 1.1 等）",
            "title": "条款标题（如果有）",
            "text": "条款的完整文本内容"
        }}
    ]
}}

**重要**:
- 输出必须是纯 JSON 格式，不要使用 markdown 代码块
- 如果某个条款只有编号没有标题，title 字段留空或使用编号
- 确保所有条款都被提取，不要在文档中间停止

文档内容:
{content}
"""

    def extract(self, content: str) -> List[Dict[str, Any]]:
        """提取条款 - 自适应版本"""
        # 分析文档结构
        structure = self._analyze_structure(content)
        logger.info(f"文档结构分析: {structure}")

        # 根据文档大小和结构决定参数
        content_length = len(content)
        detected_count = sum(structure['detected_patterns'].values())

        # 动态调整参数 - 基于检测到的条款数量和文档长度
        if content_length > 30000 or detected_count > 30:
            max_chars = min(content_length, 60000)
            max_tokens = 16000
        elif content_length > 15000 or detected_count > 15:
            max_chars = min(content_length, 40000)
            max_tokens = 12000
        else:
            max_chars = config.CLAUSE_CONTENT_MAX_CHARS
            max_tokens = config.CLAUSE_EXTRACTION_MAX_TOKENS

        # 构建 Prompt
        prompt = self._build_prompt(content[:max_chars], structure)

        try:
            response = self.llm_client.generate(
                prompt,
                max_tokens=max_tokens,
                temperature=0.1
            )
            result = parse_llm_json_response(response)
            clauses = result.get('clauses', [])
            logger.info(f"条款提取完成: 提取到 {len(clauses)} 个条款")
            return clauses
        except Exception as e:
            logger.warning(f"条款提取失败: {e}")
            return []


class DynamicExtractor:
    """动态提取器 - 支持大文件自动分块处理"""

    def __init__(self, llm_client, classifier: ProductClassifier):
        self.llm_client = llm_client
        self.classifier = classifier
        self.prompt_builder = PromptBuilder()
        self.specialized_extractors = {
            config.EXTRACTOR_PREMIUM_TABLE: PremiumTableExtractor(llm_client),
            config.EXTRACTOR_CLAUSES: ClauseExtractor(llm_client),
        }

    def extract(self,
                document: NormalizedDocument,
                required_fields: List[str]) -> ExtractResult:
        """结构化提取"""

        # 1. 获取产品类型信息（一次性分类，避免重复）
        classifications = self.classifier.classify(document.content)
        product_type = classifications[0][0] if classifications else 'life_insurance'
        is_hybrid = len(classifications) > 1 and classifications[1][1] > config.HYBRID_PRODUCT_THRESHOLD

        # 2. 构建 Prompt
        prompt = self.prompt_builder.build(
            product_type=product_type,
            required_fields=required_fields,
            extraction_focus=get_extraction_focus(product_type),
            output_schema=get_output_schema(product_type),
            is_hybrid=is_hybrid
        )

        # 3. 执行提取（自动判断是否分块）
        content_length = len(document.content)
        if content_length > config.DYNAMIC_CONTENT_MAX_CHARS:
            logger.info(f"文档较大 ({content_length} 字符)，使用分块提取")
            result = self._extract_chunked(document, prompt)
        else:
            result = self._extract_single(document, prompt)

        # 4. 专用提取器（按需）
        if config.EXTRACTOR_PREMIUM_TABLE in required_fields or 'pricing_params' in required_fields:
            if document.profile.has_premium_table:
                premium_result = self.specialized_extractors[config.EXTRACTOR_PREMIUM_TABLE].extract(
                    document.content
                )
                if premium_result:
                    result[config.EXTRACTOR_PREMIUM_TABLE] = premium_result

        if config.EXTRACTOR_CLAUSES in required_fields:
            clause_result = self.specialized_extractors[config.EXTRACTOR_CLAUSES].extract(
                document.content
            )
            if clause_result:
                result[config.EXTRACTOR_CLAUSES] = clause_result

        return ExtractResult(
            data=result,
            confidence={k: config.DEFAULT_DYNAMIC_CONFIDENCE for k in result},
            provenance={k: config.PROVENANCE_DYNAMIC_LLM for k in result},
            metadata={
                config.EXTRACTION_MODE: 'dynamic',
                config.PRODUCT_TYPE: product_type,
                config.IS_HYBRID: is_hybrid,
                'content_length': content_length
            }
        )

    def _extract_single(self, document: NormalizedDocument, prompt: str) -> Dict[str, Any]:
        """单次提取（标准文档）"""
        full_prompt = f"{prompt}\n\n文档内容:\n{document.content}"

        try:
            response = self.llm_client.generate(
                full_prompt,
                max_tokens=config.DYNAMIC_EXTRACTION_MAX_TOKENS,
                temperature=0.1
            )
            return parse_llm_json_response(response)

        except Exception as e:
            logger.error(f"动态提取失败: {e}")
            return {}

    def _extract_chunked(self, document: NormalizedDocument, base_prompt: str) -> Dict[str, Any]:
        """分块提取（大文档）"""
        content = document.content
        chunk_size = config.DYNAMIC_CONTENT_MAX_CHARS
        overlap = 1000  # 块之间重叠 1000 字符以保持上下文

        # 检测是否需要大量 token（如提取条款）
        # 检测文档中的条款数量
        clause_patterns = [
            r'\*\*\d+\.\d+\*\*',  # HTML 表格格式
            r'第[一二三四五六七八九十\d]+\s*条',  # 标准格式
            r'\d+\.\d+\s',  # 小数点格式
        ]
        estimated_clauses = sum(len(re.findall(p, content)) for p in clause_patterns)

        # 根据条款数量调整 token 限制
        if estimated_clauses > 50:
            max_tokens = getattr(config, 'DYNAMIC_EXTRACTION_MAX_TOKENS_LARGE', 16000)
            logger.info(f"检测到约 {estimated_clauses} 个条款，使用高 token 限制: {max_tokens}")
        else:
            max_tokens = config.DYNAMIC_EXTRACTION_MAX_TOKENS

        # 分块
        chunks = []
        start = 0
        while start < len(content):
            end = start + chunk_size
            chunks.append(content[start:end])
            start = end - overlap if end < len(content) else end

        logger.info(f"文档分为 {len(chunks)} 块进行处理")

        # 第一块：完整提取
        first_prompt = f"{base_prompt}\n\n文档内容:\n{chunks[0]}"
        try:
            response = self.llm_client.generate(
                first_prompt,
                max_tokens=max_tokens,
                temperature=0.1
            )
            result = parse_llm_json_response(response)
            logger.info(f"第 1/{len(chunks)} 块提取完成，得到 {len(result)} 个字段")
            if 'clauses' in result:
                logger.info(f"  提取到 {len(result.get('clauses', []))} 个条款")
        except Exception as e:
            logger.error(f"第 1 块提取失败: {e}")
            result = {}

        # 后续块：补充提取
        for i, chunk in enumerate(chunks[1:], 1):
            # 统计已有条款数
            existing_clause_count = len(result.get('clauses', []))

            supplement_prompt = f"""你是保险产品信息提取专家。

**任务**: 从以下文档片段中补充提取信息。

**已有提取结果**:
```json
{json.dumps(result, ensure_ascii=False, indent=2)}
```

已有条款数: {existing_clause_count} 条

**新文档片段**:
{chunk}

**要求**:
1. **特别关注条款**: 继续从新片段中提取所有条款，添加到 clauses 列表中
2. 对条款列表使用追加模式，不要替换已有条款
3. 只提取已有结果中缺失的字段
4. 如果已有字段的值不完整，用新信息补充
5. 输出格式为 JSON，只包含新增或更新的字段

**输出格式** (JSON):
{{}}
"""

            try:
                response = self.llm_client.generate(
                    supplement_prompt,
                    max_tokens=max_tokens,  # 使用相同的高 token 限制
                    temperature=0.1
                )
                chunk_result = parse_llm_json_response(response)

                # 合并前记录条款数
                before_clause_count = len(result.get('clauses', []))

                # 合并结果
                for key, value in chunk_result.items():
                    if key not in result:
                        result[key] = value
                    elif isinstance(value, dict) and isinstance(result.get(key), dict):
                        result[key].update(value)
                    elif key == 'clauses' and isinstance(value, list) and isinstance(result.get(key), list):
                        # 条款去重：基于 number 字段，如果没有 number 则跳过
                        existing_numbers = {c.get('number') for c in result[key] if c.get('number')}
                        for item in value:
                            item_number = item.get('number')
                            # 只添加有编号且不重复的条款
                            if item_number and item_number not in existing_numbers:
                                result[key].append(item)
                                existing_numbers.add(item_number)
                    elif isinstance(value, list) and isinstance(result.get(key), list):
                        # 其他列表的简单合并
                        for item in value:
                            if item not in result[key]:
                                result[key].append(item)

                after_clause_count = len(result.get('clauses', []))
                logger.info(f"第 {i+1}/{len(chunks)} 块提取完成，条款数: {before_clause_count} -> {after_clause_count}")

            except Exception as e:
                logger.warning(f"第 {i+1} 块提取失败: {e}")
                continue

        logger.info(f"分块提取完成，共 {len(chunks)} 块，得到 {len(result)} 个字段")
        return result
