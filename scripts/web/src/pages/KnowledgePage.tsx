import { useState, useEffect, useCallback } from 'react';
import { Card, Table, Button, Space, Modal, Typography, message, Progress, Statistic, Row, Col, Popconfirm } from 'antd';
import { DatabaseOutlined, ReloadOutlined, ImportOutlined, EyeOutlined, SyncOutlined } from '@ant-design/icons';
import * as kbApi from '../api/knowledge';
import type { Document, IndexStatus } from '../types';

const { Title, Text, Paragraph } = Typography;

export default function KnowledgePage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewDoc, setPreviewDoc] = useState<{ name: string; content: string; total_chars: number } | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<string>('');

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [docs, status] = await Promise.all([kbApi.fetchDocuments(), kbApi.fetchIndexStatus()]);
      setDocuments(docs);
      setIndexStatus(status);
    } catch (err) {
      message.error(`加载失败: ${err}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    if (!taskId || taskStatus === 'completed' || taskStatus === 'failed') return;
    const timer = setInterval(async () => {
      try {
        const task = await kbApi.fetchTaskStatus(taskId);
        setTaskStatus(task.status);
        if (task.status === 'completed' || task.status === 'failed') {
          clearInterval(timer);
          if (task.status === 'completed') {
            message.success('操作完成');
            loadData();
          } else {
            message.error(`操作失败: ${task.progress}`);
          }
        }
      } catch {
        clearInterval(timer);
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [taskId, taskStatus, loadData]);

  const handleImport = async () => {
    try {
      const { task_id } = await kbApi.importDocuments('*.md');
      setTaskId(task_id);
      setTaskStatus('pending');
      message.info('开始导入...');
    } catch (err) {
      message.error(`导入失败: ${err}`);
    }
  };

  const handleRebuild = async () => {
    try {
      const { task_id } = await kbApi.rebuildIndex('*.md', true);
      setTaskId(task_id);
      setTaskStatus('pending');
      message.info('开始重建索引...');
    } catch (err) {
      message.error(`重建失败: ${err}`);
    }
  };

  const handlePreview = async (name: string) => {
    try {
      const doc = await kbApi.fetchDocumentPreview(name);
      setPreviewDoc(doc);
    } catch (err) {
      message.error(`预览失败: ${err}`);
    }
  };

  const columns = [
    { title: '文档名称', dataIndex: 'name', key: 'name', ellipsis: true },
    {
      title: '条款数',
      dataIndex: 'clause_count',
      key: 'clause_count',
      width: 100,
      sorter: (a: Document, b: Document) => a.clause_count - b.clause_count,
    },
    {
      title: '文件大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 120,
      render: (size: number) => (size > 1024 ? `${(size / 1024).toFixed(1)} KB` : `${size} B`),
      sorter: (a: Document, b: Document) => a.file_size - b.file_size,
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: string, record: Document) => (
        <Button type="link" icon={<EyeOutlined />} onClick={() => handlePreview(record.name)}>
          预览
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>知识库管理</Title>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic title="文档数量" value={documents.length} prefix={<DatabaseOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="向量库文档" value={indexStatus?.document_count || 0} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="BM25 状态"
              value={indexStatus?.bm25?.loaded ? '已加载' : '未加载'}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="向量库状态"
              value={indexStatus?.vector_db?.status || '未知'}
            />
          </Card>
        </Col>
      </Row>

      <Space style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          icon={<ImportOutlined />}
          onClick={handleImport}
          loading={taskStatus === 'running' || taskStatus === 'pending'}
        >
          导入文档
        </Button>
        <Popconfirm
          title="确定重建索引？此操作会重新处理所有文档。"
          onConfirm={handleRebuild}
        >
          <Button
            icon={<SyncOutlined />}
            loading={taskStatus === 'running' || taskStatus === 'pending'}
          >
            重建索引
          </Button>
        </Popconfirm>
        <Button icon={<ReloadOutlined />} onClick={loadData}>
          刷新
        </Button>
      </Space>

      {(taskStatus === 'pending' || taskStatus === 'running') && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Progress percent={taskStatus === 'pending' ? 0 : 50} status="active" />
          <Text type="secondary">
            {taskStatus === 'pending' ? '等待中...' : '处理中...'}
          </Text>
        </Card>
      )}

      <Card>
        <Table
          dataSource={documents}
          columns={columns}
          rowKey="name"
          loading={loading}
          pagination={{ pageSize: 20 }}
          size="middle"
        />
      </Card>

      <Modal
        title={previewDoc?.name || '文档预览'}
        open={!!previewDoc}
        onCancel={() => setPreviewDoc(null)}
        footer={null}
        width={700}
      >
        {previewDoc && (
          <>
            <Text type="secondary">总字符数: {previewDoc.total_chars}</Text>
            <Paragraph
              style={{ marginTop: 12, maxHeight: 500, overflow: 'auto', whiteSpace: 'pre-wrap' }}
            >
              {previewDoc.content}
            </Paragraph>
          </>
        )}
      </Modal>
    </div>
  );
}
