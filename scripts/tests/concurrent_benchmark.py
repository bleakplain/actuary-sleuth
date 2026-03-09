#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
并发处理性能对比测试

对比串行处理 vs 并发处理的性能差异
"""
import sys
import os
# 添加 lib 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

import time
import asyncio
import logging
from typing import List, Dict


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockLLMClient:
    """模拟LLM客户端 - 用于测试"""

    def __init__(self, latency_range=(1.0, 3.0), rate_limit_probability=0.1):
        """
        Args:
            latency_range: (min, max) 模拟延迟范围（秒）
            rate_limit_probability: 模拟429概率
        """
        import random
        self.latency_range = latency_range
        self.rate_limit_prob = rate_limit_probability
        self.request_count = 0
        self.rate_limit_count = 0

    def generate(self, prompt: str, **kwargs) -> str:
        """模拟LLM调用"""
        import random
        import time

        self.request_count += 1

        # 模拟429限流
        if random.random() < self.rate_limit_prob:
            self.rate_limit_count += 1
            # 第一次请求可能429
            if self.request_count % 5 == 0:  # 每5个请求模拟一次429
                raise Exception("429 Rate limit exceeded")

        # 模拟处理延迟
        latency = random.uniform(*self.latency_range)
        time.sleep(latency)

        # 返回模拟JSON
        return '{"product_info": {"test": "value"}, "clauses": [], "pricing_params": {}}'


def simulate_serial_processing(
    chunks: List[str],
    mock_client: MockLLMClient
) -> tuple[List[Dict], float]:
    """模拟串行处理"""
    logger.info(f"=== 串行处理 {len(chunks)} 个chunks ===")
    start_time = time.time()

    results = []
    for i, chunk in enumerate(chunks):
        try:
            response = mock_client.generate(chunk)
            # 模拟解析
            import json
            result = json.loads(response) if response else {}
            results.append(result)
            logger.info(f"  [{i+1}/{len(chunks)}] 完成")

        except Exception as e:
            if '429' in str(e):
                # 串行处理的重试
                logger.warning(f"  [{i+1}/{len(chunks)}] 遇到429，2秒后重试...")
                time.sleep(2)
                response = mock_client.generate(chunk)
                import json
                result = json.loads(response) if response else {}
                results.append(result)
            else:
                results.append({})

    elapsed = time.time() - start_time
    logger.info(f"串行处理完成: {elapsed:.1f}秒")
    return results, elapsed


async def simulate_concurrent_processing(
    chunks: List[str],
    mock_client: MockLLMClient,
    max_concurrent: int = 3
):
    """模拟并发处理"""
    logger.info(f"=== 并发处理 {len(chunks)} 个chunks (并发数: {max_concurrent}) ===")

    from concurrent.futures import ThreadPoolExecutor

    async def process_chunk(index: int, chunk: str):
        semaphore = asyncio.Semaphore(max_concurrent)
        async with semaphore:
            loop = asyncio.get_event_loop()
            for attempt in range(3):
                try:
                    result = await loop.run_in_executor(
                        None,
                        mock_client.generate,
                        chunk
                    )
                    import json
                    parsed = json.loads(result) if result else {}
                    logger.info(f"  [{index+1}/{len(chunks)}] 完成")
                    return index, parsed
                except Exception as e:
                    if '429' in str(e) and attempt < 2:
                        wait = 2 ** attempt
                        logger.warning(f"  [{index+1}/{len(chunks)}] 429, {wait}s后重试...")
                        await asyncio.sleep(wait)
                    else:
                        return index, {}
            return index, {}

    start_time = time.time()

    tasks = [process_chunk(i, chunk) for i, chunk in enumerate(chunks)]
    completed = await asyncio.gather(*tasks)

    results = [None] * len(chunks)
    for idx, result in completed:
        results[idx] = result

    elapsed = time.time() - start_time
    logger.info(f"并发处理完成: {elapsed:.1f}秒")
    return results, elapsed


def generate_test_chunks(count: int, size_kb: int = 5) -> List[str]:
    """生成测试用的chunks"""
    # 每个chunk约 size_kb KB
    chunk_text = "测试内容。" * (size_kb * 1024 // 12)
    return [f"Chunk {i+1}\n{chunk_text}" for i in range(count)]


def run_comparison(
    chunk_count: int = 15,
    chunk_size_kb: int = 5,
    max_concurrent: int = 3
):
    """运行对比测试"""
    logger.info("=" * 60)
    logger.info(f"性能对比测试: {chunk_count} chunks × {chunk_size_kb}KB")
    logger.info("=" * 60)

    # 生成测试数据
    chunks = generate_test_chunks(chunk_count, chunk_size_kb)
    total_size = sum(len(c.encode('utf-8')) for c in chunks) / 1024
    logger.info(f"总文档大小: {total_size:.1f} KB\n")

    # 测试1: 串行处理
    mock_client_serial = MockLLMClient(latency_range=(1.0, 2.0))
    _, serial_time = simulate_serial_processing(chunks, mock_client_serial)

    # 测试2: 并发处理
    mock_client_concurrent = MockLLMClient(latency_range=(1.0, 2.0))
    _, concurrent_time = asyncio.run(simulate_concurrent_processing(
        chunks,
        mock_client_concurrent,
        max_concurrent
    ))

    # 结果对比
    logger.info("\n" + "=" * 60)
    logger.info("性能对比结果")
    logger.info("=" * 60)
    logger.info(f"串行处理耗时: {serial_time:.1f}秒")
    logger.info(f"并发处理耗时: {concurrent_time:.1f}秒")
    logger.info(f"加速比: {serial_time/concurrent_time:.2f}x")
    logger.info(f"时间节省: {(1 - concurrent_time/serial_time)*100:.1f}%")
    logger.info("=" * 60)

    return {
        'serial_time': serial_time,
        'concurrent_time': concurrent_time,
        'speedup': serial_time / concurrent_time,
        'time_saved_percent': (1 - concurrent_time / serial_time) * 100
    }


def demonstrate_rate_limiting():
    """演示429限流处理"""
    logger.info("\n" + "=" * 60)
    logger.info("429限流处理演示")
    logger.info("=" * 60)

    from extraction.concurrent_processor import RateLimitConfig, TokenBucketLimiter, ConcurrentLLMProcessor

    # 测试令牌桶
    bucket = TokenBucketLimiter(rate=2.0, capacity=5)  # 2请求/秒，容量5

    async def test_token_bucket():
        logger.info("\n--- 令牌桶测试 (2 req/s, 容量5) ---")
        start = time.time()

        # 前5个请求应该立即通过
        for i in range(5):
            await bucket.acquire()
            logger.info(f"请求 {i+1}: 立即通过")

        # 第6个请求需要等待令牌补充
        logger.info("请求 6: 等待令牌...")
        await bucket.acquire()
        elapsed = time.time() - start
        logger.info(f"请求 6: 通过 (总耗时 {elapsed:.1f}s)")

        # 连续请求测试速率限制
        logger.info("\n连续10个请求测试:")
        start = time.time()
        for i in range(10):
            await bucket.acquire()
            logger.info(f"  请求 {i+1}: {(time.time()-start):.1f}s")

    asyncio.run(test_token_bucket())

    # 测试并发处理器
    logger.info("\n--- 并发处理器测试 ---")

    async def test_concurrent_processor():
        processor = ConcurrentLLMProcessor(
            rate_limit=RateLimitConfig(
                max_concurrent=3,
                min_delay=0.3,
                burst_size=5
            )
        )

        def mock_process(chunk, index, total):
            # 模拟处理时间
            time.sleep(0.5)
            if index == 2:  # 模拟第3个请求429
                raise Exception("429 Rate limit exceeded")
            return {"index": index, "data": "test"}

        chunks = ["chunk"] * 8
        results = await processor.process_chunks(chunks, mock_process)

        logger.info(f"处理完成: {len([r for r in results if r])}/{len(results)} 成功")
        processor.close()

    asyncio.run(test_concurrent_processor())


if __name__ == '__main__':
    # 运行性能对比
    results = run_comparison(
        chunk_count=15,
        chunk_size_kb=5,
        max_concurrent=3
    )

    # 演示限流处理
    demonstrate_rate_limiting()

    # 输出结论
    logger.info("\n" + "=" * 60)
    logger.info("结论")
    logger.info("=" * 60)
    if results['speedup'] > 2.0:
        logger.info("✓ 并发处理显著优于串行处理 (加速比 > 2x)")
        logger.info("✓ 建议：在处理长文档时使用并发模式")
    elif results['speedup'] > 1.5:
        logger.info("✓ 并发处理优于串行处理 (加速比 > 1.5x)")
    else:
        logger.info("⚠ 加速比不明显，可能需要调整并发数")

    logger.info(f"\n推荐配置:")
    logger.info(f"  - 智谱 glm-4-flash: 并发数=5, 间隔=0.3s")
    logger.info(f"  - 智谱 glm-4-air: 并发数=3, 间隔=0.5s")
    logger.info(f"  - 智谱 glm-4-plus: 并发数=2, 间隔=1.0s")
