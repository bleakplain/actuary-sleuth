"""缓存历史指标采集器"""
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Callable

from lib.common.database import get_connection

logger = logging.getLogger(__name__)

# 采样间隔（秒）
SAMPLE_INTERVAL = 60
# 保留天数
RETENTION_DAYS = 7


@dataclass(frozen=True)
class CacheTrendPoint:
    timestamp: str
    hits: int
    misses: int
    hit_rate: float
    memory_size: int
    evictions: int = 0
    l2_size: int = 0


class CacheMetricsCollector:
    """缓存指标定时采集器。

    在后台线程中定时采集缓存统计，写入 cache_metrics_history 表。
    """

    def __init__(self, cache_manager_getter: Callable, interval: int = SAMPLE_INTERVAL):
        """初始化采集器。

        Args:
            cache_manager_getter: 获取 CacheManager 实例的函数
            interval: 采样间隔（秒）
        """
        self._get_cache = cache_manager_getter
        self._interval = interval
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """启动采集线程。"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(f"缓存指标采集器已启动，间隔 {self._interval}s")

    def stop(self) -> None:
        """停止采集线程。"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        """采集线程主循环。"""
        while self._running:
            try:
                self._collect_and_save()
            except Exception as e:
                logger.warning(f"指标采集失败: {e}")
            time.sleep(self._interval)

    def _collect_and_save(self) -> None:
        """采集并保存指标。"""
        cache = self._get_cache()
        if cache is None:
            return

        stats = cache.get_stats()
        now = datetime.now(timezone.utc).isoformat()

        scope_metrics = {
            s: {"hits": s_stats.hits, "misses": s_stats.misses}
            for s, s_stats in stats.by_scope.items()
        }

        with get_connection() as conn:
            conn.execute(
                """INSERT INTO cache_metrics_history
                   (timestamp, hits, misses, hit_rate, memory_size, evictions, l2_size, namespace_metrics_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    now,
                    stats.hits,
                    stats.misses,
                    stats.hit_rate,
                    stats.memory_size,
                    stats.evictions,
                    stats.l2_size,
                    json.dumps(scope_metrics, ensure_ascii=False),
                )
            )
            cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
            conn.execute("DELETE FROM cache_metrics_history WHERE timestamp < ?", (cutoff,))

    @staticmethod
    def query_trend(range_hours: int = 24) -> List[CacheTrendPoint]:
        """查询历史趋势数据。

        Args:
            range_hours: 时间范围（小时）

        Returns:
            数据点列表
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=range_hours)).isoformat()
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT timestamp, hits, misses, hit_rate, memory_size, evictions, l2_size
                   FROM cache_metrics_history
                   WHERE timestamp >= ?
                   ORDER BY timestamp ASC""",
                (cutoff,)
            ).fetchall()
            return [
                CacheTrendPoint(
                    timestamp=row[0],
                    hits=row[1],
                    misses=row[2],
                    hit_rate=row[3],
                    memory_size=row[4],
                    evictions=row[5],
                    l2_size=row[6],
                )
                for row in rows
            ]


# 全局采集器实例
_collector: Optional[CacheMetricsCollector] = None


def start_metrics_collector(cache_manager_getter: Callable) -> None:
    """启动指标采集器。

    Args:
        cache_manager_getter: 获取 CacheManager 实例的函数
    """
    global _collector
    if _collector is None:
        _collector = CacheMetricsCollector(cache_manager_getter)
        _collector.start()


def stop_metrics_collector() -> None:
    """停止指标采集器。"""
    global _collector
    if _collector:
        _collector.stop()
        _collector = None


def get_cache_trend(range_hours: int = 24) -> List[CacheTrendPoint]:
    """获取缓存历史趋势。

    Args:
        range_hours: 时间范围（小时）

    Returns:
        数据点列表
    """
    return CacheMetricsCollector.query_trend(range_hours)
