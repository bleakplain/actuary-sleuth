"""评测样本自动合成 pipeline — 从知识库 Chunk 生成候选问答对。"""
import json
import logging
import uuid
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from .eval_dataset import EvalSample, QuestionType, ReviewStatus, save_eval_dataset, RegulationRef

logger = logging.getLogger(__name__)

_SYNTH_PROMPT = """你是一个保险监管法规领域的专家。根据以下法规条款内容，生成 2-3 个保险精算审核人员可能会问的问题。

要求：
1. 问题必须是保险产品审核相关（条款、定价、免责、等待期等），不涉及公司运营
2. 问题应该多样化：事实查询、对比分析、边界条件
3. 每个问题的答案必须完全来自提供的条款内容，不得编造
4. 引用条目（article）必须是答案所依据的具体条款编号，如"第十三条"、"第1项"等

法规条款内容：
{chunk_text}

请以 JSON 数组格式返回，每个元素包含：
- "question": 问题文本
- "answer": 答案文本（基于条款内容）
- "keywords": 2-3 个关键词
- "topic": 所属主题
- "difficulty": "easy"/"medium"/"hard"
- "article": 答案所依据的条款编号（如"第十三条"）
- "excerpt": 答案依据的条款原文摘要（不超过100字）

仅输出 JSON 数组，不要输出其他内容。"""


@dataclass(frozen=True)
class SynthConfig:
    min_answer_length: int = 20
    kb_version: str = ""


@dataclass
class SynthResult:
    """合成 pipeline 中间结果，在 synthesize() 中逐步累积。非 frozen 以支持增量更新。"""
    total_chunks: int = 0
    processed_chunks: int = 0
    generated_samples: int = 0
    filtered_samples: int = 0
    failed_chunks: int = 0
    samples: List[EvalSample] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_chunks': self.total_chunks,
            'processed_chunks': self.processed_chunks,
            'generated_samples': self.generated_samples,
            'filtered_samples': self.filtered_samples,
            'failed_chunks': self.failed_chunks,
            'samples': [s.to_dict() for s in self.samples],
            'errors': self.errors,
        }


class SynthQA:

    def __init__(self, config: Optional[SynthConfig] = None):
        self.config = config or SynthConfig()

    def load_chunks(self) -> List[Dict[str, Any]]:
        import lancedb
        from .kb_manager import KBManager

        kb_mgr = KBManager()
        paths = kb_mgr.get_active_paths()
        if not paths:
            raise ValueError("无活跃知识库版本")

        db = lancedb.connect(paths["vector_db_path"])
        table = db.open_table("regulations_vectors")
        df = table.to_pandas()

        chunks: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            text = row.get("text", "")
            metadata = row.get("metadata", {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    metadata = {}

            source_file = metadata.get("file_name", metadata.get("source_file", ""))

            if not text or len(text.strip()) < 50:
                continue

            chunks.append({
                "text": text,
                "source_file": source_file,
                "metadata": metadata,
            })

        logger.info(f"加载 {len(chunks)} 个有效 Chunk")
        return chunks

    def _generate_for_chunk(self, chunk: Dict[str, Any]) -> List[Dict]:
        from lib.llm.factory import LLMClientFactory

        llm = LLMClientFactory.create_qa_llm()
        prompt = _SYNTH_PROMPT.format(chunk_text=chunk["text"][:3000])

        try:
            response = llm.generate(prompt)
            items = self._parse_response(response)
            metadata = chunk.get("metadata", {})
            for item in items:
                item["_chunk_law_name"] = metadata.get("law_name", "")
                item["_chunk_source_file"] = chunk.get("source_file", "")
                item["_chunk_article_number"] = metadata.get("article_number", "")
            return items
        except Exception as e:
            logger.warning(f"Chunk 合成失败: {e}")
            return []

    def _parse_response(self, response: str) -> List[Dict]:
        from lib.doc_parser.kb.converter.excel_to_md import extract_json_array

        json_str = extract_json_array(response)
        if json_str is None:
            logger.warning("LLM 返回中未找到 JSON 数组，跳过")
            return []
        try:
            items = json.loads(json_str)
            if isinstance(items, list):
                return items
            return []
        except json.JSONDecodeError:
            logger.warning("LLM 返回 JSON 解析失败，跳过")
            return []

    def _filter_samples(
        self,
        candidates: List[EvalSample],
        existing: List[EvalSample],
    ) -> List[EvalSample]:
        filtered: List[EvalSample] = []
        existing_questions = {s.question for s in existing}

        for sample in candidates:
            if len(sample.ground_truth) < self.config.min_answer_length:
                continue
            if sample.question in existing_questions:
                continue
            if not any(kw in sample.ground_truth for kw in sample.evidence_keywords if len(kw) >= 2):
                continue

            existing_questions.add(sample.question)
            filtered.append(sample)

        return filtered

    def synthesize(
        self,
        chunks: Optional[List[Dict[str, Any]]] = None,
        existing_samples: Optional[List[EvalSample]] = None,
        save_interval: int = 10,
        save_fn=None,
        progress_callback=None,
    ) -> SynthResult:
        if chunks is None:
            chunks = self.load_chunks()

        existing = existing_samples or []
        result = SynthResult(total_chunks=len(chunks))

        for i, chunk in enumerate(chunks):
            result.processed_chunks += 1
            items = self._generate_for_chunk(chunk)

            if not items:
                result.failed_chunks += 1
                if progress_callback:
                    progress_callback(result, i + 1, len(chunks))
                continue

            source_file = chunk.get("source_file", "")
            candidates: List[EvalSample] = []
            for item in items:
                try:
                    article = item.get("article", "")
                    excerpt = item.get("excerpt", "")
                    refs = []
                    if article or excerpt:
                        refs.append(RegulationRef(
                            doc_name=item.get("_chunk_law_name", source_file),
                            article=article,
                            excerpt=excerpt,
                        ))
                    sample = EvalSample(
                        id=f"synth_{uuid.uuid4().hex[:8]}",
                        question=item["question"],
                        ground_truth=item["answer"],
                        evidence_docs=[source_file] if source_file else [],
                        evidence_keywords=item.get("keywords", []),
                        question_type=QuestionType.FACTUAL,
                        difficulty=item.get("difficulty", "medium"),
                        topic=item.get("topic", ""),
                        regulation_refs=refs,
                        created_by="llm",
                        review_status=ReviewStatus.PENDING,
                        kb_version=self.config.kb_version,
                    )
                    candidates.append(sample)
                    result.generated_samples += 1
                except (KeyError, TypeError) as e:
                    result.errors.append(f"字段解析失败: {e}")

            before_filter = len(candidates)
            filtered = self._filter_samples(candidates, existing)
            result.filtered_samples += before_filter - len(filtered)

            result.samples.extend(filtered)
            existing.extend(filtered)

            if progress_callback:
                progress_callback(result, i + 1, len(chunks))

            if save_fn and (i + 1) % save_interval == 0:
                saved_count = save_fn(result.samples)
                logger.info(
                    f"[{i + 1}/{len(chunks)}] 渐进保存 {saved_count} 条，"
                    f"累计有效 {len(result.samples)}，失败 {result.failed_chunks}"
                )

        logger.info(
            f"合成完成: {result.processed_chunks} chunks, "
            f"{len(result.samples)} 有效样本, "
            f"{result.filtered_samples} 过滤, "
            f"{result.failed_chunks} 失败"
        )
        return result
