# Cache Monitor Dashboard - 技术调研报告

生成时间: 2026-04-16
源规格: .claude/specs/012-cache-monitor/spec.md

## 执行摘要

1. **现有缓存架构完善**：已实现 L1 内存 + L2 SQLite 两级缓存，具备命中/未命中统计、命名空间隔离、TTL 过期、KB 版本失效等完整功能。

2. **扩展点清晰**：`CacheManager.get_stats()` 已返回基础统计数据，前端 ObservabilityPage 采用 Tab 组织结构，可直接添加 Cache 标签页。

3. **历史趋势需要新增存储**：当前统计为进程内存计数器，不持久化。需新增 `cache_metrics_history` 表存储历史快照。

4. **缓存条目查询已具备基础**：SQLite `cache_entries` 表存储所有条目，可直接查询。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 实时命中率展示 | `lib/common/cache.py:CacheManager.get_stats()` | ✅ 已有 |
| FR-002 命中/未命中数展示 | `lib/common/cache.py:CacheManager.get_stats()` | ✅ 已有 |
| FR-003 缓存条目数展示 | `lib/common/cache.py:CacheManager.get_stats()` | ✅ 已有 `memory_size` |
| FR-004 L1/L2 分层展示 | `lib/common/cache.py` | ⚠️ 部分有，需增加 L2 条目数、驱逐次数 |
| FR-005 命名空间筛选 | `lib/common/cache.py` | ✅ 已有 `by_namespace` |
| FR-006 历史趋势图 | - | ❌ 需新增 |
| FR-007 缓存条目详情列表 | `lib/common/cache.py` SQLite 表 | ⚠️ 需新增查询 API |
| FR-008 手动清除过期缓存 | `lib/common/cache.py:invalidate_all()` | ⚠️ 需封装为 API |

### 1.2 可复用组件

**后端：**
- `CacheManager` — 核心缓存管理器，`get_stats()` 返回实时统计
- `api/routers/observability.py` — 可测性路由，已有 `/cache/stats` 端点
- `api/database.py` — 数据库访问层模式，可复用连接池
- `lib/config.py` — 配置管理，`enable_cache`、`cache.ttl` 等配置项

**前端：**
- `ObservabilityPage.tsx` — 可测性主页面，可直接添加 Tab
- `TraceView.tsx` / `TraceList.tsx` / `TraceDetail.tsx` — 视图组织模式可复用
- `observabilityStore.ts` — 状态管理模式可复用
- `api/observability.ts` — API 调用模式可复用

**类型定义：**
- `types/index.ts` — 已有 Trace 相关类型，需新增 Cache 相关类型

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `lib/common/cache.py` | 修改 | 增加 `_evictions` 计数器、`get_entries()` 条目查询、`cleanup_expired()` 清理过期 |
| `lib/common/cache_metrics.py` | 新增 | 历史指标采集与存储 |
| `api/routers/observability.py` | 修改 | 增加条目列表、历史趋势、清理过期等端点 |
| `api/schemas/observability.py` | 修改 | 增加缓存相关 Schema |
| `api/database.py` | 修改 | 增加 `cache_metrics_history` 表 DDL |
| `web/src/components/observability/CacheView.tsx` | 新增 | 缓存监控主视图 |
| `web/src/components/observability/CacheMetrics.tsx` | 新增 | 实时指标卡片 |
| `web/src/components/observability/CacheTrendChart.tsx` | 新增 | 历史趋势图 |
| `web/src/components/observability/CacheEntryList.tsx` | 新增 | 条目列表 |
| `web/src/stores/cacheStore.ts` | 新增 | 缓存状态管理 |
| `web/src/api/observability.ts` | 修改 | 增加缓存相关 API |
| `web/src/types/index.ts` | 修改 | 增加缓存相关类型 |

---

## 二、技术选型研究

### 2.1 历史趋势存储方案对比

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| 内存数组 | 简单，无 I/O | 进程重启丢失，内存占用 | 短期趋势 | ❌ |
| SQLite 时序表 | 持久化，复用现有基础设施 | 需定期清理 | 长期趋势 | ✅ |
| Prometheus | 专业时序数据库 | 引入新依赖，部署复杂 | 生产级监控 | ❌ 过度设计 |

**选择理由**：SQLite 时序表方案简单、持久化、复用现有连接池，满足 7 天历史需求。

### 2.2 前端图表库选型

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| Ant Design Charts | 已有 antd 依赖，风格统一 | 包体积较大 | ✅ |
| Recharts | 轻量，React 友好 | 需额外安装 | ❌ |
| ECharts | 功能强大 | 包体积大，风格需配置 | ❌ |

**选择理由**：项目已使用 antd，直接使用 `@ant-design/charts` 保持风格统一。

### 2.3 依赖分析

| 依赖 | 版本 | 用途 | 兼容性 |
|------|------|------|--------|
| `@ant-design/charts` | ^2.x | 趋势图 | 需新增，与 antd 5.x 兼容 |

---

## 三、数据流分析

### 3.1 现有数据流（实时统计）

```
用户请求 → CacheManager.get/set
         → 更新 _hits/_misses 计数器（内存）
         → API 调用 get_stats() 返回快照
         → 前端展示
```

### 3.2 新增数据流（历史趋势）

```
定时任务（每分钟）
         → CacheManager.get_stats()
         → 写入 cache_metrics_history 表
         → API 查询历史数据
         → 前端趋势图展示
```

### 3.3 新增数据流（条目列表）

```
前端请求 → API /cache/entries
         → 查询 cache_entries 表
         → 分页返回
         → 前端列表展示
```

### 3.4 关键数据结构

**新增 Schema（SQLite）：**
```sql
CREATE TABLE cache_metrics_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    hits INTEGER NOT NULL,
    misses INTEGER NOT NULL,
    hit_rate REAL NOT NULL,
    memory_size INTEGER NOT NULL,
    namespace_metrics_json TEXT NOT NULL  -- JSON: {embedding: {hits, misses}, retrieval: {...}, ...}
);
CREATE INDEX idx_cache_metrics_ts ON cache_metrics_history(timestamp);
```

**新增 API Response Schema（Python）：**
```python
from pydantic import BaseModel
from typing import List, Dict, Optional

class CacheStats(BaseModel):
    memory_size: int
    max_memory_entries: int
    hits: int
    misses: int
    hit_rate: float
    kb_version: str
    by_namespace: Dict[str, Dict[str, int]]
    evictions: int = 0  # 新增
    l2_size: int = 0    # 新增

class CacheEntry(BaseModel):
    key: str
    namespace: str
    created_at: float
    ttl: int
    kb_version: str
    size_bytes: int

class CacheEntryListResponse(BaseModel):
    items: List[CacheEntry]
    total: int

class CacheTrendPoint(BaseModel):
    timestamp: str
    hits: int
    misses: int
    hit_rate: float
    memory_size: int

class CacheTrendResponse(BaseModel):
    points: List[CacheTrendPoint]
```

**新增前端类型（TypeScript）：**
```typescript
export interface CacheStats {
  memory_size: number;
  max_memory_entries: number;
  hits: number;
  misses: number;
  hit_rate: number;
  kb_version: string;
  by_namespace: Record<string, { hits: number; misses: number }>;
  evictions: number;
  l2_size: number;
}

export interface CacheEntry {
  key: string;
  namespace: string;
  created_at: number;
  ttl: number;
  kb_version: string;
  size_bytes: number;
}

export interface CacheTrendPoint {
  timestamp: string;
  hits: number;
  misses: number;
  hit_rate: number;
  memory_size: number;
}
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

- [x] `CacheManager` 是否线程安全 — ✅ 已使用 `threading.RLock` 保护
- [x] SQLite `cache_entries` 表是否可直接查询 — ✅ 表已存在，schema 在 `cache.py:24-34`
- [ ] `@ant-design/charts` 是否与 antd 5.x 兼容 — 需验证
- [ ] 定时采集任务如何启动 — 建议在 API 启动时初始化后台线程

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 历史数据表膨胀 | 中 | 性能下降 | 定期清理超过 7 天的数据 |
| 定时任务与主线程竞争 | 低 | 延迟增加 | 使用独立线程，读取统计为 O(1) |
| 前端趋势图渲染慢 | 低 | 体验差 | 限制数据点数量，聚合查询 |
| 条目列表过大 | 中 | 内存压力 | 强制分页，默认 20 条 |

---

## 五、参考实现

### 5.1 主流缓存监控设计参考

**Redis Insight：**
- 实时指标卡片：命中率、内存使用、连接数
- 历史趋势图：内存、命中率随时间变化
- 键列表：支持前缀搜索、分页

**Memcached 监控：**
- 命中/未命中/驱逐三项核心指标
- 简洁的仪表盘设计

**借鉴要点：**
1. 核心指标突出展示（命中率最关键）
2. 命名空间/分层用 Tab 或 Segmented Control 切换
3. 趋势图支持时间范围选择
4. 条目列表支持筛选和分页

### 5.2 现有代码关键片段

**CacheManager.get_stats() 返回结构（cache.py:215-233）：**
```python
def get_stats(self) -> Dict[str, Any]:
    with self._lock:
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0
        return {
            "memory_size": len(self._memory),
            "max_memory_entries": self._max_memory_entries,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
            "kb_version": self._kb_version,
            "by_namespace": {
                ns: {
                    "hits": self._namespace_hits.get(ns, 0),
                    "misses": self._namespace_misses.get(ns, 0),
                }
                for ns in self._namespace_ttl
            },
        }
```

**现有 API 端点（observability.py:66-72）：**
```python
@router.get("/cache/stats")
async def get_cache_stats():
    engine = get_rag_engine()
    cache = engine.cache
    if cache is None:
        return {"status": "not_initialized"}
    return cache.get_stats()
```

---

## 六、实现建议

### 6.1 优先级排序

1. **P1 - 实时监控仪表盘**：复用现有 `get_stats()`，前端新增 Cache Tab
2. **P1 - 缓存层级详情**：扩展 `get_stats()` 增加 `evictions`、`l2_size`
3. **P2 - 历史趋势**：新增历史表 + 定时采集 + 趋势图
4. **P2 - 条目列表**：新增条目查询 API + 前端列表组件

### 6.2 测试策略

- **单元测试**：扩展 `test_cache.py`，验证新增方法
- **集成测试**：新增 `test_observability_api.py` 缓存端点测试
- **前端测试**：手动验证 UI 交互，暂不引入 E2E

### 6.3 迁移兼容性

- 无破坏性变更，纯增量功能
- 新增历史表通过 `api/database.py` 迁移脚本自动创建
- 前端 Tab 不影响现有 Trace 功能
