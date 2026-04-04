# Observability Page Design

## Overview

An independent Trace viewing page for production monitoring, plus session search capability extended into the existing AskPage. Trace viewing is the core new feature; session management stays in AskPage with enhanced search.

## Motivation

- Current trace viewing is only accessible per-message in AskPage's debug panel
- No standalone trace listing, filtering, or search capability
- Growing trace data needs cleanup to prevent database bloat
- Production ops needs efficient error trace discovery and diagnosis
- Session list in AskPage lacks search and batch management

## Design Decisions

1. **Independent Trace page** at `/observability` with sidebar navigation entry
2. **Session management stays in AskPage** — extend existing conversation list with search and batch delete
3. **Left-right split layout** for Trace page: list on left, detail on right
4. **Reuse existing components**: TracePanel used as-is for trace detail
5. **Batch cleanup** for traces, with preview confirmation
6. **Statistics dashboard deferred** to future iteration

## Part 1: AskPage Session Enhancement

Extend the existing conversation list in AskPage's left panel:

- **Add search box**: Fuzzy search by session title above the conversation list
- **Add batch delete**: Multi-select conversations via checkbox, batch delete button
- **Keep existing behavior**: Click to load conversation, single delete on hover

### API Changes to Existing Endpoints

Extend `GET /api/ask/conversations` to support `?search=` query parameter for title filtering.

Add `DELETE /api/ask/conversations` for batch delete with `?ids=conv1,conv2` query parameter.

### Component Changes

Modify the conversation list section in `ChatPanel.tsx` (AskPage's left panel):
- Add `Input.Search` above the list
- Add `Checkbox` per conversation item
- Add batch delete button (appears when items selected)

## Part 2: Trace Viewing Page

### Layout

```
ObservabilityPage (/observability)
├── Left: TraceList (search by IDs, filter by status/date, multi-select, batch cleanup)
└── Right: TraceDetail (TracePanel reuse, trace info header, copy buttons)
```

```
┌──────────────────────────────────────────────────────────────┐
│  可测性                                      [批量清理]        │
├──────────┬───────────────────────────────────────────────────┤
│ 🔍 TraceId│  Trace 详情                                       │
│ 🔍 ConvId │  ┌───────────────────────────────────────────┐   │
│ 🔍 MsgId  │  │ trace_id: a1b2c3d4e5f6  2026-04-04 10:30 │   │
│ ─────────│  │ conversation_id: conv_a1b2  msg_id: 42     │   │
│ 状态 ▼   │  │ ┌───────────────────────────────────────┐ │   │
│ 时间范围  │  │ │ 3 步骤 · 2 LLM调用 · 1.2s · 0 错误  │ │   │
│ ─────────│  │ └───────────────────────────────────────┘ │   │
│ □ t1 ◀───│──│ ▶ root (1.2s)                               │   │
│ □ t2     │  │   ├─ preprocessing (0.3s)                  │   │
│ □ t3     │  │   ├─ retrieval (0.5s)                      │   │
│ □ t4     │  │   ├─ rerank (0.2s)                         │   │
│          │  │   └─ llm (0.2s)                             │   │
│          │  │                                             │   │
│ 48条     │  └───────────────────────────────────────────┘   │
└──────────┴───────────────────────────────────────────────────┘
```

### Left Panel: TraceList

- **Search**: 3 separate search fields
  - traceId (exact match)
  - conversationId (exact match)
  - messageId (exact match)
- **Filters**:
  - Status dropdown: All / ok / error
  - Date range picker: start_date, end_date (on created_at)
- **List columns**: trace_id (truncated), status badge, duration_ms, created_at
- **Sort**: Default descending by created_at
- **Multi-select**: Checkbox per item + select-all
- **Actions**: Batch cleanup (selected), conditional cleanup dialog

### Right Panel: TraceDetail

- **Info header**: trace_id, conversation_id, message_id (all copyable), created_at
- **Trace tree**: Reuse `TracePanel` component directly, pass trace data
- **Empty state**: Prompt to select a trace from the list

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/observability/traces` | Paginated list, query params: `trace_id`, `conversation_id`, `message_id`, `status`, `start_date`, `end_date`, `page`, `size` |
| GET | `/api/observability/traces/{trace_id}` | Full trace data with span tree |
| DELETE | `/api/observability/traces` | Batch delete by IDs, query param: `ids=t1,t2` |
| POST | `/api/observability/traces/cleanup` | Conditional cleanup: body `{start_date, end_date, status}`, preview mode returns count, confirm mode executes |

### Cleanup Logic

- Conditional cleanup: Select date range + status -> preview affected count -> confirm -> execute
- Selection cleanup: Check items in list -> batch delete
- Cascade: Deleting a trace deletes all associated spans
- Frontend shows preview dialog before executing any cleanup

## Frontend Component Structure

```
scripts/web/src/
├── pages/
│   ├── AskPage.tsx                      # Extend: add search to conversation list
│   └── ObservabilityPage.tsx            # New: Trace viewing page
├── components/
│   ├── TracePanel.tsx                   # Existing: reused as-is
│   └── observability/
│       ├── TraceView.tsx                # Trace viewing (split layout container)
│       ├── TraceList.tsx                # Left: trace list + search + filters
│       ├── TraceDetail.tsx              # Right: wraps TracePanel + info header
│       └── CleanupDialog.tsx            # Batch cleanup confirmation dialog
├── api/
│   └── observability.ts                 # New: API client for observability endpoints
├── stores/
│   └── observabilityStore.ts            # New: Zustand store for trace state
└── types/
    └── index.ts                         # Extend: trace list item type, cleanup request type
```

### Reuse Summary

| Component | Source | Reuse Method |
|-----------|--------|-------------|
| TracePanel | Existing | Pass trace data, no modification needed |
| AppLayout | Existing | Add "Observability" nav item to sidebar |
| Ant Design | Existing | Table, Input, DatePicker, Modal, Checkbox, Badge |

## Backend Structure

```
scripts/api/
├── routers/
│   └── observability.py                 # New: trace viewing and cleanup API
├── routers/
│   └── ask.py                           # Extend: add search param and batch delete
scripts/api/database.py                   # Extend: add trace query, cleanup, conversation search functions
```

### Database Functions to Add

**Conversation queries (for AskPage extension):**
- Modify `get_conversations()` to accept optional `search: str` parameter for title filtering
- `batch_delete_conversations(ids: List[str]) -> int` — delete by IDs, return count

**Trace queries (new):**
- `search_traces(trace_id, conversation_id, message_id, status, start_date, end_date, page, size) -> Tuple[List[Dict], int]` — paginated filtered query
- `get_trace_by_trace_id(trace_id: str) -> Optional[Dict]` — get full trace with span tree by trace_id
- `batch_delete_traces(trace_ids: List[str]) -> int` — delete traces + cascade spans
- `count_traces_for_cleanup(start_date, end_date, status) -> int` — preview count for conditional cleanup
- `cleanup_traces(start_date, end_date, status) -> int` — conditional cleanup, return deleted count

## Data Flow

### AskPage Session Enhancement

```
User types in search box
  → Debounced fetch: GET /api/ask/conversations?search=xxx
  → Filtered list renders

User selects multiple conversations + clicks batch delete
  → DELETE /api/ask/conversations?ids=conv1,conv2
  → List refreshes
```

### Trace Page

```
User opens /observability
  → ObservabilityPage renders TraceView
  → TraceList mounts, calls GET /api/observability/traces
  → User enters traceId / applies filters → re-fetches list
  → User selects a trace → GET /api/observability/traces/{trace_id}
  → TraceDetail renders TracePanel with full trace data

User initiates cleanup
  → CleanupDialog opens, user selects conditions
  → POST /api/observability/traces/cleanup with {start_date, end_date, status, preview: true}
  → Backend returns count
  → User confirms → POST with {preview: false}
  → List refreshes
```

## Out of Scope (Future Iterations)

- Statistics dashboard (trace count trends, latency distribution, error rates)
- Trace comparison view
- Issue annotation / bookmarking
- Trace export (JSON/CSV)
- Real-time trace streaming
