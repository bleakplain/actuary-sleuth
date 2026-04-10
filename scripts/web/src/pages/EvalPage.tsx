import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Card, Table, Button, Space, Select, Tag, Modal, Form, Input, InputNumber, Switch,
  Typography, message, Row, Col, Popconfirm, Progress, Descriptions, Tabs, Tooltip,
  Divider, Checkbox, Drawer, Tree, theme,
} from 'antd';
import {
  PlusOutlined, ImportOutlined, SaveOutlined, RollbackOutlined,
  PlayCircleOutlined, DownloadOutlined, SwapOutlined,
  DeleteOutlined, CopyOutlined, CheckCircleOutlined, SearchOutlined, CloseCircleOutlined, LinkOutlined,
  FolderOutlined,
} from '@ant-design/icons';
import * as evalApi from '../api/eval';
import * as kbApi from '../api/knowledge';
import MetricsChart, { formatMetric, ComparisonChart, TrendChart } from '../components/MetricsChart';
import type { EvalSample, EvalSnapshot, Evaluation, EvalConfig, SampleResult, MetricsDiff, RegulationRef } from '../types';
import { resolveMetricMeta } from '../utils/evalMetrics';
import { DRAWER_SM, DRAWER_LG, MODAL_MD, MODAL_LG } from '../constants/layout';

const { Text, Title } = Typography;

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

const REVIEW_STATUS_TAG: Record<string, { color: string; label: string }> = {
  approved: { color: 'green', label: '已通过' },
  pending: { color: 'default', label: '待审核' },
};

interface KbSearchResult {
  doc_name: string; article: string; excerpt: string; hierarchy_path: string; chunk_id: string;
}

interface KbChunkItem {
  law_name: string; article_number: string; category: string; hierarchy_path: string;
  source_file: string; doc_number: string; issuing_authority: string; text: string;
}

const MIN_DRAWER_WIDTH = DRAWER_SM;
const MAX_DRAWER_WIDTH = DRAWER_LG + 160;
const DEFAULT_DRAWER_WIDTH = Math.round((DRAWER_SM + MAX_DRAWER_WIDTH) / 2);

function SampleDrawer({
  sample,
  open,
  onClose,
  onSaved,
}: {
  sample: EvalSample;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { token } = theme.useToken();
  const [drawerWidth, setDrawerWidth] = useState(DEFAULT_DRAWER_WIDTH);
  const [resizing, setResizing] = useState(false);
  const resizeStartX = useRef(0);
  const resizeStartWidth = useRef(0);

  const [editGroundTruth, setEditGroundTruth] = useState('');
  const [editComment, setEditComment] = useState('');
  const [kbQuery, setKbQuery] = useState('');
  const [kbResults, setKbResults] = useState<KbSearchResult[]>([]);
  const [kbSearching, setKbSearching] = useState(false);
  const [kbSearchDone, setKbSearchDone] = useState(false);

  const [kbDocs, setKbDocs] = useState<{ name: string; file_path: string; clause_count: number }[]>([]);
  const [kbDocsLoading, setKbDocsLoading] = useState(false);
  const [selectedDocPath, setSelectedDocPath] = useState<string | undefined>(undefined);
  const [docChunks, setDocChunks] = useState<KbChunkItem[]>([]);
  const [docChunksLoading, setDocChunksLoading] = useState(false);
  const [currentRefs, setCurrentRefs] = useState<RegulationRef[]>([]);
  const [treeWidth, setTreeWidth] = useState(240);
  const treeResizeStartX = useRef(0);
  const treeResizeStartWidth = useRef(0);
  const [treeResizing, setTreeResizing] = useState(false);

  useEffect(() => {
    if (sample) {
      setEditGroundTruth(sample.ground_truth);
      setEditComment(sample.review_comment);
      setCurrentRefs([...(sample.regulation_refs || [])]);
      setKbQuery('');
      setKbResults([]);
      setKbSearchDone(false);
      loadKbDocs();
    }
  }, [sample]);

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    resizeStartX.current = e.clientX;
    resizeStartWidth.current = drawerWidth;
    setResizing(true);

    const handleResizeMove = (ev: MouseEvent) => {
      const delta = resizeStartX.current - ev.clientX;
      const newWidth = Math.min(MAX_DRAWER_WIDTH, Math.max(MIN_DRAWER_WIDTH, resizeStartWidth.current + delta));
      setDrawerWidth(newWidth);
    };

    const handleResizeEnd = () => {
      setResizing(false);
      document.removeEventListener('mousemove', handleResizeMove);
      document.removeEventListener('mouseup', handleResizeEnd);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.addEventListener('mousemove', handleResizeMove);
    document.addEventListener('mouseup', handleResizeEnd);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [drawerWidth]);

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

  const loadKbDocs = async () => {
    setKbDocsLoading(true);
    try {
      const docs = await kbApi.fetchDocuments();
      setKbDocs(docs.map(d => ({ name: d.name, file_path: d.file_path, clause_count: d.clause_count })));
    } catch {
      // KB docs optional
    } finally {
      setKbDocsLoading(false);
    }
  };

  const handleTreeResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    treeResizeStartX.current = e.clientX;
    treeResizeStartWidth.current = treeWidth;
    setTreeResizing(true);

    const handleMove = (ev: MouseEvent) => {
      const delta = ev.clientX - treeResizeStartX.current;
      const newWidth = Math.min(300, Math.max(80, treeResizeStartWidth.current + delta));
      setTreeWidth(newWidth);
    };

    const handleEnd = () => {
      setTreeResizing(false);
      document.removeEventListener('mousemove', handleMove);
      document.removeEventListener('mouseup', handleEnd);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.addEventListener('mousemove', handleMove);
    document.addEventListener('mouseup', handleEnd);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [treeWidth]);

  const handleSelectDoc = async (filePath: string) => {
    setSelectedDocPath(filePath || undefined);
    if (!filePath) {
      setDocChunks([]);
      return;
    }
    setDocChunksLoading(true);
    try {
      const result = await kbApi.fetchDocumentChunks(filePath);
      setDocChunks(result.chunks);
    } catch {
      setDocChunks([]);
    } finally {
      setDocChunksLoading(false);
    }
  };

  const addRef = (ref: RegulationRef) => {
    if (currentRefs.some(r => r.doc_name === ref.doc_name && r.article === ref.article)) {
      message.info('该条款已引用');
      return;
    }
    setCurrentRefs(prev => [...prev, ref]);
  };

  const removeRef = (index: number) => {
    setCurrentRefs(prev => prev.filter((_, i) => i !== index));
  };

  const handleSave = async () => {
    try {
      await evalApi.updateEvalSample(sample.id, {
        ...sample,
        ground_truth: editGroundTruth,
        regulation_refs: currentRefs,
      });
      message.success('已保存，审核状态重置为待审核');
      onSaved();
    } catch (err) {
      message.error(`保存失败: ${err}`);
    }
  };

  const handleApprove = async () => {
    try {
      await evalApi.updateEvalSample(sample.id, {
        ...sample,
        ground_truth: editGroundTruth,
        regulation_refs: currentRefs,
      });
      await evalApi.approveSample(sample.id, 'admin', editComment);
      message.success('审核通过');
      onClose();
      onSaved();
    } catch (err) {
      message.error(`审核失败: ${err}`);
    }
  };

  // 构建目录树
  const treeData = useMemo(() => {
    const dirMap = new Map<string, { docs: { name: string; file_path: string; clause_count: number }[]; clauses: number }>();
    kbDocs.forEach(doc => {
      const parts = doc.file_path.split('/');
      const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : '根目录';
      const existing = dirMap.get(dir) || { docs: [], clauses: 0 };
      existing.docs.push(doc);
      existing.clauses += doc.clause_count;
      dirMap.set(dir, existing);
    });

    return Array.from(dirMap.entries()).map(([dir, info]) => {
      const dirName = dir.split('/').pop() || dir;
      const children = info.docs.map(d => ({
        key: d.file_path,
        title: (
          <span>
            <span>{d.name}</span>
            <Tag style={{ marginLeft: 6, fontSize: token.fontSizeSM }}>{d.clause_count} 条</Tag>
          </span>
        ),
        isLeaf: true,
      }));
      return {
        key: dir,
        title: (
          <span>
            <FolderOutlined style={{ marginRight: 6, color: token.colorPrimary }} />
            <span>{dirName}</span>
            <Tag style={{ marginLeft: 6, fontSize: token.fontSizeSM }}>{info.docs.length} 篇</Tag>
          </span>
        ),
        children,
      };
    });
  }, [kbDocs]);

  const handleTreeSelect = (selectedKeys: React.Key[]) => {
    if (selectedKeys.length > 0) {
      const key = selectedKeys[0] as string;
      handleSelectDoc(key);
    }
  };

  if (!sample) return null;

  const drawerTitle = (
    <Space>
      <span>{sample.id}</span>
      <Tag color={TYPE_COLORS[sample.question_type] || 'default'}>{sample.question_type}</Tag>
      <Tag color={REVIEW_STATUS_TAG[sample.review_status]?.color}>
        {REVIEW_STATUS_TAG[sample.review_status]?.label}
      </Tag>
    </Space>
  );

  const searchTab = (
    <div>
      <div style={{ display: 'flex', gap: 8 }}>
        <Input
          placeholder="输入问题关键词..."
          value={kbQuery}
          onChange={(e) => setKbQuery(e.target.value)}
          onPressEnter={handleSearchKb}
        />
        <Button icon={<SearchOutlined />} loading={kbSearching} onClick={handleSearchKb}>搜索</Button>
      </div>
      {kbSearchDone && kbResults.length === 0 && !kbSearching && (
        <div style={{ color: token.colorTextQuaternary, fontSize: token.fontSize, marginTop: 8 }}>无搜索结果</div>
      )}
      {kbResults.length > 0 && (
        <div style={{ marginTop: 8, maxHeight: 320, overflow: 'auto' }}>
          {kbResults.map((r, idx) => (
            <div key={idx} className="info-card" style={{ fontSize: token.fontSize }}>
              <div className="flex-between">
                <Space>
                  <Tag>{r.article || '-'}</Tag>
                  <Text ellipsis style={{ maxWidth: 200 }}>{r.doc_name}</Text>
                </Space>
                <Button type="link" size="small" icon={<LinkOutlined />}
                  onClick={() => addRef({ doc_name: r.doc_name, article: r.article, excerpt: r.excerpt, chunk_id: r.chunk_id })} />
              </div>
              {r.hierarchy_path && (
                <div style={{ marginTop: 2, color: token.colorTextTertiary, fontSize: token.fontSizeSM }}>{r.hierarchy_path}</div>
              )}
              <div style={{ marginTop: 2, color: token.colorTextSecondary, fontSize: token.fontSizeSM }}>
                {r.excerpt.length > 120 ? r.excerpt.slice(0, 120) + '...' : r.excerpt}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  const browseTab = (
    <div style={{ minHeight: 320 }}>
      {kbDocsLoading && <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>加载中...</Text>}
      {kbDocs.length > 0 && (
        <div style={{ display: 'flex', height: 320 }}>
          <div style={{ width: treeWidth, minWidth: treeWidth, overflow: 'auto', paddingRight: 4 }}>
            <Tree
              showLine
              treeData={treeData}
              onSelect={handleTreeSelect}
              selectedKeys={selectedDocPath ? [selectedDocPath] : []}
              style={{ fontSize: token.fontSize }}
            />
          </div>
          <div
            onMouseDown={handleTreeResizeStart}
            style={{
              width: 4,
              cursor: 'col-resize',
              background: treeResizing ? token.colorPrimary : token.colorBorderSecondary,
              flexShrink: 0,
              transition: treeResizing ? 'none' : 'background 0.2s',
            }}
          />
          <div style={{ flex: 1, overflow: 'auto', paddingLeft: 8 }}>
            {docChunksLoading && (
              <div style={{ color: token.colorTextQuaternary, fontSize: token.fontSizeSM }}>加载条款中...</div>
            )}
            {selectedDocPath && !docChunksLoading && docChunks.length === 0 && (
              <div style={{ color: token.colorTextQuaternary, fontSize: token.fontSizeSM }}>该文档无条款数据</div>
            )}
            {!selectedDocPath && !docChunksLoading && (
              <div style={{ color: token.colorTextQuaternary, fontSize: token.fontSizeSM }}>请在左侧选择文档</div>
            )}
            {docChunks.map((chunk, idx) => (
              <div key={idx} className="info-card" style={{ fontSize: token.fontSize }}>
                <div className="flex-between">
                  <Space>
                    <Tag>{chunk.article_number || '-'}</Tag>
                    {chunk.hierarchy_path && (
                      <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>{chunk.hierarchy_path.split(' > ').pop()}</Text>
                    )}
                  </Space>
                  <Button type="link" size="small" icon={<LinkOutlined />}
                    onClick={() => addRef({
                      doc_name: chunk.source_file,
                      article: chunk.article_number,
                      excerpt: chunk.text,
                      chunk_id: '',
                    })} />
                </div>
                <div style={{ marginTop: 2, color: token.colorTextSecondary, fontSize: token.fontSizeSM }}>
                  {chunk.text.length > 120 ? chunk.text.slice(0, 120) + '...' : chunk.text}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );

  return (
    <Drawer
      title={drawerTitle}
      open={open}
      onClose={onClose}
      width={drawerWidth}
      styles={{ body: { overflowY: 'auto', paddingBottom: 60 } }}
      footer={
        <div className="flex-between">
          <Space>
            <span style={{ fontSize: token.fontSize }}>备注：</span>
            <Input size="small" style={{ width: 400 }} value={editComment}
              onChange={(e) => setEditComment(e.target.value)} placeholder="审核意见（可选）" />
          </Space>
          <Space>
            <Button onClick={handleSave}>保存</Button>
            <Button type="primary" onClick={handleApprove}>审核通过</Button>
          </Space>
        </div>
      }
    >
      {/* 拖拽把手 */}
      <div
        onMouseDown={handleResizeStart}
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          bottom: 0,
          width: 4,
          cursor: 'col-resize',
          zIndex: 10,
          background: resizing ? token.colorPrimary : 'transparent',
          transition: resizing ? 'none' : 'background 0.2s',
        }}
        onMouseEnter={(e) => {
          if (!resizing) (e.currentTarget as HTMLDivElement).style.background = token.colorBorder;
        }}
        onMouseLeave={(e) => {
          if (!resizing) (e.currentTarget as HTMLDivElement).style.background = 'transparent';
        }}
      />

      <div style={{ marginBottom: 16 }}>
        <Text type="secondary">问题</Text>
        <div style={{ marginTop: 4, fontSize: 14 }}>{sample.question}</div>
      </div>

      <div style={{ marginBottom: 16 }}>
        <Text type="secondary">标准答案</Text>
        <Input.TextArea
          rows={3}
          value={editGroundTruth}
          onChange={(e) => setEditGroundTruth(e.target.value)}
          style={{ marginTop: 4 }}
        />
      </div>

      <div style={{ marginBottom: 16 }}>
        <Text type="secondary">已引用法规 ({currentRefs.length})</Text>
        {currentRefs.length === 0 && (
          <div style={{ color: token.colorTextQuaternary, fontSize: token.fontSize, marginTop: 4 }}>暂无引用，请在下方搜索或浏览法规库添加</div>
        )}
        {currentRefs.map((ref, idx) => (
          <div key={idx} className="info-card" style={{ marginTop: 4, fontSize: token.fontSize }}>
            <div className="flex-between">
              <Space>
                <Tag>{ref.article}</Tag>
                <Text>{ref.doc_name}</Text>
              </Space>
              <Button type="text" size="small" danger icon={<CloseCircleOutlined />}
                onClick={() => removeRef(idx)} />
            </div>
            <div style={{ marginTop: 2, color: token.colorTextSecondary, fontSize: token.fontSizeSM }}>
              {ref.excerpt && ref.excerpt.length > 150 ? ref.excerpt.slice(0, 150) + '...' : ref.excerpt}
            </div>
          </div>
        ))}
      </div>

      <Divider style={{ margin: '12px 0' }} />

      <Tabs
        size="small"
        items={[
          { key: 'search', label: '搜索法规', children: searchTab },
          { key: 'browse', label: '浏览法规', children: browseTab },
        ]}
      />
    </Drawer>
  );
}

export default function EvalPage() {
  const { token } = theme.useToken();
  const [activeTab, setActiveTab] = useState('dataset');

  const [samples, setSamples] = useState<EvalSample[]>([]);
  const [snapshots, setSnapshots] = useState<EvalSnapshot[]>([]);
  const [samplesLoading, setSamplesLoading] = useState(false);
  const [filters, setFilters] = useState<{ question_type?: string; difficulty?: string; topic?: string; review_status?: string }>({});
  const [reviewStats, setReviewStats] = useState<{ total: number; pending: number; approved: number }>({ total: 0, pending: 0, approved: 0 });
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingSample, setEditingSample] = useState<Partial<EvalSample> | null>(null);
  const [drawerSample, setDrawerSample] = useState<EvalSample | null>(null);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importText, setImportText] = useState('');
  const [snapshotModalOpen, setSnapshotModalOpen] = useState(false);
  const [snapshotName, setSnapshotName] = useState('');
  const [snapshotDescription, setSnapshotDescription] = useState('');
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
  const EVAL_PAGE_SIZE = 20;

  const hasSelection = selectedEvalIds.length > 0;
  const evalPaged = useMemo(
    () => evaluations.slice((evalPage - 1) * EVAL_PAGE_SIZE, evalPage * EVAL_PAGE_SIZE),
    [evaluations, evalPage],
  );
  const evalAllSelected = evalPaged.length > 0 && evalPaged.every((e) => selectedEvalIds.includes(e.id));

  const toggleEvalSelection = (id: string, checked: boolean) => {
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

  const load_review_stats = useCallback(async () => {
    try {
      const statsData = await evalApi.fetchReviewStats();
      setReviewStats(statsData);
    } catch {
      // non-critical
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'dataset') {
      load_samples();
      load_review_stats();
    }
  }, [activeTab, load_samples, load_review_stats]);

  const create_sample = () => {
    setEditingSample(null);
    form.resetFields();
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
      await evalApi.createSnapshot(snapshotName, snapshotDescription);
      message.success('快照创建成功');
      setSnapshotModalOpen(false);
      setSnapshotName('');
      setSnapshotDescription('');
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
    {
      title: '审核', dataIndex: 'review_status', key: 'review_status', width: 70,
      render: (v: string) => {
        const info = REVIEW_STATUS_TAG[v] || { color: 'default', label: v };
        return <Tag color={info.color} style={{ margin: 0 }}>{info.label}</Tag>;
      },
    },
    { title: 'ID', dataIndex: 'id', key: 'id', width: 100, ellipsis: true },
    { title: '问题', dataIndex: 'question', key: 'question', ellipsis: true },
    {
      title: '类型', dataIndex: 'question_type', key: 'question_type', width: 140,
      render: (t: string) => <Tag color={TYPE_COLORS[t] || 'default'}>{t}</Tag>,
    },
    { title: '难度', dataIndex: 'difficulty', key: 'difficulty', width: 80 },
    { title: '主题', dataIndex: 'topic', key: 'topic', width: 100 },
    {
      title: '引用', dataIndex: 'regulation_refs', key: 'regulation_refs', width: 60,
      render: (refs: RegulationRef[]) => (
        <Text type="secondary">{refs?.length || 0}</Text>
      ),
    },
    {
      title: '操作', key: 'action', width: 120,
      render: (_: undefined, sample: EvalSample) => (
        <Space>
          <Button type="link" size="small" onClick={() => setDrawerSample(sample)}>审核</Button>
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
          min_score: values.rerank_min_score,
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
      title: '配置', dataIndex: 'config', key: 'config', width: 80,
      render: (_: unknown, e: Evaluation) => {
        const cv = e.config_version;
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
      <Title level={4} className="mb-16">评测管理</Title>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'dataset',
            label: '评测数据集',
            children: (
              <>
                <div className="flex-between" style={{ marginBottom: 12 }}>
                  <Space>
                    <Select
                      placeholder="审核状态" allowClear style={{ width: 110 }}
                      value={filters.review_status}
                      onChange={(v) => setFilters({ ...filters, review_status: v })}
                      options={[
                        { value: 'pending', label: `待审核 (${reviewStats.pending})` },
                        { value: 'approved', label: `已通过 (${reviewStats.approved})` },
                      ]}
                    />
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
                        size="small"
                        scroll={{ x: 750 }}
                        onRow={(sample) => ({
                          onClick: () => setDrawerSample(sample),
                          style: { cursor: 'pointer' },
                        })}
                      />
                    </Card>
                  </Col>
                  <Col span={8}>
                    <Card title="快照历史" size="small">
                      {snapshots.length === 0 ? (
                        <Text type="secondary">暂无快照</Text>
                      ) : (
                        snapshots.map((snapshot) => (
                          <div key={snapshot.id} className="flex-between" style={{ marginBottom: 8 }}>
                            <div>
                              <Space>
                                <Text strong>{snapshot.name}</Text>
                                <Tag>v{snapshot.version}</Tag>
                              </Space>
                              <Text type="secondary" style={{ marginLeft: 8 }}>{snapshot.sample_count} 条</Text>
                              <br />
                              <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
                                {snapshot.created_at}
                                {snapshot.hash_code && (
                                  <span style={{ marginLeft: 8, fontFamily: 'monospace' }}>{snapshot.hash_code}</span>
                                )}
                              </Text>
                              {snapshot.description && (
                                <div style={{ fontSize: token.fontSizeSM, color: token.colorTextSecondary, marginTop: 2 }}>{snapshot.description}</div>
                              )}
                            </div>
                            <Space>
                              <Popconfirm title={`确定恢复到 ${snapshot.name}？当前数据将被覆盖。`} onConfirm={() => restore_snapshot(snapshot.id)}>
                                <Button type="link" size="small" icon={<RollbackOutlined />}>恢复</Button>
                              </Popconfirm>
                              <Popconfirm title={`确定删除快照 ${snapshot.name}？`} onConfirm={async () => {
                                try {
                                  await evalApi.deleteSnapshot(snapshot.id);
                                  message.success('快照已删除');
                                  load_samples();
                                } catch (err) {
                                  message.error(String(err));
                                }
                              }}>
                                <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                              </Popconfirm>
                            </Space>
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
            key: 'configs',
            label: '配置管理',
            children: (
              <Row gutter={16}>
                <Col span={10}>
                  <Card title="配置列表" size="small" bodyStyle={{ padding: 0, overflow: 'hidden' }}
                    extra={<Button type="primary" size="small" icon={<PlusOutlined />} onClick={start_new_config}>新增</Button>}
                  >
                    <div style={{ overflow: 'auto', maxHeight: 'calc(100vh - var(--header-height) - 206px)' }}>
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
                            background: viewingConfig?.id === cfg.id ? token.colorPrimaryBg : undefined,
                          },
                        })}
                      />
                    </div>
                    <div className="table-footer">
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
                            <span style={{ color: token.colorPrimary }}>{configSelectedIds.length} 项</span>
                            <span style={{ fontSize: token.fontSizeSM, color: token.colorTextQuaternary }}>(含生效中不可删除)</span>
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
                      <div className="flex-between mb-16">
                        <span style={{ fontWeight: token.fontWeightStrong }}>配置详情</span>
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
                            <Text type="secondary">启用重排序</Text>
                            <Tag color={viewingConfigJson.rerank?.enable_rerank ? 'green' : 'default'}>{viewingConfigJson.rerank?.enable_rerank ? '是' : '否'}</Tag>
                          </div>
                        }
                      >
                        <Descriptions bordered size="small" column={3}>
                          <Descriptions.Item label="重排序器">{viewingConfigJson.rerank?.reranker_type}</Descriptions.Item>
                          <Descriptions.Item label="重排序 Top-K">{viewingConfigJson.rerank?.rerank_top_k}</Descriptions.Item>
                          <Descriptions.Item label="最小重排序分数">{viewingConfigJson.rerank?.min_score}</Descriptions.Item>
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
                      <div className="flex-between mb-16">
                        <span style={{ fontWeight: token.fontWeightStrong }}>新建配置</span>
                        <Space>
                          <Button type="primary" onClick={save_config}>保存</Button>
                          <Button onClick={() => { setEditingConfig(false); setViewingConfig(null); }}>取消</Button>
                        </Space>
                      </div>

                      <Form form={editForm} layout="vertical">
                        <Form.Item name="description" label="配置说明">
                          <Input placeholder="如：关闭 reranker 的配置" />
                        </Form.Item>

                        <Card size="small" title="检索参数" style={{ marginBottom: 8 }}>
                          <Row gutter={16}>
                            <Col span={12}>
                              <Form.Item name="retrieval_vector_top_k" label="向量 Top-K">
                                <InputNumber min={1} style={{ width: '100%' }} />
                              </Form.Item>
                            </Col>
                            <Col span={12}>
                              <Form.Item name="retrieval_keyword_top_k" label="关键词 Top-K">
                                <InputNumber min={1} style={{ width: '100%' }} />
                              </Form.Item>
                            </Col>
                            <Col span={12}>
                              <Form.Item name="retrieval_rrf_k" label="RRF K">
                                <InputNumber min={1} style={{ width: '100%' }} />
                              </Form.Item>
                            </Col>
                            <Col span={12}>
                              <Form.Item name="retrieval_max_chunks_per_article" label="单篇最大 Chunk">
                                <InputNumber min={1} style={{ width: '100%' }} />
                              </Form.Item>
                            </Col>
                            <Col span={12}>
                              <Form.Item name="retrieval_min_rrf_score" label="最小 RRF 分数">
                                <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} />
                              </Form.Item>
                            </Col>
                          </Row>
                        </Card>

                        <Card
                          size="small"
                          title="重排序参数"
                          style={{ marginBottom: 8 }}
                          extra={
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <Text type="secondary">启用重排序</Text>
                              <Form.Item name="rerank_enable_rerank" valuePropName="checked" style={{ marginBottom: 0 }}>
                                <Switch checkedChildren="开" unCheckedChildren="关" />
                              </Form.Item>
                            </div>
                          }
                        >
                          <Row gutter={16}>
                            <Col span={12}>
                              <Form.Item name="rerank_reranker_type" label="重排序器">
                                <Select disabled={!rerankEnabled} options={[
                                  { value: 'gguf', label: 'GGUF' },
                                  { value: 'llm', label: 'LLM' },
                                  { value: 'none', label: 'None' },
                                ]} />
                              </Form.Item>
                            </Col>
                            <Col span={12}>
                              <Form.Item name="rerank_rerank_top_k" label="重排序 Top-K">
                                <InputNumber min={1} disabled={!rerankEnabled} style={{ width: '100%' }} />
                              </Form.Item>
                            </Col>
                            <Col span={12}>
                              <Form.Item name="rerank_min_score" label="最小重排序分数">
                                <InputNumber min={0} max={1} step={0.1} disabled={!rerankEnabled} style={{ width: '100%' }} />
                              </Form.Item>
                            </Col>
                          </Row>
                        </Card>

                        <Card size="small" title="生成参数">
                          <Form.Item name="generation_max_context_chars" label="最大上下文字符数">
                            <InputNumber min={500} max={50000} step={1000} style={{ width: '100%' }} />
                          </Form.Item>
                        </Card>
                      </Form>
                    </>
                  )}

                  {!editingConfig && !viewingConfig && (
                    <div className="empty-state">
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
                <div className="flex-between" style={{ marginBottom: 12 }}>
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
                    <div className="flex-between" style={{ marginBottom: 8 }}>
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
                          <div className="empty-state" style={{ fontSize: token.fontSizeSM }}>加载中...</div>
                        ) : evalPaged.length === 0 ? (
                          <div className="empty-state" style={{ fontSize: token.fontSizeSM }}>暂无评测记录</div>
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
                                    onChange={(ev) => toggleEvalSelection(e.id, ev.target.checked)}
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
                                background: selectedEvaluation?.id === evaluation.id ? token.colorPrimaryBg : undefined,
                              },
                            })}
                          />
                        )}
                      </div>
                      <div className="table-footer">
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
                              <span style={{ color: token.colorPrimary }}>{selectedEvalIds.length} 项</span>
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
                          <Descriptions.Item label="配置版本">{selectedEvaluation.config_version ? `v${selectedEvaluation.config_version}` : '-'}</Descriptions.Item>
                          <Descriptions.Item label="启动时间">{selectedEvaluation.started_at}</Descriptions.Item>
                          <Descriptions.Item label="数据集版本" span={2}>{selectedEvaluation.dataset_version || '-'}</Descriptions.Item>
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
                                      <div style={{ marginTop: 4, padding: 8, background: token.colorFillTertiary, borderRadius: 4 }}>
                                        {record.generated_answer || '-'}
                                      </div>
                                      {record.retrieved_docs.length > 0 && (
                                        <>
                                          <Text strong style={{ marginTop: 8, display: 'block' }}>检索结果：</Text>
                                          {record.retrieved_docs.map((doc, i) => (
                                            <div key={i} style={{ padding: 4, fontSize: token.fontSize }}>
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

      <SampleDrawer
        sample={drawerSample!}
        open={!!drawerSample}
        onClose={() => setDrawerSample(null)}
        onSaved={() => { load_samples(); load_review_stats(); }}
      />

      <Modal
        title={editingSample ? '编辑评测问题' : '新增评测问题'}
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={save_sample}
        width={MODAL_MD}
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
        width={MODAL_MD}
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
          style={{ marginBottom: 12 }}
        />
        <Input.TextArea
          rows={2}
          placeholder="描述（可选）"
          value={snapshotDescription}
          onChange={(e) => setSnapshotDescription(e.target.value)}
        />
      </Modal>

      <Modal
        title="版本对比"
        open={compareModalOpen}
        onCancel={() => { setCompareModalOpen(false); setCompareResult(null); }}
        width={MODAL_LG}
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
                  render: (v: number) => <span style={{ color: v > 0 ? token.colorSuccess : v < 0 ? token.colorError : token.colorTextTertiary }}>{v > 0 ? '+' : ''}{v.toFixed(1)}%</span> },
                { title: '趋势', dataIndex: 'trend', key: 'trend', width: 60,
                  render: (v: string) => <span style={{ color: v === '\u2191' ? token.colorSuccess : v === '\u2193' ? token.colorError : token.colorTextTertiary, fontWeight: token.fontWeightStrong }}>{v}</span> },
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
        styles={{ body: { maxHeight: 'calc(100vh - var(--header-height) - 136px)', overflowY: 'auto' } }}
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
                return <span style={{ color: unique ? token.colorPrimary : undefined, fontWeight: unique ? token.fontWeightStrong : undefined }}>{String(val)}</span>;
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
