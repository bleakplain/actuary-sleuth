#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 知识库质量评估脚本

使用方法:
    python evaluate_rag.py --mode retrieval    # 仅检索评估（快速，不需要 LLM）
    python evaluate_rag.py --mode generation   # 仅生成评估（需要 LLM）
    python evaluate_rag.py --mode full         # 完整评估（默认）
    python evaluate_rag.py --retrieval-only    # 快捷开关，等价于 --mode retrieval
    python evaluate_rag.py --export report.json
    python evaluate_rag.py --compare old.json
"""
import argparse
import json
import logging
import sys
import os
from datetime import datetime
from pathlib import Path

# 添加 scripts 目录到 Python 路径
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from lib.rag_engine import RAGEngine, RAGConfig
from lib.rag_engine.evaluator import (
    RetrievalEvaluator,
    GenerationEvaluator,
    GenerationEvalReport,
    RAGEvalReport,
    run_retrieval_evaluation,
)
from lib.rag_engine.eval_dataset import (
    EvalSample,
    QuestionType,
    create_default_eval_dataset,
    load_eval_dataset,
    DEFAULT_DATASET_PATH,
)
from lib.rag_engine.llamaindex_adapter import ClientLLMAdapter
from lib.llm import LLMClientFactory
from lib.llm.langchain_adapter import ChatAdapter, EmbeddingAdapter
from llama_index.core import Settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _ensure_env():
    """确保 ZHIPU_API_KEY 环境变量已设置"""
    if 'ZHIPU_API_KEY' not in os.environ:
        try:
            from dotenv import load_dotenv
            env_path = script_dir / '.env'
            if env_path.exists():
                load_dotenv(env_path)
        except ImportError:
            pass

    if 'ZHIPU_API_KEY' not in os.environ:
        try:
            from lib.common.config_validator import ConfigValidator
            api_key = ConfigValidator.require_api_key('ZHIPU_API_KEY', '智谱')
            os.environ['ZHIPU_API_KEY'] = api_key
        except Exception as e:
            logger.error(f"无法获取 API 密钥: {e}")
            sys.exit(1)


def setup_rag_engine(config: RAGConfig) -> 'RAGEngine':
    """创建 RAG 引擎（含 LLM + Embedding）"""
    _ensure_env()

    llm_client = LLMClientFactory.create_qa_llm()
    Settings.llm = ClientLLMAdapter(llm_client)
    Settings.embed_model = LLMClientFactory.create_embed_llm()

    logger.info("LLM 和 Embedding 模型设置完成")
    return RAGEngine(config)


def create_ragas_llm():
    """创建 RAGAS 评估用的 Langchain LLM"""
    _ensure_env()
    return ChatAdapter(client=LLMClientFactory.create_eval_llm())


def create_ragas_embeddings():
    """创建 RAGAS 评估用的 Langchain Embedding"""
    _ensure_env()
    return EmbeddingAdapter(LLMClientFactory.create_embed_llm())


def export_report(report: RAGEvalReport, output_path: str):
    """导出评估报告"""
    output_data = {
        'timestamp': datetime.now().isoformat(),
        'report': report.to_dict(),
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    logger.info(f"评估报告已导出到: {output_path}")


def load_report(path: str) -> RAGEvalReport:
    """从 JSON 文件加载评估报告"""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    report_data = data.get('report', data)
    retrieval_data = report_data.get('retrieval', {})
    generation_data = report_data.get('generation', {})

    return RAGEvalReport(
        retrieval=type('obj', (), {
            'precision_at_k': retrieval_data.get('precision_at_k', 0.0),
            'recall_at_k': retrieval_data.get('recall_at_k', 0.0),
            'mrr': retrieval_data.get('mrr', 0.0),
            'ndcg': retrieval_data.get('ndcg', 0.0),
            'redundancy_rate': retrieval_data.get('redundancy_rate', 0.0),
            'by_type': retrieval_data.get('by_type', {}),
        })(),
        generation=type('obj', (), {
            'faithfulness': generation_data.get('faithfulness'),
            'answer_relevancy': generation_data.get('answer_relevancy'),
            'answer_correctness': generation_data.get('answer_correctness'),
            'by_type': generation_data.get('by_type', {}),
        })(),
        total_samples=report_data.get('total_samples', 0),
        failed_samples=report_data.get('failed_samples', []),
    )


def compare_reports(report1: RAGEvalReport, report2: RAGEvalReport, label1: str = "Before", label2: str = "After"):
    """对比两个评估报告"""
    print("\n" + "=" * 70)
    print(f"评估对比: {label1} vs {label2}")
    print("=" * 70)

    # 检索指标对比
    retrieval_metrics = [
        ('precision_at_k', 'Precision@K'),
        ('recall_at_k', 'Recall@K'),
        ('mrr', 'MRR'),
        ('ndcg', 'NDCG'),
        ('redundancy_rate', '冗余率'),
    ]

    print("\n  检索指标:")
    for key, name in retrieval_metrics:
        v1 = getattr(report1.retrieval, key)
        v2 = getattr(report2.retrieval, key)

        diff = v2 - v1
        diff_pct = (diff / v1 * 100) if v1 > 0 else 0

        if diff > 0.01:
            arrow = "↑"
        elif diff < -0.01:
            arrow = "↓"
        else:
            arrow = "→"

        # 冗余率越低越好，其他指标越高越好
        if key == 'redundancy_rate':
            status = "+" if diff < 0 else ""
        else:
            status = "+" if diff > 0 else ""

        print(f"    {name:16} {label1}: {v1:.3f} | {label2}: {v2:.3f} | {arrow} {status}{abs(diff_pct):.1f}%")

    # 生成指标对比
    gen_metrics = [
        ('faithfulness', '忠实度'),
        ('answer_relevancy', '答案相关性'),
        ('answer_correctness', '答案正确性'),
    ]

    print("\n  生成指标:")
    for key, name in gen_metrics:
        v1 = getattr(report1.generation, key)
        v2 = getattr(report2.generation, key)

        if v1 is None or v2 is None:
            continue

        diff = v2 - v1
        diff_pct = (diff / v1 * 100) if v1 > 0 else 0

        if diff > 0.01:
            arrow = "↑"
        elif diff < -0.01:
            arrow = "↓"
        else:
            arrow = "→"

        status = "+" if diff > 0 else ""
        print(f"    {name:16} {label1}: {v1:.3f} | {label2}: {v2:.3f} | {arrow} {status}{abs(diff_pct):.1f}%")

    # 失败案例数对比
    print(f"\n  失败案例数: {label1}: {len(report1.failed_samples)} | {label2}: {len(report2.failed_samples)}")

    print("=" * 70 + "\n")


def detect_regressions(current_report: Dict, baseline_report: Dict) -> Dict[str, Any]:
    """检测指标退化

    Args:
        current_report: 当前评估报告（字典格式）
        baseline_report: 基线评估报告（字典格式）

    Returns:
        包含 passed, degradations, improvements 的字典
    """
    TOLERANCE = 0.02

    metrics_to_check = [
        ("recall@5", ["retrieval", "recall@5"]),
        ("faithfulness", ["generation", "faithfulness"]),
        ("answer_correctness", ["generation", "answer_correctness"]),
    ]

    degradations: List[Dict[str, Any]] = []
    improvements: List[Dict[str, Any]] = []

    for display_name, key_path in metrics_to_check:
        current_val: float = current_report
        baseline_val: float = baseline_report
        try:
            for key in key_path:
                current_val = current_val[key]
                baseline_val = baseline_val[key]
        except (KeyError, TypeError):
            continue

        delta = current_val - baseline_val
        if delta < -TOLERANCE:
            degradations.append({
                "metric": display_name,
                "baseline": baseline_val,
                "current": current_val,
                "delta": round(delta, 4),
            })
        elif delta > TOLERANCE:
            improvements.append({
                "metric": display_name,
                "baseline": baseline_val,
                "current": current_val,
                "delta": round(delta, 4),
            })

    return {
        "passed": len(degradations) == 0,
        "degradations": degradations,
        "improvements": improvements,
    }


def main():
    parser = argparse.ArgumentParser(
        description="RAG 知识库质量评估工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    %(prog)s --mode retrieval              # 仅检索评估
    %(prog)s --mode full                   # 完整评估
    %(prog)s --retrieval-only              # 快捷开关
    %(prog)s --export report.json          # 导出报告
    %(prog)s --export report.json --compare old.json  # 导出并对比
    %(prog)s --questions questions.json    # 自定义问题集
        """
    )

    parser.add_argument(
        '--mode',
        type=str,
        choices=['retrieval', 'generation', 'full'],
        default='full',
        help='评估模式: retrieval(仅检索)/generation(仅生成)/full(完整，默认)'
    )

    parser.add_argument(
        '--retrieval-only',
        action='store_true',
        help='仅进行检索评估（等价于 --mode retrieval）'
    )

    parser.add_argument(
        '--questions', '-q',
        type=str,
        help='自定义问题集 JSON 文件'
    )

    parser.add_argument(
        '--top-k',
        type=int,
        default=5,
        help='检索的文档数量（默认: 5）'
    )

    parser.add_argument(
        '--export',
        type=str,
        help='导出评估报告到指定文件'
    )

    parser.add_argument(
        '--compare',
        type=str,
        help='与之前的评估报告对比（指定 JSON 文件路径）'
    )

    parser.add_argument(
        '--chunking',
        type=str,
        choices=['semantic', 'fixed'],
        default='semantic',
        help='分块策略（默认: semantic）'
    )

    args = parser.parse_args()

    # 确定评估模式
    if args.retrieval_only:
        mode = 'retrieval'
    else:
        mode = args.mode

    # 加载评估数据
    if args.questions:
        samples = load_eval_dataset(args.questions)
        logger.info(f"加载自定义问题集: {len(samples)} 个问题")
    else:
        samples = create_default_eval_dataset()
        logger.info(f"使用默认评估集: {len(samples)} 个问题")

    # 创建 RAG 引擎（仅检索模式不需要 LLM，但仍需 embedding）
    config = RAGConfig(chunking_strategy=args.chunking)

    if mode in ('retrieval', 'full'):
        # 检索评估需要 embedding 模型
        rag_engine = setup_rag_engine(config)
        logger.info(f"RAG 引擎初始化完成（分块策略: {args.chunking}）")

        logger.info("开始检索评估...")
        retrieval_report, failed_samples = run_retrieval_evaluation(
            rag_engine, samples, top_k=args.top_k
        )

    if mode == 'generation' or (mode == 'full'):
        if mode == 'generation':
            rag_engine = setup_rag_engine(config)
            logger.info(f"RAG 引擎初始化完成（分块策略: {args.chunking}）")

        logger.info("开始生成评估...")
        ragas_llm = create_ragas_llm()
        ragas_embeddings = create_ragas_embeddings()
        gen_evaluator = GenerationEvaluator(rag_engine, llm=ragas_llm, embeddings=ragas_embeddings)
        generation_report = gen_evaluator.evaluate_batch(samples, rag_engine)
    else:
        generation_report = GenerationEvalReport()

    # 组装报告
    report = RAGEvalReport(
        retrieval=retrieval_report,
        generation=generation_report,
        total_samples=len(samples),
        failed_samples=failed_samples,
    )

    # 打印报告
    report.print_report()

    # 导出报告
    if args.export:
        export_report(report, args.export)

    # 对比报告
    if args.compare:
        old_report = load_report(args.compare)
        compare_reports(old_report, report, "Previous", "Current")

    # 返回退出码（基于检索召回率）
    if report.retrieval.recall_at_k >= 0.8:
        logger.info("检索评估结果: 优秀")
        return 0
    elif report.retrieval.recall_at_k >= 0.6:
        logger.info("检索评估结果: 良好")
        return 0
    else:
        logger.warning("检索评估结果: 需要改进")
        return 1


if __name__ == '__main__':
    sys.exit(main())
