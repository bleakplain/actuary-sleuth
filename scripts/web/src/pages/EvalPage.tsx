import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Card, Table, Button, Space, Select, Tag, Modal, Form, Input, InputNumber, Switch,
  Typography, message, Row, Col, Popconfirm, Progress, Descriptions, Tabs, Tooltip,
  Divider, Checkbox,
} from 'antd';
import {
  PlusOutlined, ImportOutlined, SaveOutlined, RollbackOutlined,
  PlayCircleOutlined, DownloadOutlined, SwapOutlined,
  DeleteOutlined, CopyOutlined, CheckCircleOutlined, SearchOutlined, CloseCircleOutlined, LinkOutlined,
} from '@ant-design/icons';
import * as evalApi from '../api/eval';
import MetricsChart, { formatMetric, ComparisonChart, TrendChart } from '../components/MetricsChart';
import type { EvalSample, EvalSnapshot, Evaluation, EvalConfig, SampleResult, MetricsDiff, RegulationRef } from '../types';
import { resolveMetricMeta } from '../utils/evalMetrics';

const { Text } = Typography;

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

function ReviewTab() {
  const [samples, setSamples] = useState<EvalSample[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [stats, setStats] = useState<{ total: number; pending: number; approved: number }>({ total: 0, pending: 0, approved: 0 });
  const [kbQuery, setKbQuery] = useState('');
  const [kbResults, setKbResults] = useState<{
    doc_name: string; article: string; excerpt: string; relevance: number; hierarchy_path: string; chunk_id: string;
  }[]>([]);
  const [kbSearching, setKbSearching] = useState(false);
  const [editGroundTruth, setEditGroundTruth] = useState('');
  const [editReviewer, setEditReviewer] = useState('');
  const [editComment, setEditComment] = useState('');
  const [kbSearchDone, setKbSearchDone] = useState(false);

  const selected = samples.find((s) => s.id === selectedId) ?? null;

  const loadSamples = useCallback(async () => {
    setLoading(true);
    try {
      const [sampleList, statsData] = await Promise.all([
        evalApi.fetchEvalSamples(statusFilter ? { review_status: statusFilter } : undefined),
        evalApi.fetchReviewStats(),
      ]);
      setSamples(sampleList);
      setStats(statsData);
    } catch (err) {
      message.error(`加载失败: ${err}`);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { loadSamples(); }, [loadSamples]);

  useEffect(() => {
    if (selected) {
      setEditGroundTruth(selected.ground_truth);
      setEditReviewer(selected.reviewer);
      setEditComment(selected.review_comment);
    }
  }, [selected]);

  const handleSearchKb = async () => {
    if (!kbQuery.trim()) return;
    setKbSearching(true);
    setKbSearchDone(true);
    try {
      const results = await evalApi.searchKnowledgeBase(kbQuery.trim());
      setKbResults(results);
    } catch (err) {
      message.error(`搜索失败: ${err}`);
    } finally {
      setKbSearching(false);
    }
  };

  const handleSave = async () => {
    if (!selected) return;
    try {
      await evalApi.updateEvalSample(selected.id, { ...selected, ground_truth: editGroundTruth });
      message.success('已保存，审核状态重置为待审核');
      loadSamples();
    } catch (err) {
      message.error(`保存失败: ${err}`);
    }
  };

  const handleApprove = async () => {
    if (!selected) return;
    try {
      await evalApi.approveSample(selected.id, editReviewer, editComment);
      message.success('审核通过');
      loadSamples();
    } catch (err) {
      message.error(`审核失败: ${err}`);
    }
  };

  const handleAddRef = async (result: {
    doc_name: string; article: string; excerpt: string; relevance: number; hierarchy_path: string; chunk_id: string;
  }) => {
    if (!selected) return;
    const newRef: RegulationRef = {
      doc_name: result.doc_name,
      article: result.article,
      excerpt: result.excerpt,
      relevance: result.relevance,
      chunk_id: result.chunk_id,
    };
    const updatedRefs = [...(selected.regulation_refs || []), newRef];
    try {
      await evalApi.updateEvalSample(selected.id, { ...selected, regulation_refs: updatedRefs });
      message.success('已添加引用');
      loadSamples();
    } catch (err) {
      message.error(`添加引用失败: ${err}`);
    }
  };

  const handleRemoveRef = async (index: number) => {
    if (!selected) return;
    const updatedRefs = [...(selected.regulation_refs || [])];
    updatedRefs.splice(index, 1);
    try {
      await evalApi.updateEvalSample(selected.id, { ...selected, regulation_refs: updatedRefs });
      loadSamples();
    } catch (err) {
      message.error(`移除引用失败: ${err}`);
    }
  };

  return (
    <Row gutter={16}>
      <Col span={8}>
        <Card size="small" title={
          <Space>
            <span>样本列表</span>
            <Tag color="blue">{stats.pending} 待审核</Tag>
            <Tag color="green">{stats.approved} 已通过</Tag>
          </Space>
        }>
          <div style={{ marginBottom: 8 }}>
            <Select
              size="small"
              value={statusFilter || undefined}
              onChange={setStatusFilter}
              allowClear
              placeholder="筛选状态"
              style={{ width: '100%' }}
              options={[
                { value: 'pending', label: '待审核' },
                { value: 'approved', label: '已通过' },
              ]}
            />
          </div>
          <div style={{ overflow: 'auto', maxHeight: 'calc(100vh - 220px)' }}>
            <Table
              dataSource={samples}
              loading={loading}
              rowKey="id"
              size="small"
              pagination={false}
              scroll={{ y: 'calc(100vh - 280px)' }}
              onRow={(s) => ({
                onClick: () => setSelectedId(s.id),
                style: {
                  cursor: 'pointer',
                  background: selectedId === s.id ? '#e6f4ff' : undefined,
                },
              })}
              columns={[
                {
                  title: '状态', dataIndex: 'review_status', key: 'review_status', width: 60,
                  render: (v: string) => v === 'approved'
                    ? <Tag color="green" style={{ margin: 0 }}>通过</Tag>
                    : <Tag style={{ margin: 0 }}>待审</Tag>,
                },
                { title: '问题', dataIndex: 'question', key: 'question', ellipsis: true },
              ]}
            />
          </div>
        </Card>
      </Col>

      <Col span={16}>
        {selected ? (
          <Card size="small" title={
            <Space>
              <span>{selected.id}</span>
              <Tag color={TYPE_COLORS[selected.question_type] || 'default'}>{selected.question_type}</Tag>
              {selected.review_status === 'approved'
                ? <Tag color="green">已通过</Tag>
                : <Tag>待审核</Tag>}
            </Space>
          }>
            <div style={{ marginBottom: 12 }}>
              <Text type="secondary">问题：</Text>
              <div style={{ marginTop: 4 }}>{selected.question}</div>
            </div>

            <div style={{ marginBottom: 12 }}>
              <Text type="secondary">标准答案：</Text>
              <Input.TextArea
                rows={3}
                value={editGroundTruth}
                onChange={(e) => setEditGroundTruth(e.target.value)}
                style={{ marginTop: 4 }}
              />
            </div>

            <div style={{ marginBottom: 12 }}>
              <Text type="secondary">已引用法规：</Text>
              {(!selected.regulation_refs || selected.regulation_refs.length === 0) && (
                <div style={{ color: '#bfbfbf', fontSize: 13, marginTop: 4 }}>暂无引用</div>
              )}
              {selected.regulation_refs?.map((ref, idx) => (
                <div key={idx} style={{
                  marginTop: 4, padding: '6px 8px', background: '#fafafa',
                  border: '1px solid #f0f0f0', borderRadius: 4, fontSize: 13,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Space>
                      <Tag>{ref.article}</Tag>
                      <Text>{ref.doc_name}</Text>
                    </Space>
                    <Button type="text" size="small" danger icon={<CloseCircleOutlined />}
                      onClick={() => handleRemoveRef(idx)} />
                  </div>
                  <div style={{ marginTop: 2, color: '#666', fontSize: 12 }}>{ref.excerpt.slice(0, 150)}...</div>
                </div>
              ))}
            </div>

            <Divider style={{ margin: '12px 0' }} />

            <div style={{ marginBottom: 12 }}>
              <Text type="secondary">搜索法规库</Text>
              <div style={{ marginTop: 4, display: 'flex', gap: 8 }}>
                <Input
                  placeholder="输入关键词搜索..."
                  value={kbQuery}
                  onChange={(e) => setKbQuery(e.target.value)}
                  onPressEnter={handleSearchKb}
                />
                <Button icon={<SearchOutlined />} loading={kbSearching} onClick={handleSearchKb}>搜索</Button>
              </div>
            </div>

            {kbSearchDone && kbResults.length === 0 && !kbSearching && (
              <div style={{ color: '#bfbfbf', fontSize: 13, marginBottom: 12 }}>无搜索结果</div>
            )}

            {kbResults.length > 0 && (
              <div style={{ marginBottom: 12, maxHeight: 300, overflow: 'auto' }}>
                {kbResults.map((r, idx) => (
                  <div key={idx} style={{
                    padding: '6px 8px', marginBottom: 4, background: '#fafafa',
                    border: '1px solid #f0f0f0', borderRadius: 4, fontSize: 13,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Space>
                        <Tag>{r.article || '-'}</Tag>
                        <Text ellipsis style={{ maxWidth: 200 }}>{r.doc_name}</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>{r.relevance.toFixed(2)}</Text>
                      </Space>
                      <Button type="link" size="small" icon={<LinkOutlined />}
                        onClick={() => handleAddRef(r)}>引用</Button>
                    </div>
                    <div style={{ marginTop: 2, color: '#666', fontSize: 12 }}>{r.excerpt.slice(0, 120)}...</div>
                  </div>
                ))}
              </div>
            )}

            <Divider style={{ margin: '12px 0' }} />

            <div style={{ marginBottom: 12 }}>
              <Space>
                <span style={{ fontSize: 13 }}>审核人：</span>
                <Input size="small" style={{ width: 120 }} value={editReviewer}
                  onChange={(e) => setEditReviewer(e.target.value)} placeholder="姓名" />
              </Space>
            </div>
            <div style={{ marginBottom: 16 }}>
              <Space>
                <span style={{ fontSize: 13 }}>备注：</span>
                <Input size="small" style={{ width: 300 }} value={editComment}
                  onChange={(e) => setEditComment(e.target.value)} placeholder="审核备注（可选）" />
              </Space>
            </div>

            <div style={{ display: 'flex', gap: 8 }}>
              <Button onClick={handleSave}>保存</Button>
              <Button type="primary" onClick={handleApprove}>审核通过</Button>
            </div>
          </Card>
        ) : (
          <Card style={{ textAlign: 'center', paddingTop: 80 }}>
            <Text type="secondary">选择左侧的样本进行审核</Text>
          </Card>
        )}
      </Col>
    </Row>
  );
}

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
  const [evalConfigs, setEvalConfigs] = useState<EvalConfig[]>([]);
  const [selectedConfigId, setSelectedConfigId] = useState<number | null>(null);
  const [selectedEvaluation, setSelectedEvaluation] = useState<Evaluation | null>(null);
  const [selectedEvalIds, setSelectedEvalIds] = useState<string[]>([]);
  const [report, setReport] = useState<Record<string, Record<string, number>> | null>(null);
  const [details, setDetails] = useState<SampleResult[]>([]);
  const [compareModalOpen, setCompareModalOpen] = useState(false);
  const [compareIds, setCompareIds] = useState<{ baseline: string; compare: string }>({ baseline: '', compare: '' });
  const [compareResult, setCompareResult] = useState<{
    metrics_diff: Record<string, MetricsDiff>;
    improved: string[];
    regressed: string[];
  } | null>(null);
  const [dimensionFilter, setDimensionFilter] = useState<string>('overall');
  const [trendMetric, setTrendMetric] = useState<string>('retrieval.precision_at_k');
  const [trendData, setTrendData] = useState<{ run_id: string; label: string; value: number; timestamp: string }[]>([]);
  const [editForm] = Form.useForm();
  const rerankEnabled = Form.useWatch('rerank_enable_rerank', editForm) ?? true;

  // Config Tab state
  const [viewingConfig, setViewingConfig] = useState<EvalConfig | null>(null);
  const [viewingConfigJson, setViewingConfigJson] = useState<EvalConfig['config_json'] | null>(null);
  const [editingConfig, setEditingConfig] = useState<boolean>(false);
  const [configSelectedIds, setConfigSelectedIds] = useState<number[]>([]);
  const [configCompareOpen, setConfigCompareOpen] = useState(false);
  const [configCompareResult, setConfigCompareResult] = useState<{ param: string; values: (string | number | boolean)[] }[] | null>(null);

  const evalK = useMemo((): number => {
    if (!selectedEvaluation?.config?.rerank) return 5;
    return (selectedEvaluation.config.rerank as Record<string, unknown>).rerank_top_k as number ?? 5;
  }, [selectedEvaluation]);

  const flattenedMetrics = useMemo((): Record<string, number> => {
    const result: Record<string, number> = {};
    if (!report) return result;
    for (const [section, metrics] of Object.entries(report)) {
      if (typeof metrics !== 'object' || metrics === null || Array.isArray(metrics)) continue;
      let source: Record<string, unknown> = metrics;
      if (dimensionFilter !== 'overall' && 'by_type' in source) {
        const byType = source.by_type as Record<string, Record<string, number>> | undefined;
        if (byType && byType[dimensionFilter]) {
          source = byType[dimensionFilter];
        }
      }
      for (const [key, val] of Object.entries(source)) {
        if (key === 'by_type') continue;
        if (typeof val === 'number') {
          result[`${section}.${key}`] = val;
        }
      }
    }
    return result;
  }, [report, dimensionFilter]);

  const availableDimensions = useMemo((): string[] => {
    if (!report) return ['overall'];
    const dims = ['overall'];
    for (const section of Object.values(report)) {
      if (typeof section === 'object' && section !== null && 'by_type' in section) {
        const byType = (section as Record<string, unknown>).by_type as Record<string, Record<string, number>> | undefined;
        if (byType) {
          for (const qtype of Object.keys(byType)) {
            if (!dims.includes(qtype)) dims.push(qtype);
          }
        }
      }
    }
    return dims;
  }, [report]);

  const completedEvaluationsOptions = useMemo(() =>
    evaluations.filter((e) => e.status === 'completed').map((e) => ({
      value: e.id, label: `${e.id} (${e.mode}, ${e.started_at?.slice(0, 10)})`,
    })),
    [evaluations]
  );

  const [evalPage, setEvalPage] = useState(1);
  const EVAL_PAGE_SIZE = 15;

  const hasSelection = selectedEvalIds.length > 0;
  const evalPaged = useMemo(
    () => evaluations.slice((evalPage - 1) * EVAL_PAGE_SIZE, evalPage * EVAL_PAGE_SIZE),
    [evaluations, evalPage],
  );
  const evalAllSelected = evalPaged.length > 0 && evalPaged.every((e) => selectedEvalIds.includes(e.id));

  const toggle_eval_selection = (id: string, checked: boolean) => {
    setSelectedEvalIds((prev) => checked ? [...prev, id] : prev.filter((x) => x !== id));
  };

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
      setEvaluations((prev) => {
        if (prev.length !== data.length || prev[0]?.id !== data[0]?.id) {
          setEvalPage(1);
          setSelectedEvalIds([]);
        }
        return data;
      });
    } catch (err) {
      message.error(`加载失败: ${err}`);
    } finally {
      setEvaluationsLoading(false);
    }
  }, []);

  // Load configs for runs tab and configs tab
  useEffect(() => {
    if (activeTab === 'runs' || activeTab === 'configs') {
      if (evalConfigs.length === 0) {
        evalApi.fetchEvalConfigs().then(setEvalConfigs).catch(() => {});
      }
    }
  }, [activeTab]);

  // Auto-select active config
  useEffect(() => {
    if (evalConfigs.length > 0 && selectedConfigId === null) {
      const active = evalConfigs.find((c) => c.is_active);
      if (active) setSelectedConfigId(active.id);
    }
  }, [evalConfigs, selectedConfigId]);

  useEffect(() => {
    if (activeTab === 'runs') {
      refresh_evaluation_history();
    }
  }, [activeTab, refresh_evaluation_history]);

  const trendMetricOptions = useMemo(() => {
    const opts: { value: string; label: string }[] = [];
    const seen = new Set<string>();
    for (const e of evaluations) {
      const rpt = (e as Record<string, unknown>).report as Record<string, Record<string, number>> | undefined;
      if (!rpt) continue;
      for (const [section, metrics] of Object.entries(rpt)) {
        if (typeof metrics !== 'object' || metrics === null) continue;
        for (const key of Object.keys(metrics)) {
          if (key === 'by_type' || key === 'total_samples' || key === 'failed_samples') continue;
          const full = `${section}.${key}`;
          if (!seen.has(full)) {
            seen.add(full);
            const ml = resolveMetricMeta(key);
            opts.push({ value: full, label: `${section}.${ml.label}` });
          }
        }
      }
    }
    return opts;
  }, [evaluations]);

  useEffect(() => {
    if (activeTab !== 'runs' || !trendMetric) return;
    evalApi.fetchEvaluationTrends(trendMetric).then(setTrendData).catch(() => {});
  }, [activeTab, trendMetric]);

  const hasRunning = useMemo(
    () => evaluations.some((e) => e.status === 'running' || e.status === 'pending'),
    [evaluations],
  );

  useEffect(() => {
    if (activeTab !== 'runs' || !hasRunning) return;
    const timer = setInterval(refresh_evaluation_history, 3000);
    return () => clearInterval(timer);
  }, [activeTab, hasRunning, refresh_evaluation_history]);

  const start_evaluation = async (mode: 'retrieval' | 'generation' | 'full') => {
    if (!selectedConfigId) {
      message.warning('请先选择评测配置');
      return;
    }
    try {
      const { evaluation_id } = await evalApi.createEvaluation({
        mode,
        config_id: selectedConfigId,
      });
      message.success(`评测任务已创建: ${evaluation_id}`);
      refresh_evaluation_history();
    } catch (err) {
      message.error(`启动失败: ${err}`);
    }
  };

  const view_evaluation = async (evaluation: Evaluation) => {
    setSelectedEvaluation(evaluation);
    setSelectedEvalIds([]);
    setDimensionFilter('overall');
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

  const handle_batch_delete_evals = async () => {
    try {
      const { deleted } = await evalApi.deleteEvaluations(selectedEvalIds);
      message.success(`已删除 ${deleted} 条评测`);
      if (selectedEvaluation && selectedEvalIds.includes(selectedEvaluation.id)) {
        setSelectedEvaluation(null);
        setReport(null);
        setDetails([]);
      }
      setSelectedEvalIds([]);
      refresh_evaluation_history();
    } catch (err) {
      message.error(`删除失败: ${err}`);
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
      message.warning('请选择两个评测');
      return;
    }
    try {
      const result = await evalApi.compareEvaluations(compareIds.baseline, compareIds.compare);
      setCompareResult(result);
    } catch (err) {
      message.error(`对比失败: ${err}`);
    }
  };

  // Config Tab handlers
  const refresh_configs = useCallback(async () => {
    const configs = await evalApi.fetchEvalConfigs();
    setEvalConfigs(configs);
    return configs;
  }, []);

  useEffect(() => {
    if (activeTab === 'configs') refresh_configs();
  }, [activeTab, refresh_configs]);

  const view_config = async (config: EvalConfig) => {
    setViewingConfig(config);
    setEditingConfig(false);
    try {
      const full = await evalApi.fetchEvalConfig(config.id);
      setViewingConfigJson(full.config_json || null);
    } catch {
      message.error('加载配置详情失败');
    }
  };

  const CONFIG_FORM_DEFAULTS = {
    retrieval_vector_top_k: 20,
    retrieval_keyword_top_k: 20,
    retrieval_rrf_k: 60,
    retrieval_max_chunks_per_article: 3,
    retrieval_min_rrf_score: 0,
    rerank_enable_rerank: true,
    rerank_reranker_type: 'gguf',
    rerank_rerank_top_k: 5,
    rerank_min_score: 0,
    generation_max_context_chars: 12000,
  };

  const form_values_from_config = (json: Record<string, Record<string, unknown>> | undefined) => ({
    retrieval_vector_top_k: (json?.retrieval?.vector_top_k as number) ?? CONFIG_FORM_DEFAULTS.retrieval_vector_top_k,
    retrieval_keyword_top_k: (json?.retrieval?.keyword_top_k as number) ?? CONFIG_FORM_DEFAULTS.retrieval_keyword_top_k,
    retrieval_rrf_k: (json?.retrieval?.rrf_k as number) ?? CONFIG_FORM_DEFAULTS.retrieval_rrf_k,
    retrieval_max_chunks_per_article: (json?.retrieval?.max_chunks_per_article as number) ?? CONFIG_FORM_DEFAULTS.retrieval_max_chunks_per_article,
    retrieval_min_rrf_score: (json?.retrieval?.min_rrf_score as number) ?? CONFIG_FORM_DEFAULTS.retrieval_min_rrf_score,
    rerank_enable_rerank: (json?.rerank?.enable_rerank as boolean) ?? CONFIG_FORM_DEFAULTS.rerank_enable_rerank,
    rerank_reranker_type: (json?.rerank?.reranker_type as string) ?? CONFIG_FORM_DEFAULTS.rerank_reranker_type,
    rerank_rerank_top_k: (json?.rerank?.rerank_top_k as number) ?? CONFIG_FORM_DEFAULTS.rerank_rerank_top_k,
    rerank_min_score: (json?.rerank?.rerank_min_score as number) ?? CONFIG_FORM_DEFAULTS.rerank_min_score,
    generation_max_context_chars: (json?.generation?.max_context_chars as number) ?? CONFIG_FORM_DEFAULTS.generation_max_context_chars,
  });

  const start_new_config = () => {
    setViewingConfig(null);
    setViewingConfigJson(null);
    setEditingConfig(true);
    editForm.setFieldsValue({ description: '', ...CONFIG_FORM_DEFAULTS });
  };

  const clone_config = () => {
    if (!viewingConfig || !viewingConfigJson) return;
    setViewingConfig(null);
    setViewingConfigJson(null);
    setEditingConfig(true);
    editForm.setFieldsValue({
      description: viewingConfig.description,
      ...form_values_from_config(viewingConfigJson as Record<string, Record<string, unknown>>),
    });
  };

  const save_config = async () => {
    try {
      const values = await editForm.validateFields();
      await evalApi.createEvalConfig({
        description: values.description || '',
        retrieval: {
          vector_top_k: values.retrieval_vector_top_k,
          keyword_top_k: values.retrieval_keyword_top_k,
          rrf_k: values.retrieval_rrf_k,
          max_chunks_per_article: values.retrieval_max_chunks_per_article,
          min_rrf_score: values.retrieval_min_rrf_score,
        },
        rerank: {
          enable_rerank: values.rerank_enable_rerank,
          reranker_type: values.rerank_reranker_type,
          rerank_top_k: values.rerank_rerank_top_k,
          rerank_min_score: values.rerank_min_score,
        },
        generation: {
          max_context_chars: values.generation_max_context_chars,
        },
      });
      message.success('配置创建成功');
      await refresh_configs();
      setEditingConfig(false);
      setViewingConfig(null);
    } catch (err) {
      message.error(`保存配置失败: ${err}`);
    }
  };

  const activate_config = async (configId: number) => {
    try {
      await evalApi.activateEvalConfig(configId);
      message.success('已切换为当前生效配置');
      const configs = await refresh_configs();
      if (viewingConfig?.id === configId) {
        const updated = configs.find((c) => c.id === configId) ?? viewingConfig;
        setViewingConfig(updated);
      }
    } catch (err) {
      message.error(`切换失败: ${err}`);
    }
  };

  const delete_config = async (configId: number) => {
    try {
      await evalApi.deleteEvalConfig(configId);
      message.success('配置已删除');
      if (selectedConfigId === configId) setSelectedConfigId(null);
      if (viewingConfig?.id === configId) {
        setViewingConfig(null);
        setViewingConfigJson(null);
      }
      await refresh_configs();
    } catch (err) {
      message.error(`删除失败: ${err}`);
    }
  };

  const handle_batch_delete_configs = async () => {
    const deletableIds = configSelectedIds.filter((id) => {
      const cfg = evalConfigs.find((c) => c.id === id);
      return cfg && !cfg.is_active;
    });
    const skipped = configSelectedIds.length - deletableIds.length;
    if (skipped > 0) {
      message.warning(`${skipped} 条生效中的配置已跳过`);
    }
    let deleted = 0;
    for (const id of deletableIds) {
      try {
        const ok = await evalApi.deleteEvalConfig(id);
        if (ok) deleted++;
      } catch { /* skip */ }
    }
    if (deleted > 0) message.success(`已删除 ${deleted} 条配置`);
    else if (skipped > 0) message.info('没有可删除的配置');
    if (viewingConfig && configSelectedIds.includes(viewingConfig.id)) {
      setViewingConfig(null);
      setViewingConfigJson(null);
    }
    setConfigSelectedIds([]);
    await refresh_configs();
  };

  const run_config_compare = async () => {
    if (configSelectedIds.length < 2) return;
    const configs = await Promise.all(
      configSelectedIds.map((id) => evalApi.fetchEvalConfig(id)),
    );
    const allJsons = configs.map((c) => (c.config_json || {}) as Record<string, Record<string, unknown>>);
    const allKeys = new Set<string>();
    for (const j of allJsons) {
      for (const section of ['retrieval', 'rerank', 'generation']) {
        for (const key of Object.keys(j[section] || {})) {
          allKeys.add(`${section}.${key}`);
        }
      }
    }
    const rows: { param: string; values: (string | number | boolean)[] }[] = [];
    for (const param of allKeys) {
      const [section, key] = param.split('.');
      rows.push({
        param,
        values: allJsons.map((j) => (j[section]?.[key] as string | number | boolean) ?? '-'),
      });
    }
    setConfigCompareResult(rows);
  };

  const evaluationColumns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 140, ellipsis: true },
    {
      title: '模式', dataIndex: 'mode', key: 'mode', width: 100,
      render: (m: string) => <Tag>{m}</Tag>,
    },
    {
      title: '配置', dataIndex: 'config', key: 'config', width: 100,
      render: (_: unknown, e: Evaluation) => {
        const cv = e.config?.dataset?.config_version;
        return cv ? <Tag>v{cv}</Tag> : <Text type="secondary">-</Text>;
      },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (s: string) => {
        const info = STATUS_MAP[s] || { color: 'default', label: s };
        return <Tag color={info.color}>{info.label}</Tag>;
      },
    },
    {
      title: '进度', key: 'progress', width: 120,
      render: (_: undefined, e: Evaluation) => {
        if (e.status === 'completed') return <Text>100%</Text>;
        if (e.total > 0) return <Progress percent={Math.round((e.progress / e.total) * 100)} size="small" />;
        return <Text type="secondary">-</Text>;
      },
    },
    { title: '启动时间', dataIndex: 'started_at', key: 'started_at', width: 160, ellipsis: true },
  ];

  const detailColumns = [
    { title: '样本ID', dataIndex: 'sample_id', key: 'sample_id', width: 80 },
    {
      title: <Tooltip title={resolveMetricMeta('precision_at_k', evalK).tooltip}>Precision@{evalK}</Tooltip>,
      key: 'precision', width: 100,
      render: (_: undefined, r: SampleResult) => formatMetric(r.retrieval_metrics.precision),
    },
    {
      title: <Tooltip title={resolveMetricMeta('recall_at_k', evalK).tooltip}>Recall@{evalK}</Tooltip>,
      key: 'recall', width: 100,
      render: (_: undefined, r: SampleResult) => formatMetric(r.retrieval_metrics.recall),
    },
    {
      title: <Tooltip title={resolveMetricMeta('mrr').tooltip}>MRR</Tooltip>,
      key: 'mrr', width: 90,
      render: (_: undefined, r: SampleResult) => formatMetric(r.retrieval_metrics.mrr),
    },
    {
      title: <Tooltip title={resolveMetricMeta('ndcg').tooltip}>NDCG</Tooltip>,
      key: 'ndcg', width: 90,
      render: (_: undefined, r: SampleResult) => formatMetric(r.retrieval_metrics.ndcg),
    },
    {
      title: <Tooltip title={resolveMetricMeta('faithfulness').tooltip}>忠实度</Tooltip>,
      key: 'faithfulness', width: 100,
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
            label: '评测数据集',
            children: (
              <>
                <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Space>
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
                  <Space>
                    <Button type="primary" icon={<PlusOutlined />} onClick={create_sample}>新增</Button>
                    <Button icon={<ImportOutlined />} onClick={() => setImportModalOpen(true)}>批量导入</Button>
                    <Button icon={<SaveOutlined />} onClick={() => setSnapshotModalOpen(true)}>创建快照</Button>
                  </Space>
                </div>

                <Row gutter={16}>
                  <Col span={16}>
                    <Card bodyStyle={{ padding: 0 }} style={{ overflow: 'hidden' }}>
                      <Table
                        dataSource={samples}
                        columns={datasetColumns}
                        rowKey="id"
                        loading={samplesLoading}
                        pagination={{ pageSize: 20 }}
                        size="middle"
                        scroll={{ x: 650 }}
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
            key: 'review',
            label: '审核',
            children: <ReviewTab />,
          },
          {
            key: 'configs',
            label: '配置管理',
            children: (
              <Row gutter={16}>
                <Col span={10}>
                  <Card title="配置列表" size="small" bodyStyle={{ padding: 0, overflow: 'hidden' }}
                    extra={<Button type="primary" size="small" icon={<PlusOutlined />} onClick={start_new_config}>新增</Button>}
                  >
                    <div style={{ overflow: 'auto', maxHeight: 'calc(100vh - 270px)' }}>
                      <Table
                        dataSource={evalConfigs}
                        columns={[
                          {
                            title: '', key: '_select', width: 40,
                            render: (_: undefined, cfg: EvalConfig) => (
                              <Checkbox
                                checked={configSelectedIds.includes(cfg.id)}
                                disabled={!!cfg.is_active}
                                onChange={(ev) => {
                                  setConfigSelectedIds((prev) =>
                                    ev.target.checked ? [...prev, cfg.id] : prev.filter((x) => x !== cfg.id),
                                  );
                                  view_config(cfg);
                                }}
                                onClick={(ev) => ev.stopPropagation()}
                              />
                            ),
                          },
                          {
                            title: '版本', dataIndex: 'version', key: 'version', width: 60,
                            render: (v: number) => <Text strong>v{v}</Text>,
                          },
                          {
                            title: '说明', dataIndex: 'description', key: 'description', ellipsis: true,
                            render: (d: string) => d || '-',
                          },
                          {
                            title: '状态', key: 'status', width: 70,
                            render: (_: undefined, cfg: EvalConfig) =>
                              !!cfg.is_active ? <Tag color="green">生效中</Tag> : <Text type="secondary">未激活</Text>,
                          },
                          {
                            title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 160, ellipsis: true,
                            render: (t: string) => t?.slice(0, 19),
                          },
                        ]}
                        rowKey="id"
                        size="small"
                        pagination={false}
                        onRow={(cfg) => ({
                          onClick: () => view_config(cfg),
                          style: {
                            cursor: 'pointer',
                            background: viewingConfig?.id === cfg.id ? '#e6f4ff' : undefined,
                          },
                        })}
                      />
                    </div>
                    <div style={{
                      padding: '8px 16px', borderTop: '1px solid #f0f0f0',
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      fontSize: 12, color: '#8c8c8c', flexShrink: 0,
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Checkbox
                          checked={evalConfigs.length > 0 && configSelectedIds.length === evalConfigs.length}
                          indeterminate={configSelectedIds.length > 0 && configSelectedIds.length < evalConfigs.length}
                          onChange={(e) => setConfigSelectedIds(e.target.checked ? evalConfigs.map((c) => c.id) : [])}
                        >
                          全选
                        </Checkbox>
                        {configSelectedIds.length > 0 ? (
                          <>
                            <span style={{ color: '#1677ff' }}>{configSelectedIds.length} 项</span>
                            <span style={{ fontSize: 12, color: '#bfbfbf' }}>(含生效中不可删除)</span>
                            <Divider type="vertical" style={{ margin: '0 4px' }} />
                            <Popconfirm
                              title={`确定删除选中的 ${configSelectedIds.length} 条配置？`}
                              description="生效中的配置无法删除"
                              onConfirm={handle_batch_delete_configs}
                            >
                              <Button type="primary" danger size="small" icon={<DeleteOutlined />}>删除</Button>
                            </Popconfirm>
                            {configSelectedIds.length >= 2 && (
                              <Button size="small" icon={<SwapOutlined />} onClick={() => { run_config_compare(); setConfigCompareOpen(true); }}>
                                对比
                              </Button>
                            )}
                          </>
                        ) : (
                          <span>共 {evalConfigs.length} 条</span>
                        )}
                      </div>
                    </div>
                  </Card>
                </Col>

                <Col span={14}>
                  {!editingConfig && viewingConfig && viewingConfigJson && (
                    <>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                        <Text strong>配置详情</Text>
                        <Space>
                          <Button size="small" icon={<CopyOutlined />} onClick={clone_config}>克隆</Button>
                          {!viewingConfig.is_active && (
                            <Popconfirm title="将此配置设为当前生效？" onConfirm={() => activate_config(viewingConfig!.id)}>
                              <Button size="small" icon={<CheckCircleOutlined />}>设为生效</Button>
                            </Popconfirm>
                          )}
                        </Space>
                      </div>

                      <Descriptions bordered size="small" column={3}>
                        <Descriptions.Item label="版本">v{viewingConfig.version}</Descriptions.Item>
                        <Descriptions.Item label="状态">
                          {!!viewingConfig.is_active ? <Tag color="green">生效中</Tag> : <Tag>未激活</Tag>}
                        </Descriptions.Item>
                        <Descriptions.Item label="创建时间">{viewingConfig.created_at}</Descriptions.Item>
                        <Descriptions.Item label="说明" span={3}>{viewingConfig.description || '-'}</Descriptions.Item>
                      </Descriptions>

                      <Card size="small" title="检索参数" style={{ marginTop: 8 }}>
                        <Descriptions bordered size="small" column={3}>
                          <Descriptions.Item label="向量 Top-K">{viewingConfigJson.retrieval?.vector_top_k}</Descriptions.Item>
                          <Descriptions.Item label="关键词 Top-K">{viewingConfigJson.retrieval?.keyword_top_k}</Descriptions.Item>
                          <Descriptions.Item label="RRF K">{viewingConfigJson.retrieval?.rrf_k}</Descriptions.Item>
                          <Descriptions.Item label="单篇最大 Chunk">{viewingConfigJson.retrieval?.max_chunks_per_article}</Descriptions.Item>
                          <Descriptions.Item label="最小 RRF 分数">{viewingConfigJson.retrieval?.min_rrf_score}</Descriptions.Item>
                        </Descriptions>
                      </Card>

                      <Card size="small" title="重排序参数" style={{ marginTop: 8 }}
                        extra={
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <Text type="secondary" style={{ fontSize: 13 }}>启用重排序</Text>
                            <Tag color={viewingConfigJson.rerank?.enable_rerank ? 'green' : 'default'}>{viewingConfigJson.rerank?.enable_rerank ? '是' : '否'}</Tag>
                          </div>
                        }
                      >
                        <Descriptions bordered size="small" column={3}>
                          <Descriptions.Item label="重排序器">{viewingConfigJson.rerank?.reranker_type}</Descriptions.Item>
                          <Descriptions.Item label="重排序 Top-K">{viewingConfigJson.rerank?.rerank_top_k}</Descriptions.Item>
                          <Descriptions.Item label="最小重排序分数">{viewingConfigJson.rerank?.rerank_min_score}</Descriptions.Item>
                        </Descriptions>
                      </Card>

                      <Card size="small" title="生成参数" style={{ marginTop: 8 }}>
                        <Descriptions bordered size="small" column={1}>
                          <Descriptions.Item label="最大上下文字符数">{viewingConfigJson.generation?.max_context_chars}</Descriptions.Item>
                        </Descriptions>
                      </Card>
                    </>
                  )}

                  {editingConfig && (
                    <>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                        <Text strong>新建配置</Text>
                        <Space>
                          <Button type="primary" onClick={save_config}>保存</Button>
                          <Button onClick={() => { setEditingConfig(false); setViewingConfig(null); }}>取消</Button>
                        </Space>
                      </div>

                      <Form form={editForm} layout="horizontal">
                        <Form.Item name="description" label="配置说明" labelCol={{ span: 6 }} wrapperCol={{ span: 18 }}>
                          <Input placeholder="如：关闭 reranker 的配置" />
                        </Form.Item>

                        <Card size="small" title="检索参数" style={{ marginBottom: 8 }}>
                          <Form.Item name="retrieval_vector_top_k" label="向量 Top-K" labelCol={{ span: 6 }} wrapperCol={{ span: 18 }} style={{ display: 'inline-block', width: '50%', verticalAlign: 'top' }}>
                            <InputNumber min={1} style={{ width: '100%' }} />
                          </Form.Item>
                          <Form.Item name="retrieval_keyword_top_k" label="关键词 Top-K" labelCol={{ span: 6 }} wrapperCol={{ span: 18 }} style={{ display: 'inline-block', width: '50%', verticalAlign: 'top' }}>
                            <InputNumber min={1} style={{ width: '100%' }} />
                          </Form.Item>
                          <Form.Item name="retrieval_rrf_k" label="RRF K" labelCol={{ span: 6 }} wrapperCol={{ span: 18 }} style={{ display: 'inline-block', width: '50%', verticalAlign: 'top' }}>
                            <InputNumber min={1} style={{ width: '100%' }} />
                          </Form.Item>
                          <Form.Item name="retrieval_max_chunks_per_article" label="单篇最大 Chunk" labelCol={{ span: 6 }} wrapperCol={{ span: 18 }} style={{ display: 'inline-block', width: '50%', verticalAlign: 'top' }}>
                            <InputNumber min={1} style={{ width: '100%' }} />
                          </Form.Item>
                          <Form.Item name="retrieval_min_rrf_score" label="最小 RRF 分数" labelCol={{ span: 6 }} wrapperCol={{ span: 18 }} style={{ display: 'inline-block', width: '50%', verticalAlign: 'top' }}>
                            <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} />
                          </Form.Item>
                        </Card>

                        <Card
                          size="small"
                          title="重排序参数"
                          style={{ marginBottom: 8 }}
                          extra={
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <Text type="secondary" style={{ fontSize: 13 }}>启用重排序</Text>
                              <Form.Item name="rerank_enable_rerank" valuePropName="checked" style={{ marginBottom: 0 }}>
                                <Switch checkedChildren="开" unCheckedChildren="关" />
                              </Form.Item>
                            </div>
                          }
                        >
                          <Form.Item name="rerank_reranker_type" label="重排序器" labelCol={{ span: 6 }} wrapperCol={{ span: 18 }} style={{ display: 'inline-block', width: '50%', verticalAlign: 'top' }}>
                            <Select disabled={!rerankEnabled} options={[
                              { value: 'gguf', label: 'GGUF' },
                              { value: 'llm', label: 'LLM' },
                              { value: 'none', label: 'None' },
                            ]} />
                          </Form.Item>
                          <Form.Item name="rerank_rerank_top_k" label="重排序 Top-K" labelCol={{ span: 6 }} wrapperCol={{ span: 18 }} style={{ display: 'inline-block', width: '50%', verticalAlign: 'top' }}>
                            <InputNumber min={1} disabled={!rerankEnabled} style={{ width: '100%' }} />
                          </Form.Item>
                          <Form.Item name="rerank_rerank_min_score" label="最小重排序分数" labelCol={{ span: 6 }} wrapperCol={{ span: 18 }} style={{ display: 'inline-block', width: '50%', verticalAlign: 'top' }}>
                            <InputNumber min={0} max={1} step={0.1} disabled={!rerankEnabled} style={{ width: '100%' }} />
                          </Form.Item>
                        </Card>

                        <Card size="small" title="生成参数">
                          <Form.Item name="generation_max_context_chars" label="最大上下文字符数" labelCol={{ span: 6 }} wrapperCol={{ span: 18 }}>
                            <InputNumber min={500} max={50000} step={1000} />
                          </Form.Item>
                        </Card>
                      </Form>
                    </>
                  )}

                  {!editingConfig && !viewingConfig && (
                    <div style={{ textAlign: 'center', paddingTop: 80 }}>
                      <Text type="secondary">选择左侧的配置查看详情，或新建配置</Text>
                    </div>
                  )}
                </Col>
              </Row>
            ),
          },
          {
            key: 'runs',
            label: '评测历史',
            children: (
              <>
                <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Space>
                    <Select
                      style={{ width: 200 }}
                      placeholder="选择评测配置"
                      value={selectedConfigId}
                      onChange={setSelectedConfigId}
                      options={evalConfigs.map((c) => ({
                        value: c.id,
                        label: `v${c.version}${c.description ? ` ${c.description}` : ''}${!!c.is_active ? ' (生效中)' : ''}`,
                      }))}
                    />
                    <Button icon={<PlayCircleOutlined />} disabled={!selectedConfigId} onClick={() => start_evaluation('retrieval')}>检索评测</Button>
                    <Button icon={<PlayCircleOutlined />} disabled={!selectedConfigId} onClick={() => start_evaluation('generation')}>生成评测</Button>
                    <Button type="primary" icon={<PlayCircleOutlined />} disabled={!selectedConfigId} onClick={() => start_evaluation('full')}>完整评测</Button>
                    <Button icon={<SwapOutlined />} onClick={() => setCompareModalOpen(true)}>版本对比</Button>
                  </Space>
                </div>

                {trendMetricOptions.length > 0 && (
                  <Card size="small" style={{ marginBottom: 12 }} bodyStyle={{ paddingBottom: 0 }}>
                    <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Text type="secondary">指标趋势</Text>
                      <Select
                        size="small"
                        value={trendMetric}
                        onChange={setTrendMetric}
                        style={{ width: 240 }}
                        options={trendMetricOptions}
                      />
                    </div>
                    <TrendChart data={trendData} metricName={trendMetric} />
                  </Card>
                )}

                <Row gutter={16}>
                  <Col span={10}>
                    <Card title="评测记录" size="small" bodyStyle={{ padding: 0, overflow: 'hidden' }}>
                      <div style={{ overflow: 'auto', maxHeight: 400 }}>
                        {evaluationsLoading ? (
                          <div style={{ padding: '40px 16px', textAlign: 'center', color: '#bfbfbf', fontSize: 12 }}>加载中...</div>
                        ) : evalPaged.length === 0 ? (
                          <div style={{ padding: '40px 16px', textAlign: 'center', color: '#bfbfbf', fontSize: 12 }}>暂无评测记录</div>
                        ) : (
                          <Table
                            dataSource={evalPaged}
                            columns={[
                              {
                                title: '',
                                key: '_select',
                                width: 40,
                                render: (_: undefined, e: Evaluation) => (
                                  <Checkbox
                                    checked={selectedEvalIds.includes(e.id)}
                                    onChange={(ev) => toggle_eval_selection(e.id, ev.target.checked)}
                                    onClick={(ev) => ev.stopPropagation()}
                                  />
                                ),
                              },
                              ...evaluationColumns,
                            ]}
                            rowKey="id"
                            size="small"
                            scroll={{ x: 660 }}
                            pagination={false}
                            onRow={(evaluation) => ({
                              onClick: () => view_evaluation(evaluation),
                              style: {
                                cursor: 'pointer',
                                background: selectedEvaluation?.id === evaluation.id ? '#e6f4ff' : undefined,
                              },
                            })}
                          />
                        )}
                      </div>
                      <div style={{
                        padding: '8px 16px', borderTop: '1px solid #f0f0f0',
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        fontSize: 12, color: '#8c8c8c', flexShrink: 0,
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <Checkbox
                            checked={evalAllSelected}
                            indeterminate={hasSelection && !evalAllSelected}
                            onChange={(e) => setSelectedEvalIds(e.target.checked ? evalPaged.map((ev) => ev.id) : [])}
                          >
                            全选
                          </Checkbox>
                          {hasSelection && (
                            <>
                              <span style={{ color: '#1677ff' }}>{selectedEvalIds.length} 项</span>
                              <Popconfirm
                                title={`确定删除 ${selectedEvalIds.length} 条评测？`}
                                onConfirm={handle_batch_delete_evals}
                              >
                                <Button type="primary" danger size="small" icon={<DeleteOutlined />}>删除</Button>
                              </Popconfirm>
                            </>
                          )}
                          {!hasSelection && <span>共 {evaluations.length} 条</span>}
                        </div>
                        {evaluations.length > EVAL_PAGE_SIZE && (
                          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                            <Button size="small" disabled={evalPage <= 1} onClick={() => setEvalPage(evalPage - 1)}>上一页</Button>
                            <span>{evalPage}</span>
                            <Button size="small" disabled={evalPage * EVAL_PAGE_SIZE >= evaluations.length} onClick={() => setEvalPage(evalPage + 1)}>下一页</Button>
                          </div>
                        )}
                      </div>
                    </Card>
                  </Col>

                  <Col span={14}>
                    {selectedEvaluation ? (
                      <>
                        <Descriptions
                          title={`评测报告 - ${selectedEvaluation.id}`}
                          size="small"
                          column={{ xs: 1, sm: 2, md: 3 }}
                          bordered
                          style={{ marginBottom: 16 }}
                        >
                          <Descriptions.Item label="模式">{selectedEvaluation.mode}</Descriptions.Item>
                          <Descriptions.Item label="状态">
                            <Tag color={STATUS_MAP[selectedEvaluation.status]?.color}>{STATUS_MAP[selectedEvaluation.status]?.label}</Tag>
                          </Descriptions.Item>
                          <Descriptions.Item label="启动时间">{selectedEvaluation.started_at}</Descriptions.Item>
                          {selectedEvaluation.status === 'completed' && (
                            <Descriptions.Item label="操作" span={3}>
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
                            {availableDimensions.length > 1 && (
                              <div style={{ marginBottom: 12 }}>
                                <Text type="secondary">维度筛选：</Text>
                                <Select
                                  size="small"
                                  value={dimensionFilter}
                                  onChange={setDimensionFilter}
                                  style={{ width: 140, marginLeft: 8 }}
                                  options={availableDimensions.map((d) => ({
                                    value: d,
                                    label: d === 'overall' ? '整体' : d,
                                  }))}
                                />
                              </div>
                            )}
                            <MetricsChart metrics={flattenedMetrics} k={evalK} />
                            <Card title="逐题详情" size="small" style={{ marginTop: 16 }} bodyStyle={{ padding: 0, overflow: 'hidden' }}>
                              <Table
                                dataSource={details}
                                columns={detailColumns}
                                rowKey="id"
                                size="small"
                                pagination={{ pageSize: 20 }}
                                scroll={{ x: 570 }}
                                expandable={{
                                  expandedRowRender: (record) => (
                                    <div style={{ padding: '8px 16px' }}>
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
                        <Text type="secondary">选择一条评测记录查看详情</Text>
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
        width={800}
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

        {compareResult && (() => {
          const comparisonItems = Object.entries(compareResult.metrics_diff || {}).map(([key, val]) => ({
            key,
            metric: key,
            ...val,
            trend: val.delta > 0 ? '\u2191' : val.delta < 0 ? '\u2193' : '\u2192',
          }));
          return (
            <>
              <ComparisonChart data={comparisonItems} k={evalK} />
              <Table dataSource={comparisonItems}
              columns={[
                { title: '指标', dataIndex: 'metric', key: 'metric', render: (v: string) => {
                  const [, metric] = v.split('.');
                  return resolveMetricMeta(metric).label;
                }},
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
            </>
          );
        })()}
      </Modal>

      <Modal
        title="配置对比"
        open={configCompareOpen}
        onCancel={() => { setConfigCompareOpen(false); setConfigCompareResult(null); }}
        width={Math.min(Math.max(500, 200 + configSelectedIds.length * 120), 1200)}
        footer={null}
        styles={{ body: { maxHeight: 'calc(100vh - 200px)', overflowY: 'auto' } }}
      >
        {!configCompareResult && (
          <div style={{ padding: '20px 0', textAlign: 'center' }}>
            <Text type="secondary">请在左侧勾选 2 个以上配置后点击底部「对比」按钮</Text>
          </div>
        )}
        {configCompareResult && (() => {
          const versionHeaders = configSelectedIds.map((id) => {
            const ver = evalConfigs.find((c) => c.id === id)?.version;
            return `v${ver}`;
          });
          const makeColumns = (sectionLabel: string) => [
            { title: '参数', dataIndex: 'param', key: 'param', width: 180 },
            ...versionHeaders.map((header, idx) => ({
              title: header,
              key: `v${idx}`,
              width: 100,
              render: (_: unknown, r: { values: (string | number | boolean)[] }) => {
                const val = r.values[idx];
                const unique = new Set(r.values).size > 1;
                return <span style={{ color: unique ? '#1677ff' : undefined, fontWeight: unique ? 600 : undefined }}>{String(val)}</span>;
              },
            })),
          ];
          const sections: Record<string, string> = {
            retrieval: '检索参数',
            rerank: '重排序参数',
            generation: '生成参数',
          };
          return Object.entries(sections).map(([section, label]) => {
            const rows = configCompareResult
              .filter((r) => r.param.startsWith(`${section}.`))
              .map((r, i) => ({ key: i, param: r.param.replace(`${section}.`, ''), values: r.values }));
            if (rows.length === 0) return null;
            return (
              <Card key={section} size="small" title={label} style={{ marginBottom: 8 }}>
                <Table
                  dataSource={rows}
                  columns={makeColumns(label)}
                  pagination={false}
                  size="small"
                  scroll={{ x: 'max-content' }}
                />
              </Card>
            );
          });
        })()}
      </Modal>
    </div>
  );
}
