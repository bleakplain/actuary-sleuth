import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { Input, Button, Checkbox, Popconfirm, message, theme, Grid, Space } from 'antd';
import { SearchOutlined, DeleteOutlined, ClearOutlined } from '@ant-design/icons';
import { useObservabilityStore } from '../../stores/observabilityStore';
import type { Dayjs } from 'dayjs';
import { DatePicker } from 'antd';

const PAGE_SIZE = 20;

interface ColumnDef {
  key: string;
  label: string;
  initialWidth: number;
  minWidth?: number;
  flex?: boolean;
}

const COLUMNS: ColumnDef[] = [
  { key: 'time', label: '时间', initialWidth: 130, minWidth: 90 },
  { key: 'traceId', label: 'Trace ID', initialWidth: 110, minWidth: 80 },
  { key: 'name', label: '名称', initialWidth: 200, minWidth: 60, flex: true },
  { key: 'spans', label: 'Spans', initialWidth: 56, minWidth: 40 },
  { key: 'llmCalls', label: 'LLM 调用', initialWidth: 68, minWidth: 50 },
  { key: 'latency', label: '耗时', initialWidth: 100, minWidth: 70 },
];

function loadColumnWidths(): Record<string, number> {
  try {
    const saved = localStorage.getItem('trace-list-col-widths');
    if (saved) return JSON.parse(saved);
  } catch { /* ignore */ }
  const defaults: Record<string, number> = {};
  for (const col of COLUMNS) defaults[col.key] = col.initialWidth;
  return defaults;
}

export default function TraceList() {
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const {
    traceList, traceTotal, tracePage,
    selectedTraceId, selectTrace,
    loadTraces, setPage, deleteTraces,
  } = useObservabilityStore();

  const [traceIdFilter, setTraceIdFilter] = useState('');
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [colWidths, setColWidths] = useState<Record<string, number>>(loadColumnWidths);

  const handleSearch = () => {
    setSelectedIds([]);
    setPage(1);
    loadTraces({
      trace_id: traceIdFilter || undefined,
      start_date: dateRange?.[0]?.format('YYYY-MM-DD') || undefined,
      end_date: dateRange?.[1]?.format('YYYY-MM-DD') || undefined,
      page: 1,
    });
  };

  const handleClear = () => {
    setTraceIdFilter('');
    setDateRange(null);
    setSelectedIds([]);
    setPage(1);
    loadTraces({ page: 1 });
  };

  const handleBatchDelete = async () => {
    try {
      await deleteTraces(selectedIds);
      setSelectedIds([]);
      message.success('已删除');
    } catch {
      message.error('删除失败');
    }
  };

  const toggleSelect = (id: string, checked: boolean) => {
    setSelectedIds((prev) => checked ? [...prev, id] : prev.filter((x) => x !== id));
  };

  const allSelected = traceList.length > 0 && traceList.every((t) => selectedIds.includes(t.trace_id));
  const hasSelection = selectedIds.length > 0;
  const maxDuration = useMemo(() => Math.max(...traceList.map((t) => t.total_duration_ms), 1), [traceList]);

  const fmtDuration = (ms: number) => {
    if (ms < 1000) return `${ms.toFixed(0)}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  };

  const fmtTime = (s: string) => {
    if (!s) return '';
    const d = new Date(s);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${pad(d.getMonth() + 1)}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  };

  const handleResizeStart = useCallback((colKey: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const startWidth = e.currentTarget.parentElement?.offsetWidth ?? 100;
    let lastX = e.clientX;

    const handleMove = (ev: MouseEvent) => {
      const delta = ev.clientX - lastX;
      lastX = ev.clientX;
      const col = COLUMNS.find((c) => c.key === colKey);
      const minWidth = col?.minWidth ?? 40;
      const cur = document.querySelector<HTMLElement>(`[data-col="${colKey}"]`);
      if (!cur) return;
      const newWidth = Math.max(minWidth, cur.offsetWidth + delta);
      setColWidths((prev) => ({ ...prev, [colKey]: newWidth }));
    };

    const handleUp = () => {
      document.removeEventListener('mousemove', handleMove);
      document.removeEventListener('mouseup', handleUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.addEventListener('mousemove', handleMove);
    document.addEventListener('mouseup', handleUp);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, []);

  useEffect(() => {
    try { localStorage.setItem('trace-list-col-widths', JSON.stringify(colWidths)); } catch { /* ignore */ }
  }, [colWidths]);

  const renderCell = (item: typeof traceList[number], key: string) => {
    switch (key) {
      case 'time':
        return (
          <span style={{ color: token.colorTextTertiary, fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
            {fmtTime(item.created_at)}
          </span>
        );
      case 'traceId':
        return (
          <span style={{
            fontFamily: "'SF Mono','Menlo','Consolas',monospace",
            fontSize: 12, color: token.colorText,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }} title={item.trace_id}>
            {item.trace_id}
          </span>
        );
      case 'name':
        return (
          <span style={{
            color: token.colorText, fontSize: 13,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }} title={item.trace_name || undefined}>
            {item.trace_name || '-'}
          </span>
        );
      case 'spans':
        return <span style={{ color: token.colorTextTertiary, fontSize: 12 }}>{item.span_count}</span>;
      case 'llmCalls':
        return <span style={{ color: token.colorTextTertiary, fontSize: 12 }}>{item.llm_call_count}</span>;
      case 'latency':
        return (
          <span style={{
            color: item.status === 'error' ? token.colorError : token.colorSuccess,
            fontSize: 12, fontVariantNumeric: 'tabular-nums',
            position: 'relative',
          }}>
            <span style={{
              position: 'absolute', left: 0, top: 4, bottom: 4,
              width: `${Math.max((item.total_duration_ms / maxDuration) * 100, 2)}%`,
              background: item.status === 'error' ? token.colorErrorBg : token.colorSuccessBg,
              borderRadius: 2,
            }} />
            <span style={{ position: 'relative' }}>{fmtDuration(item.total_duration_ms)}</span>
          </span>
        );
      default:
        return null;
    }
  };

  const colStyle = (col: ColumnDef) => {
    if (col.flex) {
      return { flex: '1 1 0', minWidth: col.minWidth ?? 60, paddingLeft: 12 };
    }
    return { width: colWidths[col.key], flexShrink: 0 };
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Filter bar */}
      <div
        className="section-header"
        style={{ padding: '10px 16px', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: isMobile ? 6 : 8, flexShrink: 0 }}
      >
        <Input
          placeholder="Trace ID"
          size="small"
          value={traceIdFilter}
          onChange={(e) => setTraceIdFilter(e.target.value)}
          onPressEnter={handleSearch}
          allowClear
          onClear={handleSearch}
          style={{ width: isMobile ? '100%' : 220, flex: isMobile ? undefined : 'none' }}
        />
        <DatePicker.RangePicker
          size="small"
          value={dateRange}
          onChange={(dates) => setDateRange(dates as [Dayjs | null, Dayjs | null] | null)}
          style={{ width: isMobile ? '100%' : 220, flex: isMobile ? undefined : 'none' }}
        />
        <Space size={isMobile ? 4 : 8}>
          <Button size="small" type="primary" icon={<SearchOutlined />} onClick={handleSearch}>搜索</Button>
          <Button size="small" icon={<ClearOutlined />} onClick={handleClear}>重置</Button>
        </Space>
      </div>

      {/* Table header */}
      <div
        className="section-header"
        style={{
          padding: '6px 16px', background: token.colorFillQuaternary,
          fontSize: 12, color: token.colorTextTertiary,
          display: 'flex', alignItems: 'center',
          flexShrink: 0, overflowX: 'auto',
        }}
      >
        <span style={{ width: 28, flexShrink: 0 }} />
        {COLUMNS.map((col) => (
          <span key={col.key} data-col={col.key} style={{ ...colStyle(col), position: 'relative', overflow: 'visible' }}>
            {col.label}
            {!isMobile && (
              <span
                onMouseDown={(e) => handleResizeStart(col.key, e)}
                style={{
                  position: 'absolute', right: -3, top: -2, bottom: -2, width: 6,
                  cursor: 'col-resize', zIndex: 1,
                }}
              />
            )}
          </span>
        ))}
      </div>

      {/* List */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {traceList.length === 0 && (
          <div className="empty-state" style={{ fontSize: 12 }}>
            暂无 Trace 数据
          </div>
        )}
        {traceList.map((item) => (
          <div
            key={item.trace_id}
            onClick={() => selectTrace(item.trace_id)}
            style={{
              padding: '6px 16px',
              cursor: 'pointer',
              background: selectedTraceId === item.trace_id ? token.colorPrimaryBg : token.colorBgContainer,
              borderBottom: `1px solid ${token.colorBorderSecondary}`,
              display: 'flex',
              alignItems: 'center',
              fontSize: 13,
              transition: 'background 0.15s',
              minWidth: 'max-content',
            }}
            onMouseEnter={(e) => { if (selectedTraceId !== item.trace_id) e.currentTarget.style.background = token.colorFillQuaternary; }}
            onMouseLeave={(e) => { if (selectedTraceId !== item.trace_id) e.currentTarget.style.background = token.colorBgContainer; }}
          >
            <span style={{ width: 28, flexShrink: 0 }}>
              <Checkbox
                checked={selectedIds.includes(item.trace_id)}
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => toggleSelect(item.trace_id, e.target.checked)}
                size="small"
              />
            </span>
            {COLUMNS.map((col) => (
              <span key={col.key} data-col={col.key} style={{
                ...colStyle(col),
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {renderCell(item, col.key)}
              </span>
            ))}
          </div>
        ))}
      </div>

      {/* Bottom bar */}
      <div className="table-footer" style={{ flexWrap: isMobile ? 'wrap' : undefined, gap: isMobile ? 4 : undefined }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Checkbox
            checked={allSelected}
            indeterminate={hasSelection && !allSelected}
            onChange={(e) => setSelectedIds(e.target.checked ? traceList.map((t) => t.trace_id) : [])}
          >
            {isMobile ? '' : '全选'}
          </Checkbox>
          {hasSelection && (
            <>
              <span style={{ color: token.colorPrimary }}>{selectedIds.length} 项</span>
              <Popconfirm title={`确定删除 ${selectedIds.length} 条 trace？`} onConfirm={handleBatchDelete}>
                <Button type="primary" danger size="small" icon={<DeleteOutlined />}>{isMobile ? '' : '删除'}</Button>
              </Popconfirm>
            </>
          )}
          {!hasSelection && <span>共 {traceTotal} 条</span>}
        </div>
        {traceTotal > PAGE_SIZE && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Button size="small" disabled={tracePage <= 1} onClick={() => setPage(tracePage - 1)}>上一页</Button>
            <span>{tracePage}</span>
            <Button size="small" disabled={tracePage * PAGE_SIZE >= traceTotal} onClick={() => setPage(tracePage + 1)}>下一页</Button>
          </div>
        )}
      </div>
    </div>
  );
}
