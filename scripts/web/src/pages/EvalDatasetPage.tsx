import { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Button, Space, Tag, Modal, Form, Input, Select,
  Typography, message, Row, Col, Popconfirm,
} from 'antd';
import {
  PlusOutlined, ImportOutlined, SaveOutlined, RollbackOutlined,
} from '@ant-design/icons';
import * as evalApi from '../api/eval';
import type { EvalSample, EvalSnapshot } from '../types';

const { Title, Text } = Typography;

const QUESTION_TYPE_OPTIONS = [
  { value: 'factual', label: 'FACTUAL（事实类）' },
  { value: 'multi_hop', label: 'MULTI_HOP（多跳推理）' },
  { value: 'negative', label: 'NEGATIVE（否定类）' },
  { value: 'colloquial', label: 'COLLOQUIAL（口语类）' },
];

const DIFFICULTY_OPTIONS = [
  { value: 'easy', label: 'easy' },
  { value: 'medium', label: 'medium' },
  { value: 'hard', label: 'hard' },
];

const TYPE_COLORS: Record<string, string> = {
  factual: 'blue', multi_hop: 'purple', negative: 'red', colloquial: 'green',
};

export default function EvalDatasetPage() {
  const [samples, setSamples] = useState<EvalSample[]>([]);
  const [snapshots, setSnapshots] = useState<EvalSnapshot[]>([]);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState<{ question_type?: string; difficulty?: string; topic?: string }>({});
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingSample, setEditingSample] = useState<Partial<EvalSample> | null>(null);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importText, setImportText] = useState('');
  const [snapshotModalOpen, setSnapshotModalOpen] = useState(false);
  const [snapshotName, setSnapshotName] = useState('');
  const [form] = Form.useForm();

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [s, snap] = await Promise.all([
        evalApi.fetchEvalSamples(filters),
        evalApi.fetchSnapshots(),
      ]);
      setSamples(s);
      setSnapshots(snap);
    } catch (err) {
      message.error(`加载失败: ${err}`);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleCreate = () => {
    setEditingSample(null);
    form.resetFields();
    setEditModalOpen(true);
  };

  const handleEdit = (record: EvalSample) => {
    setEditingSample(record);
    form.setFieldsValue(record);
    setEditModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      if (editingSample) {
        await evalApi.updateEvalSample(editingSample.id!, values);
        message.success('更新成功');
      } else {
        await evalApi.createEvalSample(values);
        message.success('创建成功');
      }
      setEditModalOpen(false);
      loadData();
    } catch (err) {
      message.error(`保存失败: ${err}`);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await evalApi.deleteEvalSample(id);
      message.success('删除成功');
      loadData();
    } catch (err) {
      message.error(`删除失败: ${err}`);
    }
  };

  const handleImport = async () => {
    try {
      const data = JSON.parse(importText);
      const items = Array.isArray(data) ? data : (data.samples || []);
      const result = await evalApi.importEvalSamples(items);
      message.success(`导入 ${result.imported} 条，跳过 ${result.total - result.imported} 条`);
      setImportModalOpen(false);
      setImportText('');
      loadData();
    } catch (err) {
      message.error(`导入失败: ${err}`);
    }
  };

  const handleCreateSnapshot = async () => {
    if (!snapshotName.trim()) {
      message.warning('请输入快照名称');
      return;
    }
    try {
      await evalApi.createSnapshot(snapshotName, '');
      message.success('快照创建成功');
      setSnapshotModalOpen(false);
      setSnapshotName('');
      loadData();
    } catch (err) {
      message.error(`创建失败: ${err}`);
    }
  };

  const handleRestore = async (snapId: string) => {
    try {
      const result = await evalApi.restoreSnapshot(snapId);
      message.success(`已恢复 ${result.restored} 条数据`);
      loadData();
    } catch (err) {
      message.error(`恢复失败: ${err}`);
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 80 },
    { title: '问题', dataIndex: 'question', key: 'question', ellipsis: true },
    {
      title: '类型', dataIndex: 'question_type', key: 'question_type', width: 140,
      render: (t: string) => <Tag color={TYPE_COLORS[t] || 'default'}>{t}</Tag>,
    },
    { title: '难度', dataIndex: 'difficulty', key: 'difficulty', width: 80 },
    { title: '主题', dataIndex: 'topic', key: 'topic', width: 100 },
    {
      title: '操作', key: 'action', width: 150,
      render: (_: undefined, record: EvalSample) => (
        <Space>
          <Button type="link" size="small" onClick={() => handleEdit(record)}>编辑</Button>
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>评估数据集管理</Title>

      <Space style={{ marginBottom: 16 }}>
        <Select
          placeholder="问题类型" allowClear style={{ width: 160 }}
          value={filters.question_type}
          onChange={(v) => setFilters({ ...filters, question_type: v })}
          options={QUESTION_TYPE_OPTIONS}
        />
        <Select
          placeholder="难度" allowClear style={{ width: 100 }}
          value={filters.difficulty}
          onChange={(v) => setFilters({ ...filters, difficulty: v })}
          options={DIFFICULTY_OPTIONS}
        />
        <Input
          placeholder="主题筛选" style={{ width: 120 }}
          value={filters.topic}
          onChange={(e) => setFilters({ ...filters, topic: e.target.value || undefined })}
          onPressEnter={loadData}
        />
      </Space>

      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新增</Button>
        <Button icon={<ImportOutlined />} onClick={() => setImportModalOpen(true)}>批量导入</Button>
        <Button icon={<SaveOutlined />} onClick={() => setSnapshotModalOpen(true)}>创建快照</Button>
      </Space>

      <Row gutter={16}>
        <Col span={16}>
          <Card>
            <Table
              dataSource={samples}
              columns={columns}
              rowKey="id"
              loading={loading}
              pagination={{ pageSize: 20 }}
              size="middle"
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card title="快照历史" size="small">
            {snapshots.length === 0 ? (
              <Text type="secondary">暂无快照</Text>
            ) : (
              snapshots.map((snap) => (
                <div key={snap.id} style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <Text strong>{snap.name}</Text>
                    <Text type="secondary" style={{ marginLeft: 8 }}>{snap.sample_count} 条</Text>
                    <br />
                    <Text type="secondary" style={{ fontSize: 12 }}>{snap.created_at}</Text>
                  </div>
                  <Popconfirm title={`确定恢复到 ${snap.name}？当前数据将被覆盖。`} onConfirm={() => handleRestore(snap.id)}>
                    <Button type="link" size="small" icon={<RollbackOutlined />}>恢复</Button>
                  </Popconfirm>
                </div>
              ))
            )}
          </Card>
        </Col>
      </Row>

      <Modal
        title={editingSample ? '编辑评测问题' : '新增评测问题'}
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={handleSave}
        width={600}
      >
        <Form form={form} layout="vertical">
          {!editingSample && (
            <Form.Item name="id" label="ID" rules={[{ required: true }]}>
              <Input placeholder="如 f031" />
            </Form.Item>
          )}
          <Form.Item name="question" label="问题" rules={[{ required: true }]}>
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="ground_truth" label="标准答案">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="question_type" label="问题类型" rules={[{ required: true }]}>
            <Select options={QUESTION_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="difficulty" label="难度">
            <Select options={DIFFICULTY_OPTIONS} />
          </Form.Item>
          <Form.Item name="topic" label="主题">
            <Input placeholder="如 健康保险" />
          </Form.Item>
          <Form.Item name="evidence_docs" label="证据文档（JSON 数组）">
            <Input.TextArea rows={2} placeholder='["01_保险法相关监管规定.md"]' />
          </Form.Item>
          <Form.Item name="evidence_keywords" label="证据关键词（JSON 数组）">
            <Input.TextArea rows={2} placeholder='["等待期", "180天"]' />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="批量导入"
        open={importModalOpen}
        onCancel={() => setImportModalOpen(false)}
        onOk={handleImport}
        width={600}
      >
        <Text type="secondary">粘贴 JSON 数组或 {'{"samples": [...]'} 格式</Text>
        <Input.TextArea
          rows={12}
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          placeholder='[{"id": "f031", "question": "...", ...}]'
          style={{ marginTop: 8, fontFamily: 'monospace' }}
        />
      </Modal>

      <Modal
        title="创建快照"
        open={snapshotModalOpen}
        onCancel={() => setSnapshotModalOpen(false)}
        onOk={handleCreateSnapshot}
      >
        <Input
          placeholder="快照名称，如 v1.0"
          value={snapshotName}
          onChange={(e) => setSnapshotName(e.target.value)}
          onPressEnter={handleCreateSnapshot}
        />
      </Modal>
    </div>
  );
}
