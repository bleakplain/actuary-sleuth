import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Card, Table, Button, Space, Select, Tag, Modal, Form, Input,
  Typography, message, Row, Col, Popconfirm, Progress, Descriptions, Tabs,
} from 'antd';
import {
  PlusOutlined, ImportOutlined, SaveOutlined, RollbackOutlined,
  PlayCircleOutlined, DownloadOutlined, SwapOutlined,
} from '@ant-design/icons';
import * as evalApi from '../api/eval';
import MetricsChart, { formatMetric } from '../components/MetricsChart';
import type { EvalSample, EvalSnapshot, Evaluation, SampleResult, MetricsDiff } from '../types';

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

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '等待中' },
  running: { color: 'processing', label: '运行中' },
  completed: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '失败' },
};

export default function EvalPage() {
  const [activeTab, setActiveTab] = useState('dataset');

  const [samples, setSamples] = useState<EvalSample[]>([]);
  const [snapshots, setSnapshots] = useState<EvalSnapshot[]>([]);
  const [samplesLoading, setSamplesLoading] = useState(false);
  const [filters, setFilters] = useState<{ question_type?: string; difficulty?: string; topic?: string }>({});
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingSample, setEditingSample] = useState<Partial<EvalSample> | null>(null);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importText, setImportText] = useState('');
  const [snapshotModalOpen, setSnapshotModalOpen] = useState(false);
  const [snapshotName, setSnapshotName] = useState('');
  const [form] = Form.useForm();

  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [evaluationsLoading, setEvaluationsLoading] = useState(false);
  const [selectedEvaluation, setSelectedEvaluation] = useState<Evaluation | null>(null);
  const [report, setReport] = useState<Record<string, Record<string, number>> | null>(null);
  const [details, setDetails] = useState<SampleResult[]>([]);
  const [compareModalOpen, setCompareModalOpen] = useState(false);
  const [compareIds, setCompareIds] = useState<{ baseline: string; compare: string }>({ baseline: '', compare: '' });
  const [compareResult, setCompareResult] = useState<{
    metrics_diff: Record<string, MetricsDiff>;
    improved: string[];
    regressed: string[];
  } | null>(null);

  const flattenedMetrics = useMemo((): Record<string, number> => {
    const result: Record<string, number> = {};
    if (report) {
      for (const [section, metrics] of Object.entries(report)) {
        if (typeof metrics === 'object' && metrics !== null) {
          for (const [key, val] of Object.entries(metrics)) {
            if (typeof val === 'number') {
              result[`${section}.${key}`] = val;
            }
          }
        }
      }
    }
    return result;
  }, [report]);

  const completedEvaluationsOptions = useMemo(() =>
    evaluations.filter((e) => e.status === 'completed').map((e) => ({
      value: e.id, label: `${e.id} (${e.mode}, ${e.started_at?.slice(0, 10)})`,
    })),
    [evaluations]
  );

  const load_samples = useCallback(async () => {
    setSamplesLoading(true);
    try {
      const [sample_list, snapshot_list] = await Promise.all([
        evalApi.fetchEvalSamples(filters),
        evalApi.fetchSnapshots(),
      ]);
      setSamples(sample_list);
      setSnapshots(snapshot_list);
    } catch (err) {
      message.error(`加载失败: ${err}`);
    } finally {
      setSamplesLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    if (activeTab === 'dataset') load_samples();
  }, [activeTab, load_samples]);

  const create_sample = () => {
    setEditingSample(null);
    form.resetFields();
    setEditModalOpen(true);
  };

  const edit_sample = (sample: EvalSample) => {
    setEditingSample(sample);
    form.setFieldsValue(sample);
    setEditModalOpen(true);
  };

  const save_sample = async () => {
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
      load_samples();
    } catch (err) {
      message.error(`保存失败: ${err}`);
    }
  };

  const delete_sample = async (sample_id: string) => {
    try {
      await evalApi.deleteEvalSample(sample_id);
      message.success('删除成功');
      load_samples();
    } catch (err) {
      message.error(`删除失败: ${err}`);
    }
  };

  const import_samples = async () => {
    try {
      const data = JSON.parse(importText);
      const items = Array.isArray(data) ? data : (data.samples || []);
      const result = await evalApi.importEvalSamples(items);
      message.success(`导入 ${result.imported} 条，跳过 ${result.total - result.imported} 条`);
      setImportModalOpen(false);
      setImportText('');
      load_samples();
    } catch (err) {
      message.error(`导入失败: ${err}`);
    }
  };

  const create_snapshot = async () => {
    if (!snapshotName.trim()) {
      message.warning('请输入快照名称');
      return;
    }
    try {
      await evalApi.createSnapshot(snapshotName, '');
      message.success('快照创建成功');
      setSnapshotModalOpen(false);
      setSnapshotName('');
      load_samples();
    } catch (err) {
      message.error(`创建失败: ${err}`);
    }
  };

  const restore_snapshot = async (snapshot_id: string) => {
    try {
      const result = await evalApi.restoreSnapshot(snapshot_id);
      message.success(`已恢复 ${result.restored} 条数据`);
      load_samples();
    } catch (err) {
      message.error(`恢复失败: ${err}`);
    }
  };

  const datasetColumns = [
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
      render: (_: undefined, sample: EvalSample) => (
        <Space>
          <Button type="link" size="small" onClick={() => edit_sample(sample)}>编辑</Button>
          <Popconfirm title="确定删除？" onConfirm={() => delete_sample(sample.id)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const refresh_evaluation_history = useCallback(async () => {
    setEvaluationsLoading(true);
    try {
      const data = await evalApi.fetchEvaluations();
      setEvaluations(data);
    } catch (err) {
      message.error(`加载失败: ${err}`);
    } finally {
      setEvaluationsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'runs') refresh_evaluation_history();
  }, [activeTab, refresh_evaluation_history]);

  useEffect(() => {
    if (activeTab !== 'runs') return;
    const pending_evaluations = evaluations.filter((e) => e.status === 'running' || e.status === 'pending');
    if (pending_evaluations.length === 0) return;
    const timer = setInterval(async () => {
      await refresh_evaluation_history();
    }, 3000);
    return () => clearInterval(timer);
  }, [activeTab, evaluations, refresh_evaluation_history]);

  const start_evaluation = async (mode: 'retrieval' | 'generation' | 'full') => {
    try {
      const { evaluation_id } = await evalApi.createEvaluation({ mode, top_k: 5 });
      message.success(`评估任务已创建: ${evaluation_id}`);
      refresh_evaluation_history();
    } catch (err) {
      message.error(`启动失败: ${err}`);
    }
  };

  const view_evaluation = async (evaluation: Evaluation) => {
    setSelectedEvaluation(evaluation);
    if (evaluation.status === 'completed') {
      try {
        const [rpt, det] = await Promise.all([
          evalApi.fetchEvaluationReport(evaluation.id),
          evalApi.fetchEvaluationDetails(evaluation.id),
        ]);
        setReport(rpt);
        setDetails(det.details);
      } catch (err) {
        message.error(`加载报告失败: ${err}`);
      }
    } else {
      setReport(null);
      setDetails([]);
    }
  };

  const download_eval_report = async (eval_id: string, format: 'json' | 'md') => {
    try {
      const blob = await evalApi.exportEvaluationReport(eval_id, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `eval_report_${eval_id}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      message.error(`导出失败: ${err}`);
    }
  };

  const compare_eval_results = async () => {
    if (!compareIds.baseline || !compareIds.compare) {
      message.warning('请选择两个评估');
      return;
    }
    try {
      const result = await evalApi.compareEvaluations(compareIds.baseline, compareIds.compare);
      setCompareResult(result);
    } catch (err) {
      message.error(`对比失败: ${err}`);
    }
  };

  const evaluationColumns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 140, ellipsis: true },
    {
      title: '模式', dataIndex: 'mode', key: 'mode', width: 100,
      render: (m: string) => <Tag>{m}</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (s: string) => {
        const info = STATUS_MAP[s] || { color: 'default', label: s };
        return <Tag color={info.color}>{info.label}</Tag>;
      },
    },
    {
      title: '进度', key: 'progress', width: 150,
      render: (_: undefined, e: Evaluation) => {
        if (e.status === 'completed') return <Text>100%</Text>;
        if (e.total > 0) return <Progress percent={Math.round((e.progress / e.total) * 100)} size="small" />;
        return <Text type="secondary">-</Text>;
      },
    },
    { title: '启动时间', dataIndex: 'started_at', key: 'started_at', width: 180, ellipsis: true },
    { title: '完成时间', dataIndex: 'finished_at', key: 'finished_at', width: 180 },
  ];

  const detailColumns = [
    { title: '样本ID', dataIndex: 'sample_id', key: 'sample_id', width: 80 },
    {
      title: 'Precision', key: 'precision', width: 90,
      render: (_: undefined, r: SampleResult) => formatMetric(r.retrieval_metrics.precision),
    },
    {
      title: 'Recall', key: 'recall', width: 90,
      render: (_: undefined, r: SampleResult) => formatMetric(r.retrieval_metrics.recall),
    },
    {
      title: 'MRR', key: 'mrr', width: 90,
      render: (_: undefined, r: SampleResult) => formatMetric(r.retrieval_metrics.mrr),
    },
    {
      title: 'NDCG', key: 'ndcg', width: 90,
      render: (_: undefined, r: SampleResult) => formatMetric(r.retrieval_metrics.ndcg),
    },
    {
      title: 'Faithfulness', key: 'faithfulness', width: 110,
      render: (_: undefined, r: SampleResult) => formatMetric(r.generation_metrics.faithfulness),
    },
  ];

  return (
    <div>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'dataset',
            label: '数据集',
            children: (
              <>
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
                    onPressEnter={load_samples}
                  />
                </Space>

                <Space style={{ marginBottom: 16 }}>
                  <Button type="primary" icon={<PlusOutlined />} onClick={create_sample}>新增</Button>
                  <Button icon={<ImportOutlined />} onClick={() => setImportModalOpen(true)}>批量导入</Button>
                  <Button icon={<SaveOutlined />} onClick={() => setSnapshotModalOpen(true)}>创建快照</Button>
                </Space>

                <Row gutter={16}>
                  <Col span={16}>
                    <Card>
                      <Table
                        dataSource={samples}
                        columns={datasetColumns}
                        rowKey="id"
                        loading={samplesLoading}
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
                        snapshots.map((snapshot) => (
                          <div key={snapshot.id} style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div>
                              <Text strong>{snapshot.name}</Text>
                              <Text type="secondary" style={{ marginLeft: 8 }}>{snapshot.sample_count} 条</Text>
                              <br />
                              <Text type="secondary" style={{ fontSize: 12 }}>{snapshot.created_at}</Text>
                            </div>
                            <Popconfirm title={`确定恢复到 ${snapshot.name}？当前数据将被覆盖。`} onConfirm={() => restore_snapshot(snapshot.id)}>
                              <Button type="link" size="small" icon={<RollbackOutlined />}>恢复</Button>
                            </Popconfirm>
                          </div>
                        ))
                      )}
                    </Card>
                  </Col>
                </Row>
              </>
            ),
          },
          {
            key: 'runs',
            label: '评估',
            children: (
              <>
                <Space style={{ marginBottom: 16 }}>
                  <Button icon={<PlayCircleOutlined />} onClick={() => start_evaluation('retrieval')}>检索评估</Button>
                  <Button icon={<PlayCircleOutlined />} onClick={() => start_evaluation('generation')}>生成评估</Button>
                  <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => start_evaluation('full')}>完整评估</Button>
                  <Button icon={<SwapOutlined />} onClick={() => setCompareModalOpen(true)}>版本对比</Button>
                </Space>

                <Row gutter={16}>
                  <Col span={10}>
                    <Card title="评估历史" size="small">
                      <Table
                        dataSource={evaluations}
                        columns={evaluationColumns}
                        rowKey="id"
                        loading={evaluationsLoading}
                        size="small"
                        scroll={{ y: 400 }}
                        pagination={{ pageSize: 15 }}
                        onRow={(evaluation) => ({
                          onClick: () => view_evaluation(evaluation),
                          style: {
                            cursor: 'pointer',
                            background: selectedEvaluation?.id === evaluation.id ? '#e6f4ff' : undefined,
                          },
                        })}
                      />
                    </Card>
                  </Col>

                  <Col span={14}>
                    {selectedEvaluation ? (
                      <>
                        <Descriptions title={`评估报告 - ${selectedEvaluation.id}`} size="small" style={{ marginBottom: 16 }}>
                          <Descriptions.Item label="模式">{selectedEvaluation.mode}</Descriptions.Item>
                          <Descriptions.Item label="状态">
                            <Tag color={STATUS_MAP[selectedEvaluation.status]?.color}>{STATUS_MAP[selectedEvaluation.status]?.label}</Tag>
                          </Descriptions.Item>
                          <Descriptions.Item label="启动时间">{selectedEvaluation.started_at}</Descriptions.Item>
                          {selectedEvaluation.status === 'completed' && (
                            <Descriptions.Item label="操作">
                              <Space>
                                <Button size="small" icon={<DownloadOutlined />}
                                  onClick={() => download_eval_report(selectedEvaluation.id, 'json')}>JSON</Button>
                                <Button size="small" icon={<DownloadOutlined />}
                                  onClick={() => download_eval_report(selectedEvaluation.id, 'md')}>Markdown</Button>
                              </Space>
                            </Descriptions.Item>
                          )}
                        </Descriptions>

                        {report && (
                          <>
                            <MetricsChart metrics={flattenedMetrics} title="聚合指标" />
                            <Card title="逐题详情" size="small" style={{ marginTop: 16 }}>
                              <Table
                                dataSource={details}
                                columns={detailColumns}
                                rowKey="id"
                                size="small"
                                pagination={{ pageSize: 20 }}
                                expandable={{
                                  expandedRowRender: (record) => (
                                    <div>
                                      <Text strong>生成回答：</Text>
                                      <div style={{ marginTop: 4, padding: 8, background: '#f5f5f5', borderRadius: 4 }}>
                                        {record.generated_answer || '-'}
                                      </div>
                                      {record.retrieved_docs.length > 0 && (
                                        <>
                                          <Text strong style={{ marginTop: 8, display: 'block' }}>检索结果：</Text>
                                          {record.retrieved_docs.map((doc, i) => (
                                            <div key={i} style={{ padding: 4, fontSize: 13 }}>
                                              [{i + 1}] {doc.law_name} {doc.article_number}
                                            </div>
                                          ))}
                                        </>
                                      )}
                                    </div>
                                  ),
                                }}
                              />
                            </Card>
                          </>
                        )}
                      </>
                    ) : (
                      <Card style={{ textAlign: 'center', padding: 40 }}>
                        <Text type="secondary">选择一个评估查看详情</Text>
                      </Card>
                    )}
                  </Col>
                </Row>
              </>
            ),
          },
        ]}
      />

      <Modal
        title={editingSample ? '编辑评测问题' : '新增评测问题'}
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={save_sample}
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
        onOk={import_samples}
        width={600}
      >
        <Text type="secondary">粘贴 JSON 数组或 {"{samples: [...]}"} 格式</Text>
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
        onOk={create_snapshot}
      >
        <Input
          placeholder="快照名称，如 v1.0"
          value={snapshotName}
          onChange={(e) => setSnapshotName(e.target.value)}
          onPressEnter={create_snapshot}
        />
      </Modal>

      <Modal
        title="版本对比"
        open={compareModalOpen}
        onCancel={() => { setCompareModalOpen(false); setCompareResult(null); }}
        width={700}
        footer={null}
      >
        <Space style={{ marginBottom: 16 }}>
          <Select
            placeholder="基准版本" style={{ width: 200 }}
            value={compareIds.baseline || undefined}
            onChange={(v) => setCompareIds({ ...compareIds, baseline: v })}
            options={completedEvaluationsOptions}
          />
          <span>vs</span>
          <Select
            placeholder="对比版本" style={{ width: 200 }}
            value={compareIds.compare || undefined}
            onChange={(v) => setCompareIds({ ...compareIds, compare: v })}
            options={completedEvaluationsOptions}
          />
          <Button type="primary" onClick={compare_eval_results}>对比</Button>
        </Space>

        {compareResult && (
          <Table
            dataSource={Object.entries(compareResult.metrics_diff || {}).map(([key, val]) => ({
              key,
              metric: key,
              ...val,
              trend: val.delta > 0 ? '\u2191' : val.delta < 0 ? '\u2193' : '\u2192',
            }))}
            columns={[
              { title: '指标', dataIndex: 'metric', key: 'metric' },
              { title: '基准', dataIndex: 'baseline', key: 'baseline', render: (v: number) => (v * 100).toFixed(2) + '%' },
              { title: '对比', dataIndex: 'compare', key: 'compare', render: (v: number) => (v * 100).toFixed(2) + '%' },
              { title: '变化', dataIndex: 'pct_change', key: 'pct_change',
                render: (v: number) => <span style={{ color: v > 0 ? '#52c41a' : v < 0 ? '#ff4d4f' : '#999' }}>{v > 0 ? '+' : ''}{v.toFixed(1)}%</span> },
              { title: '趋势', dataIndex: 'trend', key: 'trend', width: 60,
                render: (v: string) => <span style={{ color: v === '\u2191' ? '#52c41a' : v === '\u2193' ? '#ff4d4f' : '#999', fontWeight: 600 }}>{v}</span> },
            ]}
            size="small"
            pagination={false}
          />
        )}
      </Modal>
    </div>
  );
}
