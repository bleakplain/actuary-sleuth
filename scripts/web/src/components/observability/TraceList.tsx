import { useState } from 'react';
import { Input, Select, Button, Checkbox, Badge, Space, DatePicker, Popconfirm, message } from 'antd';
import { SearchOutlined, DeleteOutlined, ClearOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useObservabilityStore } from '../../stores/observabilityStore';
import type { Dayjs } from 'dayjs';

interface Props {
  onCleanupOpen: () => void;
}

export default function TraceList({ onCleanupOpen }: Props) {
  const {
    traceList, traceTotal, tracePage,
    selectedTraceId, selectTrace,
    loadTraces, setPage, deleteTraces,
  } = useObservabilityStore();

  const [traceIdFilter, setTraceIdFilter] = useState('');
  const [convIdFilter, setConvIdFilter] = useState('');
  const [msgIdFilter, setMsgIdFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  const handleSearch = () => {
    setSelectedIds([]);
    setPage(1);
    loadTraces({
      trace_id: traceIdFilter || undefined,
      conversation_id: convIdFilter || undefined,
      message_id: msgIdFilter || undefined,
      status: statusFilter || undefined,
      start_date: dateRange?.[0]?.format('YYYY-MM-DD') || undefined,
      end_date: dateRange?.[1]?.format('YYYY-MM-DD') || undefined,
      page: 1,
    });
  };

  const handleClear = () => {
    setTraceIdFilter('');
    setConvIdFilter('');
    setMsgIdFilter('');
    setStatusFilter('');
    setDateRange(null);
    setSelectedIds([]);
    setPage(1);
    loadTraces({ page: 1 });
  };

  const handleBatchDelete = () => {
    deleteTraces(selectedIds);
    setSelectedIds([]);
    message.success('已删除');
  };

  const toggleSelect = (id: string, checked: boolean) => {
    setSelectedIds((prev) => checked ? [...prev, id] : prev.filter((x) => x !== id));
  };

  const allSelected = traceList.length > 0 && traceList.every((t) => selectedIds.includes(t.trace_id));

  return (
    <div style={{ width: 360, borderRight: '1px solid #f0f0f0', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '10px 12px', fontWeight: 600, fontSize: 14, borderBottom: '1px solid #f0f0f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span><ThunderboltOutlined style={{ marginRight: 6 }} />Trace 列表</span>
        <Button type="link" size="small" onClick={onCleanupOpen} style={{ padding: 0, fontSize: 12 }}>
          <DeleteOutlined /> 清理
        </Button>
      </div>

      <div style={{ padding: '8px 12px', borderBottom: '1px solid #f0f0f0', overflow: 'auto', flexShrink: 0 }}>
        <Space direction="vertical" size={6} style={{ width: '100%' }}>
          <Input placeholder="Trace ID" size="small" value={traceIdFilter} onChange={(e) => setTraceIdFilter(e.target.value)} allowClear />
          <Input placeholder="Conversation ID" size="small" value={convIdFilter} onChange={(e) => setConvIdFilter(e.target.value)} allowClear />
          <Input placeholder="Message ID" size="small" value={msgIdFilter} onChange={(e) => setMsgIdFilter(e.target.value)} allowClear />
          <Select placeholder="状态" size="small" value={statusFilter || undefined} onChange={setStatusFilter} allowClear style={{ width: '100%' }} options={[
            { label: '成功 (ok)', value: 'ok' },
            { label: '错误 (error)', value: 'error' },
          ]} />
          <DatePicker.RangePicker size="small" style={{ width: '100%' }} value={dateRange} onChange={(dates) => setDateRange(dates as [Dayjs | null, Dayjs | null] | null)} />
          <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
            <Button size="small" icon={<ClearOutlined />} onClick={handleClear}>重置</Button>
            <Button size="small" type="primary" icon={<SearchOutlined />} onClick={handleSearch}>搜索</Button>
          </Space>
        </Space>
      </div>

      {selectedIds.length > 0 && (
        <div style={{ padding: '6px 12px', borderBottom: '1px solid #f0f0f0' }}>
          <Popconfirm title={`确定删除 ${selectedIds.length} 条 trace？`} onConfirm={handleBatchDelete}>
            <Button type="primary" danger size="small" icon={<DeleteOutlined />} block>
              删除选中 ({selectedIds.length})
            </Button>
          </Popconfirm>
        </div>
      )}

      <div style={{ flex: 1, overflow: 'auto' }}>
        {traceList.length > 0 && (
          <div style={{ padding: '4px 12px', borderBottom: '1px solid #f5f5f5' }}>
            <Checkbox checked={allSelected} onChange={(e) => {
              setSelectedIds(e.target.checked ? traceList.map((t) => t.trace_id) : []);
            }} style={{ fontSize: 11, color: '#8c8c8c' }}>
              全选
            </Checkbox>
          </div>
        )}
        {traceList.map((item) => (
          <div
            key={item.trace_id}
            onClick={() => selectTrace(item.trace_id)}
            style={{
              padding: '6px 12px',
              cursor: 'pointer',
              background: selectedTraceId === item.trace_id ? '#e6f4ff' : '#fff',
              borderBottom: '1px solid #f5f5f5',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <Checkbox
              checked={selectedIds.includes(item.trace_id)}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => toggleSelect(item.trace_id, e.target.checked)}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <Badge status={item.status === 'error' ? 'error' : 'success'} />
                <span style={{ fontSize: 12, fontFamily: "'SF Mono', monospace", overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {item.trace_id}
                </span>
              </div>
              <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 2 }}>
                {(item.total_duration_ms / 1000).toFixed(1)}s · {item.span_count} spans · {item.created_at?.slice(5, 16)}
              </div>
            </div>
          </div>
        ))}
        {traceList.length === 0 && (
          <div style={{ padding: '24px 12px', textAlign: 'center', color: '#bfbfbf', fontSize: 12 }}>
            暂无 Trace 数据
          </div>
        )}
      </div>

      {traceTotal > 20 && (
        <div style={{ padding: '8px 12px', borderTop: '1px solid #f0f0f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12, color: '#8c8c8c' }}>
          <span>共 {traceTotal} 条</span>
          <Space size={4}>
            <Button size="small" disabled={tracePage <= 1} onClick={() => setPage(tracePage - 1)}>上一页</Button>
            <span>{tracePage}</span>
            <Button size="small" disabled={tracePage * 20 >= traceTotal} onClick={() => setPage(tracePage + 1)}>下一页</Button>
          </Space>
        </div>
      )}
    </div>
  );
}
