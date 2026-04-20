# Implementation Plan: Cache Monitor Dashboard

**Branch**: `012-cache-monitor` | **Date**: 2026-04-16 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

在可观测页面添加缓存监控功能，包括：
1. **实时监控仪表盘**：展示命中率、命中/未命中数、L1/L2 分层指标、命名空间分组
2. **历史趋势分析**：SQLite 时序表存储历史快照，支持 1h/6h/24h/7d 时间范围
3. **缓存条目列表**：查询缓存条目详情，支持命名空间筛选、分页、清除过期

## Technical Context

**Language/Version**: Python 3.11 / TypeScript 5.9
**Primary Dependencies**:
- 后端：FastAPI, Pydantic, SQLite
- 前端：React 19, antd 6, recharts 3.8, zustand 5
**Storage**: SQLite（复用现有连接池）
**Testing**: pytest
**Performance Goals**: 实时数据 < 100ms，历史查询 < 500ms
**Constraints**:
- 无破坏性变更，纯增量功能
- 复用现有 CacheManager 和 ObservabilityPage 结构
- 历史数据保留 7 天

## Constitution Check

- [x] **Library-First**: 复用 CacheManager、observabilityStore 模式、recharts 已有依赖
- [x] **测试优先**: 每个阶段规划了单元测试和集成测试
- [x] **简单优先**: SQLite 时序表而非引入 Prometheus；复用 recharts 而非新增图表库
- [x] **显式优于隐式**: 所有 API 有明确的 Schema 定义，无魔法行为
- [x] **可追溯性**: 每个 Phase 回溯到 spec.md User Story
- [x] **独立可测试**: 每个 User Story 可独立交付和验证

## Project Structure

### Documentation

```text
.claude/specs/012-cache-monitor/
├── spec.md          # 需求规格
├── research.md      # 技术调研
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code

```text
scripts/
├── lib/common/
│   ├── cache.py                 # 修改：增加 evictions/L2 统计、条目查询
│   └── cache_metrics.py         # 新增：历史指标采集
├── api/
│   ├── database.py              # 修改：增加 cache_metrics_history 表
│   ├── routers/observability.py # 修改：增加缓存 API 端点
│   └── schemas/observability.py # 修改：增加缓存 Schema
└── tests/
    ├── lib/common/test_cache.py # 修改：扩展测试
    └── api/test_cache_api.py    # 新增：API 测试

scripts/web/src/
├── components/observability/
│   ├── CacheView.tsx            # 新增：缓存监控主视图
│   ├── CacheMetrics.tsx         # 新增：实时指标卡片
│   ├── CacheTrendChart.tsx      # 新增：历史趋势图
│   └── CacheEntryList.tsx       # 新增：条目列表
├── pages/ObservabilityPage.tsx  # 修改：添加 Tab 切换
├── stores/cacheStore.ts         # 新增：缓存状态管理
├── api/observability.ts         # 修改：增加缓存 API
└── types/index.ts               # 修改：增加缓存类型
```

---

## Implementation Phases

### Phase 1: Backend - CacheManager 扩展

#### 需求回溯

→ 对应 spec.md User Story 2: 缓存层级详情视图 (P1)

#### 实现步骤

**Step 1.1: 增加驱逐计数器和 L2 条目统计**

- 文件: `scripts/lib/common/cache.py`
- 修改 `CacheManager.__init__`:
```python
def __init__(self, ...):
    # 现有初始化...
    self._evictions = 0  # 新增：LRU 驱逐计数
```

- 修改 `_evict_if_needed`:
```python
def _evict_if_needed(self) -> None:
    while len(self._memory) > self._max_memory_entries:
        self._memory.popitem(last=False)
        self._evictions += 1  # 新增
```

- 修改 `get_stats` 增加 `evictions` 和 `l2_size`:
```python
def get_stats(self) -> Dict[str, Any]:
    with self._lock:
        # 获取 L2 条目数
        l2_size = 0
        try:
            conn = self._get_db()
            row = conn.execute("SELECT COUNT(*) FROM cache_entries").fetchone()
            l2_size = row[0] if row else 0
        except Exception:
            pass

        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0
        return {
            "memory_size": len(self._memory),
            "max_memory_entries": self._max_memory_entries,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
            "kb_version": self._kb_version,
            "evictions": self._evictions,  # 新增
            "l2_size": l2_size,            # 新增
            "by_namespace": {...},
        }
```

**Step 1.2: 增加条目查询方法**

- 文件: `scripts/lib/common/cache.py`
- 新增方法:
```python
def get_entries(
    self,
    namespace: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> Tuple[List[Dict[str, Any]], int]:
    """查询缓存条目列表"""
    offset = (page - 1) * size
    where = "WHERE namespace = ?" if namespace else ""
    params = [namespace] if namespace else []

    try:
        conn = self._get_db()
        # 查询总数
        count_row = conn.execute(
            f"SELECT COUNT(*) FROM cache_entries {where}", params
        ).fetchone()
        total = count_row[0] if count_row else 0

        # 查询条目
        rows = conn.execute(
            f"SELECT key, namespace, created_at, ttl, kb_version, LENGTH(value) as size_bytes "
            f"FROM cache_entries {where} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [size, offset]
        ).fetchall()

        items = [
            {
                "key": row[0],
                "namespace": row[1],
                "created_at": row[2],
                "ttl": row[3],
                "kb_version": row[4] or "",
                "size_bytes": row[5],
            }
            for row in rows
        ]
        return items, total
    except Exception as e:
        logger.warning(f"缓存条目查询失败: {e}")
        return [], 0
```

**Step 1.3: 增加清理过期方法**

- 文件: `scripts/lib/common/cache.py`
- 新增方法:
```python
def cleanup_expired(self) -> int:
    """清理所有过期缓存条目，返回清理数量"""
    now = time.time()
    count = 0

    # 清理内存缓存
    with self._lock:
        keys_to_remove = []
        for key, (_, meta, created_at) in self._memory.items():
            ttl = meta.get("ttl", self._default_ttl)
            if self._is_expired(created_at, ttl):
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del self._memory[key]
            count += 1

    # 清理 SQLite 缓存
    try:
        conn = self._get_db()
        cursor = conn.execute(
            "DELETE FROM cache_entries WHERE created_at + ttl < ?", (now,)
        )
        count += cursor.rowcount
        conn.commit()
    except Exception as e:
        logger.warning(f"SQLite 过期清理失败: {e}")

    return count
```

#### 测试

- 文件: `scripts/tests/lib/common/test_cache.py`
- 新增测试类:
```python
class TestEvictionTracking:
    def test_eviction_counter(self, cache_db):
        cm = CacheManager(db_path=cache_db, max_memory_entries=3)
        for i in range(5):
            cm.set("generation", f"q{i}", f"v{i}")
        stats = cm.get_stats()
        assert stats["evictions"] >= 2  # 至少驱逐 2 个

class TestGetEntries:
    def test_list_entries(self, cm):
        cm.set("embedding", "t1", [0.1, 0.2])
        cm.set("retrieval", "q1", [{"score": 0.9}])
        items, total = cm.get_entries()
        assert total >= 2

    def test_filter_by_namespace(self, cm):
        cm.set("embedding", "t1", [0.1])
        cm.set("retrieval", "q1", [{}])
        items, total = cm.get_entries(namespace="embedding")
        assert all(item["namespace"] == "embedding" for item in items)

class TestCleanupExpired:
    def test_cleanup_removes_expired(self, cache_db):
        cm = CacheManager(db_path=cache_db)
        cm.set("generation", "q1", "v1", ttl=1)
        time.sleep(1.1)
        count = cm.cleanup_expired()
        assert count >= 1
```

---

### Phase 2: Backend - 历史指标存储

#### 需求回溯

→ 对应 spec.md User Story 3: 历史趋势分析 (P2)

#### 实现步骤

**Step 2.1: 增加历史指标表**

- 文件: `scripts/api/database.py`
- 在 `_SCHEMA_SQL` 中添加:
```sql
CREATE TABLE IF NOT EXISTS cache_metrics_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    hits INTEGER NOT NULL,
    misses INTEGER NOT NULL,
    hit_rate REAL NOT NULL,
    memory_size INTEGER NOT NULL,
    evictions INTEGER NOT NULL DEFAULT 0,
    l2_size INTEGER NOT NULL DEFAULT 0,
    namespace_metrics_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cache_metrics_ts ON cache_metrics_history(timestamp);
```

**Step 2.2: 实现指标采集器**

- 文件: `scripts/lib/common/cache_metrics.py` (新增)
```python
"""缓存历史指标采集器"""
import json
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from lib.common.database import get_connection

logger = logging.getLogger(__name__)

# 采样间隔（秒）
SAMPLE_INTERVAL = 60
# 保留天数
RETENTION_DAYS = 7


class CacheMetricsCollector:
    """缓存指标定时采集器"""

    def __init__(self, cache_manager_getter, interval: int = SAMPLE_INTERVAL):
        self._get_cache = cache_manager_getter
        self._interval = interval
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(f"缓存指标采集器已启动，间隔 {self._interval}s")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        while self._running:
            try:
                self._collect_and_save()
            except Exception as e:
                logger.warning(f"指标采集失败: {e}")
            time.sleep(self._interval)

    def _collect_and_save(self) -> None:
        cache = self._get_cache()
        if cache is None:
            return

        stats = cache.get_stats()
        now = datetime.now(timezone.utc).isoformat()

        with get_connection() as conn:
            # 写入新数据
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
            # 清理过期数据
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


# 全局采集器实例
_collector: Optional[CacheMetricsCollector] = None


def start_metrics_collector(cache_manager_getter) -> None:
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
```

**Step 2.3: 在 API 启动时初始化采集器**

- 文件: `scripts/api/app.py`
- 在 `lifespan` 中添加:
```python
from contextlib import asynccontextmanager
from lib.common.cache_metrics import start_metrics_collector, stop_metrics_collector

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    from api.dependencies import get_rag_engine
    engine = get_rag_engine()
    if engine.cache:
        start_metrics_collector(lambda: engine.cache)
    yield
    # 关闭时
    stop_metrics_collector()
```

---

### Phase 3: Backend - API 端点

#### 需求回溯

→ 对应 spec.md User Story 1, 3, 4

#### 实现步骤

**Step 3.1: 增加 Schema 定义**

- 文件: `scripts/api/schemas/observability.py`
- 新增:
```python
from typing import List, Dict, Optional

class CacheEntry(BaseModel):
    key: str
    namespace: str
    created_at: float
    ttl: int
    kb_version: str
    size_bytes: int

class CacheEntryListResponse(BaseModel):
    items: List[CacheEntry] = []
    total: int = 0

class CacheTrendPoint(BaseModel):
    timestamp: str
    hits: int
    misses: int
    hit_rate: float
    memory_size: int
    evictions: int = 0
    l2_size: int = 0

class CacheTrendResponse(BaseModel):
    points: List[CacheTrendPoint] = []
```

**Step 3.2: 增加 API 端点**

- 文件: `scripts/api/routers/observability.py`
- 新增端点:
```python
from api.schemas.observability import CacheEntryListResponse, CacheTrendResponse
from lib.common.cache_metrics import get_cache_trend
from fastapi import Query

@router.get("/cache/entries", response_model=CacheEntryListResponse)
async def list_cache_entries(
    namespace: str = Query("", description="命名空间筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    engine = get_rag_engine()
    cache = engine.cache
    if cache is None:
        return CacheEntryListResponse(items=[], total=0)
    ns = namespace if namespace else None
    items, total = cache.get_entries(namespace=ns, page=page, size=size)
    return CacheEntryListResponse(
        items=[CacheEntry(**item) for item in items],
        total=total,
    )

@router.get("/cache/trend", response_model=CacheTrendResponse)
async def get_cache_trend_data(
    range_hours: int = Query(24, ge=1, le=168, description="时间范围（小时）"),
):
    points = get_cache_trend(range_hours)
    return CacheTrendResponse(
        points=[CacheTrendPoint(**p) for p in points]
    )

@router.post("/cache/cleanup")
async def cleanup_cache():
    engine = get_rag_engine()
    cache = engine.cache
    if cache is None:
        return {"deleted": 0}
    count = cache.cleanup_expired()
    return {"deleted": count}
```

#### 测试

- 文件: `scripts/tests/api/test_cache_api.py` (新增)
```python
import pytest
from fastapi.testclient import TestClient
from api.app import app

client = TestClient(app)

class TestCacheEndpoints:
    def test_get_cache_stats(self):
        resp = client.get("/api/observability/cache/stats")
        assert resp.status_code == 200

    def test_list_cache_entries(self):
        resp = client.get("/api/observability/cache/entries")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_get_cache_trend(self):
        resp = client.get("/api/observability/cache/trend?range_hours=1")
        assert resp.status_code == 200
        data = resp.json()
        assert "points" in data
```

---

### Phase 4: Frontend - 类型和 API

#### 需求回溯

→ 对应 spec.md User Story 1, 2

#### 实现步骤

**Step 4.1: 增加类型定义**

- 文件: `scripts/web/src/types/index.ts`
- 新增:
```typescript
// Cache types
export interface CacheStats {
  memory_size: number;
  max_memory_entries: number;
  hits: number;
  misses: number;
  hit_rate: number;
  kb_version: string;
  evictions: number;
  l2_size: number;
  by_namespace: Record<string, { hits: number; misses: number }>;
}

export interface CacheEntry {
  key: string;
  namespace: string;
  created_at: number;
  ttl: number;
  kb_version: string;
  size_bytes: number;
}

export interface CacheEntryListResponse {
  items: CacheEntry[];
  total: number;
}

export interface CacheTrendPoint {
  timestamp: string;
  hits: number;
  misses: number;
  hit_rate: number;
  memory_size: number;
  evictions: number;
  l2_size: number;
}

export interface CacheTrendResponse {
  points: CacheTrendPoint[];
}
```

**Step 4.2: 增加 API 函数**

- 文件: `scripts/web/src/api/observability.ts`
- 新增:
```typescript
import type { CacheStats, CacheEntryListResponse, CacheTrendResponse } from '../types';

export async function fetchCacheStats(): Promise<CacheStats | { status: string }> {
  const { data } = await client.get('/api/observability/cache/stats');
  return data;
}

export async function fetchCacheEntries(params: {
  namespace?: string;
  page?: number;
  size?: number;
} = {}): Promise<CacheEntryListResponse> {
  const { data } = await client.get('/api/observability/cache/entries', { params });
  return data;
}

export async function fetchCacheTrend(rangeHours: number = 24): Promise<CacheTrendResponse> {
  const { data } = await client.get('/api/observability/cache/trend', {
    params: { range_hours: rangeHours },
  });
  return data;
}

export async function cleanupCache(): Promise<{ deleted: number }> {
  const { data } = await client.post('/api/observability/cache/cleanup');
  return data;
}
```

---

### Phase 5: Frontend - 状态管理

#### 需求回溯

→ 对应 spec.md User Story 1, 3, 4

#### 实现步骤

- 文件: `scripts/web/src/stores/cacheStore.ts` (新增)
```typescript
import { create } from 'zustand';
import type { CacheStats, CacheEntry, CacheTrendPoint } from '../types';
import * as api from '../api/observability';

interface CacheState {
  // 实时统计
  stats: CacheStats | null;
  statsLoading: boolean;

  // 历史趋势
  trendPoints: CacheTrendPoint[];
  trendRangeHours: number;
  trendLoading: boolean;

  // 条目列表
  entries: CacheEntry[];
  entriesTotal: number;
  entriesPage: number;
  entriesNamespace: string;
  entriesLoading: boolean;

  // Actions
  loadStats: () => Promise<void>;
  loadTrend: (rangeHours?: number) => Promise<void>;
  loadEntries: (namespace?: string, page?: number) => Promise<void>;
  cleanup: () => Promise<number>;
}

export const useCacheStore = create<CacheState>((set, get) => ({
  stats: null,
  statsLoading: false,
  trendPoints: [],
  trendRangeHours: 24,
  trendLoading: false,
  entries: [],
  entriesTotal: 0,
  entriesPage: 1,
  entriesNamespace: '',
  entriesLoading: false,

  loadStats: async () => {
    set({ statsLoading: true });
    try {
      const data = await api.fetchCacheStats();
      if ('status' in data) {
        set({ stats: null, statsLoading: false });
      } else {
        set({ stats: data, statsLoading: false });
      }
    } catch {
      set({ statsLoading: false });
    }
  },

  loadTrend: async (rangeHours?: number) => {
    const hours = rangeHours ?? get().trendRangeHours;
    set({ trendLoading: true, trendRangeHours: hours });
    try {
      const data = await api.fetchCacheTrend(hours);
      set({ trendPoints: data.points, trendLoading: false });
    } catch {
      set({ trendLoading: false });
    }
  },

  loadEntries: async (namespace?: string, page?: number) => {
    const ns = namespace ?? get().entriesNamespace;
    const p = page ?? get().entriesPage;
    set({ entriesLoading: true, entriesNamespace: ns, entriesPage: p });
    try {
      const data = await api.fetchCacheEntries({
        namespace: ns || undefined,
        page: p,
        size: 20,
      });
      set({ entries: data.items, entriesTotal: data.total, entriesLoading: false });
    } catch {
      set({ entriesLoading: false });
    }
  },

  cleanup: async () => {
    const result = await api.cleanupCache();
    get().loadStats();
    get().loadEntries();
    return result.deleted;
  },
}));
```

---

### Phase 6: Frontend - UI 组件

#### 需求回溯

→ 对应 spec.md User Story 1, 2, 3, 4

#### 实现步骤

**Step 6.1: 实时指标卡片**

- 文件: `scripts/web/src/components/observability/CacheMetrics.tsx` (新增)
```typescript
import { Card, Row, Col, Statistic, Progress, Segmented, theme } from 'antd';
import { useCacheStore } from '../../stores/cacheStore';
import type { CacheStats } from '../../types';

function NamespaceMetrics({ stats }: { stats: CacheStats }) {
  const { token } = theme.useToken();
  const namespaces = Object.entries(stats.by_namespace);

  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ fontSize: 12, color: token.colorTextTertiary, marginBottom: 8 }}>
        命名空间详情
      </div>
      <Row gutter={[8, 8]}>
        {namespaces.map(([ns, data]) => {
          const total = data.hits + data.misses;
          const rate = total > 0 ? data.hits / total : 0;
          return (
            <Col key={ns} span={8}>
              <Card size="small" style={{ background: token.colorFillQuaternary }}>
                <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 4 }}>{ns}</div>
                <Progress
                  percent={Math.round(rate * 100)}
                  size="small"
                  format={() => `${data.hits}/${total}`}
                />
              </Card>
            </Col>
          );
        })}
      </Row>
    </div>
  );
}

export default function CacheMetrics() {
  const { token } = theme.useToken();
  const { stats, loadStats } = useCacheStore();

  if (!stats) {
    return (
      <Card>
        <div style={{ color: token.colorTextTertiary, textAlign: 'center', padding: 20 }}>
          缓存未启用
        </div>
      </Card>
    );
  }

  const l1Usage = stats.memory_size / stats.max_memory_entries;

  return (
    <Card
      title="缓存统计"
      extra={
        <a onClick={() => loadStats()} style={{ fontSize: 12 }}>刷新</a>
      }
    >
      <Row gutter={16}>
        <Col span={6}>
          <Statistic
            title="命中率"
            value={Math.round(stats.hit_rate * 100)}
            suffix="%"
            valueStyle={{ color: stats.hit_rate > 0.8 ? token.colorSuccess : token.colorWarning }}
          />
        </Col>
        <Col span={6}>
          <Statistic title="命中" value={stats.hits} />
        </Col>
        <Col span={6}>
          <Statistic title="未命中" value={stats.misses} />
        </Col>
        <Col span={6}>
          <Statistic title="驱逐" value={stats.evictions} />
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={12}>
          <div style={{ fontSize: 12, color: token.colorTextTertiary, marginBottom: 4 }}>
            L1 内存缓存
          </div>
          <Progress
            percent={Math.round(l1Usage * 100)}
            format={() => `${stats.memory_size} / ${stats.max_memory_entries}`}
          />
        </Col>
        <Col span={12}>
          <div style={{ fontSize: 12, color: token.colorTextTertiary, marginBottom: 4 }}>
            L2 持久化缓存
          </div>
          <div style={{ fontSize: 16 }}>{stats.l2_size} 条</div>
        </Col>
      </Row>

      <NamespaceMetrics stats={stats} />
    </Card>
  );
}
```

**Step 6.2: 历史趋势图**

- 文件: `scripts/web/src/components/observability/CacheTrendChart.tsx` (新增)
```typescript
import { Card, Segmented, Spin } from 'antd';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { useCacheStore } from '../../stores/cacheStore';

const RANGE_OPTIONS = [
  { label: '1小时', value: 1 },
  { label: '6小时', value: 6 },
  { label: '24小时', value: 24 },
  { label: '7天', value: 168 },
];

function formatTime(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export default function CacheTrendChart() {
  const { trendPoints, trendRangeHours, trendLoading, loadTrend } = useCacheStore();

  const data = trendPoints.map((p) => ({
    time: formatTime(p.timestamp),
    hitRate: Math.round(p.hit_rate * 100),
    hits: p.hits,
    misses: p.misses,
  }));

  return (
    <Card
      title="命中率趋势"
      extra={
        <Segmented
          size="small"
          options={RANGE_OPTIONS}
          value={trendRangeHours}
          onChange={(v) => loadTrend(v as number)}
        />
      }
    >
      {trendLoading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin />
        </div>
      ) : data.length === 0 ? (
        <div style={{ textAlign: 'center', color: '#999', padding: 40 }}>
          无历史数据
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="time" tick={{ fontSize: 10 }} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} />
            <Tooltip
              formatter={(value: number, name: string) => {
                if (name === 'hitRate') return [`${value}%`, '命中率'];
                return [value, name];
              }}
            />
            <Line
              type="monotone"
              dataKey="hitRate"
              stroke="#1890ff"
              dot={false}
              strokeWidth={2}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}
```

**Step 6.3: 条目列表**

- 文件: `scripts/web/src/components/observability/CacheEntryList.tsx` (新增)
```typescript
import { useState } from 'react';
import { Card, Table, Select, Button, Popconfirm, message, theme, Space } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { useCacheStore } from '../../stores/cacheStore';
import type { CacheEntry } from '../../types';

const NAMESPACES = ['', 'embedding', 'retrieval', 'generation'];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTTL(ttl: number): string {
  if (ttl < 60) return `${ttl}s`;
  if (ttl < 3600) return `${Math.round(ttl / 60)}m`;
  return `${Math.round(ttl / 3600)}h`;
}

export default function CacheEntryList() {
  const { token } = theme.useToken();
  const {
    entries, entriesTotal, entriesPage, entriesNamespace, entriesLoading,
    loadEntries, cleanup,
  } = useCacheStore();

  const [cleanupLoading, setCleanupLoading] = useState(false);

  const handleCleanup = async () => {
    setCleanupLoading(true);
    try {
      const count = await cleanup();
      message.success(`已清理 ${count} 条过期缓存`);
    } catch {
      message.error('清理失败');
    } finally {
      setCleanupLoading(false);
    }
  };

  const columns = [
    {
      title: 'Key',
      dataIndex: 'key',
      key: 'key',
      ellipsis: true,
      width: 200,
      render: (key: string) => (
        <span style={{ fontFamily: 'monospace', fontSize: 11 }} title={key}>
          {key.slice(0, 30)}...
        </span>
      ),
    },
    {
      title: '命名空间',
      dataIndex: 'namespace',
      key: 'namespace',
      width: 100,
    },
    {
      title: '大小',
      dataIndex: 'size_bytes',
      key: 'size_bytes',
      width: 80,
      render: (bytes: number) => formatBytes(bytes),
    },
    {
      title: 'TTL',
      dataIndex: 'ttl',
      key: 'ttl',
      width: 60,
      render: (ttl: number) => formatTTL(ttl),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 140,
      render: (ts: number) => new Date(ts * 1000).toLocaleString(),
    },
  ];

  return (
    <Card
      title={`缓存条目 (${entriesTotal})`}
      extra={
        <Space>
          <Select
            size="small"
            style={{ width: 120 }}
            value={entriesNamespace}
            onChange={(v) => loadEntries(v, 1)}
            options={NAMESPACES.map((ns) => ({
              label: ns || '全部',
              value: ns,
            }))}
          />
          <Popconfirm
            title="确定清理过期缓存？"
            onConfirm={handleCleanup}
          >
            <Button size="small" icon={<DeleteOutlined />} loading={cleanupLoading}>
              清理过期
            </Button>
          </Popconfirm>
        </Space>
      }
    >
      <Table<CacheEntry>
        size="small"
        columns={columns}
        dataSource={entries}
        rowKey="key"
        loading={entriesLoading}
        pagination={{
          current: entriesPage,
          pageSize: 20,
          total: entriesTotal,
          onChange: (p) => loadEntries(entriesNamespace, p),
          showSizeChanger: false,
        }}
      />
    </Card>
  );
}
```

**Step 6.4: 主视图**

- 文件: `scripts/web/src/components/observability/CacheView.tsx` (新增)
```typescript
import { useEffect } from 'react';
import { Row, Col } from 'antd';
import CacheMetrics from './CacheMetrics';
import CacheTrendChart from './CacheTrendChart';
import CacheEntryList from './CacheEntryList';
import { useCacheStore } from '../../stores/cacheStore';

export default function CacheView() {
  const { loadStats, loadTrend, loadEntries } = useCacheStore();

  useEffect(() => {
    loadStats();
    loadTrend(24);
    loadEntries();
  }, [loadStats, loadTrend, loadEntries]);

  return (
    <div style={{ padding: 16, overflow: 'auto', height: '100%' }}>
      <Row gutter={[16, 16]}>
        <Col span={24}>
          <CacheMetrics />
        </Col>
        <Col span={24}>
          <CacheTrendChart />
        </Col>
        <Col span={24}>
          <CacheEntryList />
        </Col>
      </Row>
    </div>
  );
}
```

**Step 6.5: 修改 ObservabilityPage**

- 文件: `scripts/web/src/pages/ObservabilityPage.tsx`
- 修改为 Tab 结构:
```typescript
import { Tabs, Grid } from 'antd';
import TraceView from '../components/observability/TraceView';
import CacheView from '../components/observability/CacheView';

export default function ObservabilityPage() {
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  const items = [
    { key: 'trace', label: 'Trace', children: <TraceView /> },
    { key: 'cache', label: 'Cache', children: <CacheView /> },
  ];

  return (
    <div style={{
      height: isMobile
        ? 'calc(100vh - 48px - var(--mobile-nav-height) - env(safe-area-inset-bottom, 0px))'
        : 'calc(100vh - var(--header-height) - var(--content-padding) * 2)',
    }}>
      <Tabs
        defaultActiveKey="trace"
        items={items}
        style={{ height: '100%' }}
        tabBarStyle={{ padding: '0 16px', marginBottom: 0 }}
      />
    </div>
  );
}
```

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | - | - |

---

## Appendix

### 执行顺序建议

```
Phase 1 (CacheManager 扩展)
    ↓
Phase 2 (历史指标存储)
    ↓
Phase 3 (API 端点) ← 依赖 Phase 1, 2
    ↓
Phase 4 (Frontend 类型/API)
    ↓
Phase 5 (状态管理)
    ↓
Phase 6 (UI 组件) ← 依赖 Phase 4, 5
```

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US1 实时监控仪表盘 | 显示命中率、命中/未命中数、命名空间分组 | `test_cache_api.py::test_get_cache_stats` |
| US2 缓存层级详情 | 显示 L1/L2 条目数、驱逐次数 | `test_cache.py::TestEvictionTracking` |
| US3 历史趋势分析 | 支持 1h/6h/24h/7d 范围、趋势曲线展示 | 手动验证 UI |
| US4 缓存条目详情 | 条目列表、命名空间筛选、分页、清理过期 | `test_cache_api.py::test_list_cache_entries` |
