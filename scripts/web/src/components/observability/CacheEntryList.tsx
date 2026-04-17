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
