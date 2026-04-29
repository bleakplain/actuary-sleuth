"""合规检查核心逻辑测试"""
import pytest
from unittest.mock import MagicMock, patch
from lib.compliance.checker import identify_category, build_enhanced_context


class TestIdentifyCategory:
    def test_keyword_match_health(self):
        """关键词匹配: 健康险"""
        result = identify_category("", "健康保险产品")
        assert result.category == "健康险"
        assert result.confidence == 0.7
        assert result.method == "keyword"

    def test_keyword_match_life(self):
        """关键词匹配: 寿险"""
        result = identify_category("", "终身寿险")
        assert result.category == "寿险"
        assert result.confidence == 0.7
        assert result.method == "keyword"

    def test_keyword_match_accident(self):
        """关键词匹配: 意外险"""
        result = identify_category("", "意外伤害保险")
        assert result.category == "意外险"
        assert result.confidence == 0.7
        assert result.method == "keyword"

    def test_keyword_match_travel(self):
        """关键词匹配: 旅游险"""
        result = identify_category("", "旅游保险")
        assert result.category == "旅游险"
        assert result.confidence == 0.7
        assert result.method == "keyword"

    def test_llm_fallback(self):
        """LLM fallback 识别"""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = "医疗险"
        with patch('lib.compliance.checker.classify_product') as mock_classify:
            from lib.common.product_types import ProductCategory
            mock_classify.return_value = ProductCategory.OTHER
            with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
                result = identify_category("某产品", "模糊描述")
                assert result.category == "医疗险"
                assert result.confidence == 0.85
                assert result.method == "llm"

    def test_both_fail(self):
        """双阶段都失败"""
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("fail")
        with patch('lib.compliance.checker.classify_product') as mock_classify:
            from lib.common.product_types import ProductCategory
            mock_classify.return_value = ProductCategory.OTHER
            with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
                result = identify_category("某产品", "模糊描述")
                assert result.category is None
                assert result.confidence == 0.0
                assert result.method == "unknown"


class TestBuildEnhancedContext:
    def test_engine_not_initialized(self):
        """RAG 引擎未初始化"""
        with patch('lib.compliance.checker.get_engine', return_value=None):
            context, sources = build_enhanced_context("健康险")
            assert context == ""
            assert sources == {"险种专属": [], "通用法规": []}

    def test_category_none(self):
        """category 为 None 时只加载通用法规"""
        mock_engine = MagicMock()
        mock_engine.search_by_metadata.return_value = [{
            "law_name": "保险法",
            "article_number": "第一条",
            "content": "测试",
            "doc_number": "",
            "issuing_authority": "",
            "effective_date": ""
        }]
        with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
            context, sources = build_enhanced_context(None)
            assert "通用法规" in sources

    def test_full_regulations_loaded(self):
        """验证全量法规加载"""
        mock_engine = MagicMock()
        mock_engine.search_by_metadata.return_value = [
            {
                "law_name": "健康保险管理办法",
                "article_number": f"第{i}条",
                "content": f"内容{i}",
                "doc_number": "",
                "issuing_authority": "",
                "effective_date": ""
            }
            for i in range(1, 51)
        ]
        with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
            context, sources = build_enhanced_context("健康险")
            assert "第1条" in context
            assert "第50条" in context
