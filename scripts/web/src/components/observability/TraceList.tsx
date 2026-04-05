import { useState, useMemo } from 'react';
import { Input, Button, Checkbox, Popconfirm, message } from 'antd';
import { SearchOutlined, DeleteOutlined, ClearOutlined } from '@ant-design/icons';
import { useObservabilityStore } from '../../stores/observabilityStore';
import type { Dayjs } from 'dayjs';
import { DatePicker } from 'antd';

const PAGE_SIZE = 20;

export default function TraceList() {
  const {
    traceList, traceTotal, tracePage,
    selectedTraceId, selectTrace,
    loadTraces, setPage, deleteTraces,
  } = useObservabilityStore();

  const [traceIdFilter, setTraceIdFilter] = useState('');
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Filter bar */}
      <div style={{
        padding: '10px 16px', borderBottom: '1px solid #f0f0f0',
        display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0,
      }}>
        <Input
          placeholder="Trace ID"
          size="small"
          value={traceIdFilter}
          onChange={(e) => setTraceIdFilter(e.target.value)}
          onPressEnter={handleSearch}
          allowClear
          onClear={handleSearch}
          style={{ width: 220 }}
        />
        <DatePicker.RangePicker
          size="small"
          value={dateRange}
          onChange={(dates) => setDateRange(dates as [Dayjs | null, Dayjs | null] | null)}
          style={{ width: 220 }}
        />
        <Button size="small" type="primary" icon={<SearchOutlined />} onClick={handleSearch}>搜索</Button>
        <Button size="small" icon={<ClearOutlined />} onClick={handleClear}>重置</Button>
      </div>

      {/* Table header */}
      <div style={{
        padding: '6px 16px', borderBottom: '1px solid #f0f0f0', background: '#fafafa',
        display: 'flex', alignItems: 'center', fontSize: 12, color: '#8c8c8c',
        flexShrink: 0,
      }}>
        <span style={{ width: 28, flexShrink: 0 }} />
        <span style={{ width: 130, flexShrink: 0 }}>Time</span>
        <span style={{ width: 110, flexShrink: 0 }}>Trace ID</span>
        <span style={{ flex: 1, paddingLeft: 12 }}>Name</span>
        <span style={{ width: 56, flexShrink: 0 }}>Spans</span>
        <span style={{ width: 68, flexShrink: 0 }}>LLM Calls</span>
        <span style={{ width: 100, flexShrink: 0 }}>Latency</span>
      </div>

      {/* List */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {traceList.length === 0 && (
          <div style={{ padding: '40px 16px', textAlign: 'center', color: '#bfbfbf', fontSize: 12 }}>
            暂无 Trace 数据
          </div>
        )}
        {traceList.map((item) => {
          return (
            <div
              key={item.trace_id}
              onClick={() => selectTrace(item.trace_id)}
              style={{
                padding: '6px 16px',
                cursor: 'pointer',
                background: selectedTraceId === item.trace_id ? '#e6f4ff' : '#fff',
                borderBottom: '1px solid #f5f5f5',
                display: 'flex',
                alignItems: 'center',
                fontSize: 13,
                transition: 'background 0.15s',
              }}
              onMouseEnter={(e) => { if (selectedTraceId !== item.trace_id) e.currentTarget.style.background = '#fafafa'; }}
              onMouseLeave={(e) => { if (selectedTraceId !== item.trace_id) e.currentTarget.style.background = '#fff'; }}
            >
              <span style={{ width: 28, flexShrink: 0 }}>
                <Checkbox
                  checked={selectedIds.includes(item.trace_id)}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => toggleSelect(item.trace_id, e.target.checked)}
                  size="small"
                />
              </span>
              <span style={{
                width: 130, flexShrink: 0,
                color: '#8c8c8c', fontSize: 12, fontVariantNumeric: 'tabular-nums',
              }}>
                {fmtTime(item.created_at)}
              </span>
              <span style={{
                width: 110, flexShrink: 0,
                fontFamily: "'SF Mono', 'Menlo', 'Consolas', monospace",
                fontSize: 12, color: '#262626',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                title: item.trace_id,
              }}>
                {item.trace_id}
              </span>
              <span style={{
                flex: 1, paddingLeft: 12,
                color: '#262626', fontSize: 13,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                title: item.trace_name || undefined,
              }}>
                {item.trace_name || '-'}
              </span>
              <span style={{ width: 56, flexShrink: 0, color: '#8c8c8c', fontSize: 12 }}>
                {item.span_count}
              </span>
              <span style={{ width: 68, flexShrink: 0, color: '#8c8c8c', fontSize: 12 }}>
                {item.llm_call_count}
              </span>
              <span style={{
                width: 100, flexShrink: 0,
                color: item.status === 'error' ? '#ff4d4f' : '#52c41a',
                fontSize: 12, fontVariantNumeric: 'tabular-nums',
                position: 'relative',
              }}>
                <span style={{
                  position: 'absolute', left: 0, top: 4, bottom: 4,
                  width: `${Math.max((item.total_duration_ms / maxDuration) * 100, 2)}%`,
                  background: item.status === 'error' ? 'rgba(255,77,79,0.1)' : 'rgba(82,196,26,0.1)',
                  borderRadius: 2,
                }} />
                <span style={{ position: 'relative' }}>{fmtDuration(item.total_duration_ms)}</span>
              </span>
            </div>
          );
        })}
      </div>

      {/* Bottom bar: selection + pagination */}
      <div style={{
        padding: '8px 16px', borderTop: '1px solid #f0f0f0',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        fontSize: 12, color: '#8c8c8c', flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Checkbox
            checked={allSelected}
            indeterminate={hasSelection && !allSelected}
            onChange={(e) => setSelectedIds(e.target.checked ? traceList.map((t) => t.trace_id) : [])}
          >
            全选
          </Checkbox>
          {hasSelection && (
            <>
              <span style={{ color: '#1677ff' }}>{selectedIds.length} 项</span>
              <Popconfirm title={`确定删除 ${selectedIds.length} 条 trace？`} onConfirm={handleBatchDelete}>
                <Button type="primary" danger size="small" icon={<DeleteOutlined />}>删除</Button>
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
