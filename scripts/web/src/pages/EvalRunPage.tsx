import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Card, Table, Button, Space, Select, Tag, Modal, Typography,
  message, Progress, Row, Col, Descriptions,
} from 'antd';
import {
  PlayCircleOutlined, DownloadOutlined, SwapOutlined,
} from '@ant-design/icons';
import * as evalApi from '../api/eval';
import MetricsChart, { formatMetric } from '../components/MetricsChart';
import type { EvalRun, SampleResult } from '../types';

const { Title, Text } = Typography;

export default function EvalRunPage() {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedRun, setSelectedRun] = useState<EvalRun | null>(null);
  const [report, setReport] = useState<Record<string, Record<string, number>> | null>(null);
  const [details, setDetails] = useState<SampleResult[]>([]);

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
  const [compareModalOpen, setCompareModalOpen] = useState(false);
  const [compareIds, setCompareIds] = useState<{ baseline: string; compare: string }>({ baseline: '', compare: '' });
  const [compareResult, setCompareResult] = useState<{
    metrics_diff: Record<string, { baseline: number; compare: number; delta: number; pct_change: number }>;
    improved: string[];
    regressed: string[];
  } | null>(null);

  const loadRuns = useCallback(async () => {
    setLoading(true);
    try {
      const data = await evalApi.fetchEvalRuns();
      setRuns(data);
    } catch (err) {
      message.error(`加载失败: ${err}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    const runningRuns = runs.filter((r) => r.status === 'running' || r.status === 'pending');
    if (runningRuns.length === 0) return;
    const timer = setInterval(async () => {
      await loadRuns();
    }, 3000);
    return () => clearInterval(timer);
  }, [runs, loadRuns]);

  const handleStartRun = async (mode: 'retrieval' | 'generation' | 'full') => {
    try {
      const { run_id } = await evalApi.createEvalRun({ mode, top_k: 5 });
      message.success(`评估任务已创建: ${run_id}`);
      loadRuns();
    } catch (err) {
      message.error(`启动失败: ${err}`);
    }
  };

  const handleSelectRun = async (run: EvalRun) => {
    setSelectedRun(run);
    if (run.status === 'completed') {
      try {
        const [rpt, det] = await Promise.all([
          evalApi.fetchEvalRunReport(run.id),
          evalApi.fetchEvalRunDetails(run.id),
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

  const handleExport = async (runId: string, format: 'json' | 'md') => {
    try {
      const blob = await evalApi.exportEvalReport(runId, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `eval_report_${runId}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      message.error(`导出失败: ${err}`);
    }
  };

  const handleCompare = async () => {
    if (!compareIds.baseline || !compareIds.compare) {
      message.warning('请选择两个评估运行');
      return;
    }
    try {
      const result = await evalApi.compareEvalRuns(compareIds.baseline, compareIds.compare);
      setCompareResult(result);
    } catch (err) {
      message.error(`对比失败: ${err}`);
    }
  };

  const STATUS_MAP: Record<string, { color: string; label: string }> = {
    pending: { color: 'default', label: '等待中' },
    running: { color: 'processing', label: '运行中' },
    completed: { color: 'success', label: '已完成' },
    failed: { color: 'error', label: '失败' },
  };

  const runColumns = [
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
      render: (_: undefined, r: EvalRun) => {
        if (r.status === 'completed') return <Text>100%</Text>;
        if (r.total > 0) return <Progress percent={Math.round((r.progress / r.total) * 100)} size="small" />;
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
      <Title level={4} style={{ marginBottom: 16 }}>评估运行与结果</Title>

      <Space style={{ marginBottom: 16 }}>
        <Button icon={<PlayCircleOutlined />} onClick={() => handleStartRun('retrieval')}>检索评估</Button>
        <Button icon={<PlayCircleOutlined />} onClick={() => handleStartRun('generation')}>生成评估</Button>
        <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => handleStartRun('full')}>完整评估</Button>
        <Button icon={<SwapOutlined />} onClick={() => setCompareModalOpen(true)}>版本对比</Button>
      </Space>

      <Row gutter={16}>
        <Col span={10}>
          <Card title="评估历史" size="small">
            <Table
              dataSource={runs}
              columns={runColumns}
              rowKey="id"
              loading={loading}
              size="small"
              pagination={{ pageSize: 15 }}
              onRow={(record) => ({
                onClick: () => handleSelectRun(record),
                style: {
                  cursor: 'pointer',
                  background: selectedRun?.id === record.id ? '#e6f4ff' : undefined,
                },
              })}
            />
          </Card>
        </Col>

        <Col span={14}>
          {selectedRun ? (
            <>
              <Descriptions title={`评估报告 - ${selectedRun.id}`} size="small" style={{ marginBottom: 16 }}>
                <Descriptions.Item label="模式">{selectedRun.mode}</Descriptions.Item>
                <Descriptions.Item label="状态">
                  <Tag color={STATUS_MAP[selectedRun.status]?.color}>{STATUS_MAP[selectedRun.status]?.label}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="启动时间">{selectedRun.started_at}</Descriptions.Item>
                {selectedRun.status === 'completed' && (
                  <Descriptions.Item label="操作">
                    <Space>
                      <Button size="small" icon={<DownloadOutlined />}
                        onClick={() => handleExport(selectedRun.id, 'json')}>JSON</Button>
                      <Button size="small" icon={<DownloadOutlined />}
                        onClick={() => handleExport(selectedRun.id, 'md')}>Markdown</Button>
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
              <Text type="secondary">选择一个评估运行查看详情</Text>
            </Card>
          )}
        </Col>
      </Row>

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
            options={runs.filter((r) => r.status === 'completed').map((r) => ({
              value: r.id, label: `${r.id} (${r.mode}, ${r.started_at?.slice(0, 10)})`,
            }))}
          />
          <span>vs</span>
          <Select
            placeholder="对比版本" style={{ width: 200 }}
            value={compareIds.compare || undefined}
            onChange={(v) => setCompareIds({ ...compareIds, compare: v })}
            options={runs.filter((r) => r.status === 'completed').map((r) => ({
              value: r.id, label: `${r.id} (${r.mode}, ${r.started_at?.slice(0, 10)})`,
            }))}
          />
          <Button type="primary" onClick={handleCompare}>对比</Button>
        </Space>

        {compareResult && (
          <Table
            dataSource={Object.entries(compareResult.metrics_diff || {}).map(([key, val]) => ({
              key,
              metric: key,
              ...val,
              trend: val.delta > 0 ? '↑' : val.delta < 0 ? '↓' : '→',
            }))}
            columns={[
              { title: '指标', dataIndex: 'metric', key: 'metric' },
              { title: '基准', dataIndex: 'baseline', key: 'baseline', render: (v: number) => (v * 100).toFixed(2) + '%' },
              { title: '对比', dataIndex: 'compare', key: 'compare', render: (v: number) => (v * 100).toFixed(2) + '%' },
              { title: '变化', dataIndex: 'pct_change', key: 'pct_change',
                render: (v: number) => <span style={{ color: v > 0 ? '#52c41a' : v < 0 ? '#ff4d4f' : '#999' }}>{v > 0 ? '+' : ''}{v.toFixed(1)}%</span> },
              { title: '趋势', dataIndex: 'trend', key: 'trend', width: 60,
                render: (v: string) => <span style={{ color: v === '↑' ? '#52c41a' : v === '↓' ? '#ff4d4f' : '#999', fontWeight: 600 }}>{v}</span> },
            ]}
            size="small"
            pagination={false}
          />
        )}
      </Modal>
    </div>
  );
}
