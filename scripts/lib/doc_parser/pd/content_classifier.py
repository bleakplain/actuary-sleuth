#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""混合内容分类器"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from ..models import SectionType

logger = logging.getLogger(__name__)

# 安全限制常量
MAX_INPUT_LENGTH = 10000  # 输入文本最大长度
MAX_CONTEXT_LENGTH = 5000  # 上下文最大长度
REGEX_TIMEOUT_SECONDS = 1  # 正则匹配超时（秒）


class DetectionMethod(str, Enum):
    """检测方法"""
    KEYWORD = "keyword"
    RULE = "rule"
    LLM = "llm"


@dataclass(frozen=True)
class DetectionResult:
    """检测结果"""
    section_type: SectionType
    confidence: float  # 0.0 - 1.0
    method: DetectionMethod
    reasoning: str = ""


class KeywordDetector:
    """关键词检测器"""

    def __init__(self, section_keywords: dict):
        self.section_keywords = section_keywords

    def detect(self, text: str) -> DetectionResult:
        """关键词匹配检测"""
        # 输入截断，防止超长输入
        text = text.strip()[:MAX_INPUT_LENGTH]

        for section_type in SectionType:
            if section_type == SectionType.CLAUSE:
                continue  # 条款是默认类型，不需要关键词匹配

            keywords = self.section_keywords.get(section_type.value, [])
            matched_keywords = [kw for kw in keywords if kw in text]

            if matched_keywords:
                # 匹配关键词数量影响置信度
                confidence = min(1.0, 0.5 + len(matched_keywords) * 0.25)
                return DetectionResult(
                    section_type=section_type,
                    confidence=confidence,
                    method=DetectionMethod.KEYWORD,
                    reasoning=f"匹配关键词: {', '.join(matched_keywords)}"
                )

        return DetectionResult(
            section_type=SectionType.CLAUSE,
            confidence=0.0,
            method=DetectionMethod.KEYWORD,
            reasoning="未匹配任何关键词"
        )


class RuleDetector:
    """规则检测器"""

    # 规则定义: (compiled_pattern, section_type, confidence)
    RULES = [
        # 责任免除规则
        (re.compile(r'责任免除.*?(?:意外|疾病|事故|伤害|治疗)', re.DOTALL), SectionType.EXCLUSION, 0.7),
        (re.compile(r'因下列原因.*?导致.*?保险人.*?不承担', re.DOTALL), SectionType.EXCLUSION, 0.8),

        # 健康告知规则
        (re.compile(r'健康告知[：:]\s*\n.*?(?:病史|手术|住院|疾病|体检)', re.DOTALL), SectionType.HEALTH_DISCLOSURE, 0.8),
        (re.compile(r'被保险人.*?(?:患有|曾患|正在接受)', re.DOTALL), SectionType.HEALTH_DISCLOSURE, 0.7),

        # 投保须知规则
        (re.compile(r'投保须知[：:]\s*\n.*?(?:责任|义务|权利)', re.DOTALL), SectionType.NOTICE, 0.7),
        (re.compile(r'请仔细阅读.*?(?:条款|说明)', re.DOTALL), SectionType.NOTICE, 0.6),

        # 附加险规则
        (re.compile(r'附加险.*?(?:保险责任|保险金额|保险费)', re.DOTALL), SectionType.RIDER, 0.7),
        (re.compile(r'主险.*?附加.*?险', re.DOTALL), SectionType.RIDER, 0.6),

        # 条款规则
        (re.compile(r'第[一二三四五六七八九十]+条[：:]\s*\n', re.DOTALL), SectionType.CLAUSE, 0.5),
        (re.compile(r'^\d+\.\d*\s+.+$', re.MULTILINE), SectionType.CLAUSE, 0.4),
    ]

    def detect(self, text: str, context: Optional[str] = None) -> DetectionResult:
        """规则匹配检测"""
        # 输入截断，防止超长输入
        text = text[:MAX_INPUT_LENGTH]
        if context:
            context = context[:MAX_CONTEXT_LENGTH]
        full_text = f"{context}\n{text}" if context else text

        best_match: Optional[SectionType] = None
        best_confidence = 0.0
        best_reasoning = ""

        for pattern, section_type, confidence in self.RULES:
            if pattern.search(full_text):
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = section_type
                    best_reasoning = f"匹配规则模式: {pattern.pattern[:30]}..."

        if best_match:
            return DetectionResult(
                section_type=best_match,
                confidence=best_confidence,
                method=DetectionMethod.RULE,
                reasoning=best_reasoning
            )

        return DetectionResult(
            section_type=SectionType.CLAUSE,
            confidence=0.0,
            method=DetectionMethod.RULE,
            reasoning="未匹配任何规则"
        )


class LLMDetector:
    """LLM 检测器"""

    PROMPT_TEMPLATE = """分析以下保险文档内容，判断其类型。仅返回 JSON 格式结果。

内容:
{content}

可选类型:
- clause: 普通条款
- premium_table: 费率表
- notice: 投保须知
- health_disclosure: 健康告知
- exclusion: 责任免除
- rider: 附加险

返回格式:
{"type": "类型", "confidence": 0.0-1.0, "reasoning": "判断理由"}
"""

    def __init__(self):
        self._llm = None

    def detect(self, text: str, context: Optional[str] = None) -> DetectionResult:
        """LLM 分类检测"""
        # 直接构建内容并截断，避免冗余截断
        content = f"{context}\n{text}" if context else text
        content = content[:500]  # LLM 输入限制

        prompt = self.PROMPT_TEMPLATE.format(content=content)

        try:
            llm = self._get_llm()
            response = llm.generate(prompt)

            # 解析 JSON 响应
            result = self._parse_json_response(response)

            if result:
                return DetectionResult(
                    section_type=SectionType(result["type"]),
                    confidence=float(result.get("confidence", 0.5)),
                    method=DetectionMethod.LLM,
                    reasoning=result.get("reasoning", "")
                )
        except Exception as e:
            logger.warning(f"LLM 检测失败: {e}")

        return DetectionResult(
            section_type=SectionType.CLAUSE,
            confidence=0.0,
            method=DetectionMethod.LLM,
            reasoning=f"LLM 检测失败"
        )

    def _get_llm(self):
        """延迟初始化 LLM 客户端"""
        if self._llm is None:
            from lib.llm import LLMClientFactory
            self._llm = LLMClientFactory.create_audit_llm()
        return self._llm

    @staticmethod
    def _parse_json_response(response: str) -> Optional[dict]:
        """从响应中提取 JSON"""
        # 尝试直接解析
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 块
        import re
        json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        return None


class ContentClassifier:
    """混合内容分类器

    三层检测策略：
    1. 关键词检测（快速）
    2. 规则检测（中等复杂度）
    3. LLM 检测（高准确度，低速度）
    """

    CONFIDENCE_THRESHOLD = 0.7
    LLM_FALLBACK_THRESHOLD = 0.5

    def __init__(
        self,
        section_keywords: Optional[dict] = None,
        llm_enabled: bool = False,
    ):
        """初始化分类器

        Args:
            section_keywords: 章节关键词配置，如果为 None 则使用默认配置
            llm_enabled: 是否启用 LLM 检测
        """
        if section_keywords is None:
            # 加载默认关键词配置，带错误处理
            from pathlib import Path
            config_path = Path(__file__).parent / 'data' / 'keywords.json'
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                section_keywords = config.get('section_keywords', {})
            except FileNotFoundError:
                logger.warning(f"关键词配置文件不存在: {config_path}，使用空配置")
                section_keywords = {}
            except json.JSONDecodeError as e:
                logger.warning(f"关键词配置文件 JSON 解析失败: {config_path}, {e}，使用空配置")
                section_keywords = {}

        self.llm_enabled = llm_enabled
        self._keyword_detector = KeywordDetector(section_keywords)
        self._rule_detector = RuleDetector()
        self._llm_detector: Optional[LLMDetector] = None

    def classify(
        self,
        text: str,
        context: Optional[str] = None,
    ) -> DetectionResult:
        """混合分类策略

        Args:
            text: 待分类文本
            context: 上下文文本（可选）

        Returns:
            检测结果，包含类型、置信度和检测方法
        """
        # 1. 关键词检测（快速）
        keyword_result = self._keyword_detector.detect(text)
        if keyword_result.confidence >= self.CONFIDENCE_THRESHOLD:
            return keyword_result

        # 2. 规则检测（中等复杂度）
        rule_result = self._rule_detector.detect(text, context)
        if rule_result.confidence >= self.CONFIDENCE_THRESHOLD:
            return rule_result

        # 3. LLM 检测（高准确度，低速度）
        if self.llm_enabled and rule_result.confidence < self.LLM_FALLBACK_THRESHOLD:
            llm_result = self._get_llm_detector().detect(text, context)
            if llm_result.confidence > 0:
                return llm_result

        # 4. 返回最高置信度结果
        results = [keyword_result, rule_result]
        return max(results, key=lambda r: r.confidence)

    def _get_llm_detector(self) -> LLMDetector:
        """延迟初始化 LLM 检测器"""
        if self._llm_detector is None:
            self._llm_detector = LLMDetector()
        return self._llm_detector
