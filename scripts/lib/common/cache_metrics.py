"""缓存历史指标采集器"""
import json
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Callable

from lib.common.database import get_connection

logger = logging.getLogger(__name__)

SAMPLE_INTERVAL = 60  # 采样间隔（秒）
RETENTION_DAYS = 7    # 保留天数


class CacheMetricsCollector:
    """缓存指标定时采集器"""

    def __init__(self, cache_manager_getter: Callable[[], Any], interval: int = SAMPLE_INTERVAL):
        self._get_cache = cache_manager_getter
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(f"缓存指标采集器已启动，间隔 {self._interval}s")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(timeout=self._interval):
            try:
                self._collect_and_save()
            except Exception as e:
                logger.warning(f"指标采集失败: {e}")

    def _collect_and_save(self) -> None:
        cache = self._get_cache()
        if cache is None:
            return

        stats = cache.get_stats()
        now = datetime.now(timezone.utc).isoformat()

        with get_connection() as conn:
            conn.execute(
                """INSERT INTO cache_metrics_history
                   (timestamp, hits, misses, hit_rate, memory_size, evictions, l2_size, namespace_metrics_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    now,
                    stats["hits"],
                    stats["misses"],
                    stats["hit_rate"],
                    stats["memory_size"],
                    stats.get("evictions", 0),
                    stats.get("l2_size", 0),
                    json.dumps(stats["by_namespace"], ensure_ascii=False),
                )
            )
            cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
            conn.execute("DELETE FROM cache_metrics_history WHERE timestamp < ?", (cutoff,))

    @staticmethod
    def query_trend(range_hours: int = 24) -> List[Dict[str, Any]]:
        """查询历史趋势数据"""
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
                {
                    "timestamp": row[0],
                    "hits": row[1],
                    "misses": row[2],
                    "hit_rate": row[3],
                    "memory_size": row[4],
                    "evictions": row[5],
                    "l2_size": row[6],
                }
                for row in rows
            ]


_collector: Optional[CacheMetricsCollector] = None


def start_metrics_collector(cache_manager_getter: Callable[[], Any]) -> None:
    """启动指标采集器"""
    global _collector
    if _collector is None:
        _collector = CacheMetricsCollector(cache_manager_getter)
        _collector.start()


def stop_metrics_collector() -> None:
    """停止指标采集器"""
    global _collector
    if _collector:
        _collector.stop()
        _collector = None


def get_cache_trend(range_hours: int = 24) -> List[Dict[str, Any]]:
    """获取缓存历史趋势"""
    return CacheMetricsCollector.query_trend(range_hours)
