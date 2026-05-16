import React, { useState, useEffect, useRef } from 'react';
import { useUnsavedChanges } from '../hooks/useUnsavedChanges';
import {
  Card, Input, Button, Tag, Typography, theme,
  message, Space, Descriptions, Drawer, Grid,
  Alert, Select, Popconfirm, Spin,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined,
  DeleteOutlined, BookOutlined, ArrowLeftOutlined, CloseOutlined,
  SafetyCertificateOutlined, UploadOutlined, FileTextOutlined,
} from '@ant-design/icons';
import * as complianceApi from '../api/compliance';
import type { ComplianceReport, AuditResultItem, AuditRegulationItem, ParsedDocument } from '../types';
import { DRAWER_MD } from '../constants/layout';
import PageHeader from '../components/PageHeader';

const { Text } = Typography;
const { TextArea } = Input;

const STATUS_ICON: Record<string, { color: string; icon: React.ReactNode }> = {
  non_compliant: { color: 'error', icon: <CloseCircleOutlined /> },
  attention: { color: 'warning', icon: <ExclamationCircleOutlined /> },
  compliant: { color: 'success', icon: <CheckCircleOutlined /> },
};

function RegulationDrawer({
  visible, regulation, onClose, isMobile,
}: {
  visible: boolean; regulation: AuditRegulationItem | null; onClose: () => void; isMobile: boolean;
}) {
  const { token } = theme.useToken();
  if (!regulation) return null;
  return (
    <Drawer
      title={<Space><BookOutlined />法规来源详情</Space>}
      placement="right"
      width={isMobile ? '100%' : DRAWER_MD}
      open={visible}
      onClose={onClose}
    >
      <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
        <Descriptions.Item label="法规名称">{regulation.law_name}</Descriptions.Item>
        <Descriptions.Item label="条款编号">{regulation.article_number}</Descriptions.Item>
        {regulation.doc_number && <Descriptions.Item label="文号">{regulation.doc_number}</Descriptions.Item>}
        {regulation.issuing_authority && <Descriptions.Item label="发布机关">{regulation.issuing_authority}</Descriptions.Item>}
        {regulation.effective_date && <Descriptions.Item label="生效日期">{regulation.effective_date}</Descriptions.Item>}
        <Descriptions.Item label="来源类型">
          <Tag color={regulation.source_type === 'category' ? 'blue' : regulation.source_type === 'negative_list' ? 'red' : 'default'}>
            {regulation.source_type === 'category' ? '险种专属' : regulation.source_type === 'general' ? '通用法规' : '负面清单'}
          </Tag>
        </Descriptions.Item>
      </Descriptions>
      <Text strong style={{ display: 'block', marginBottom: 8 }}>法规原文</Text>
      <div style={{
        background: token.colorFillQuaternary, border: `1px solid ${token.colorBorder}`,
        borderRadius: 4, padding: 12, maxHeight: 300, overflow: 'auto', whiteSpace: 'pre-wrap',
      }}>
        {regulation.content}
      </div>
    </Drawer>
  );
}

function ClauseCard({
  item, regulationMap, onRegulationClick, token,
}: {
  item: AuditResultItem;
  regulationMap: Record<string, AuditRegulationItem>;
  onRegulationClick: (chunkId: string) => void;
  token: ReturnType<typeof theme.useToken>['token'];
}) {
  const merged = (item as AuditResultItem & { _mergedChunkIds?: string[] })._mergedChunkIds;
  const chunkIds = merged || (item.chunk_id ? [item.chunk_id] : []);
  const regs = chunkIds.map(id => regulationMap[id]).filter(Boolean);
  const cfg = STATUS_ICON[item.status] || STATUS_ICON.attention;
  const borderColor = item.status === 'non_compliant'
    ? token.colorErrorBorder
    : item.status === 'attention'
      ? token.colorWarningBorder
      : token.colorBorder;

  return (
    <Card
      size="small"
      style={{ borderLeft: `3px solid ${borderColor}`, marginBottom: 12 }}
      styles={{ body: { padding: '12px 16px' } }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <Tag color={cfg.color} icon={cfg.icon} style={{ margin: 0 }}>
              条款 {item.clause_number}
            </Tag>
            {regs.map(reg => {
              const lawShort = reg.law_name?.replace(/[《》]/g, '');
              const label = [lawShort, reg.article_number].filter(Boolean).join(' ');
              return (
                <a key={reg.chunk_id} role="button" tabIndex={0}
                  onClick={() => onRegulationClick(reg.chunk_id)}
                  onKeyDown={(e: React.KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onRegulationClick(reg.chunk_id); } }}
                  style={{ fontSize: token.fontSizeSM, color: token.colorPrimary }}
                >
                  {label}
                </a>
              );
            })}
          </div>
          <div style={{ whiteSpace: 'pre-wrap', color: token.colorTextSecondary, fontSize: token.fontSizeSM, lineHeight: 1.6 }}>
            {item.clause_content}
          </div>
        </div>
      </div>
      {item.conclusion && (
        <div style={{ marginTop: 8, fontSize: token.fontSizeSM, color: token.colorText }}>
          {item.conclusion}
        </div>
      )}
      {item.suggestion && (
        <div style={{ marginTop: 6, fontSize: token.fontSizeSM }}>
          <Text type="secondary">修改建议：</Text>
          <Text>{item.suggestion}</Text>
        </div>
      )}
    </Card>
  );
}

export default function CompliancePage() {
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  // Two states: 'input' | 'result'
  const [view, setView] = useState<'input' | 'result'>('input');

  // Input state
  const [parsing, setParsing] = useState(false);
  const [richTextContent, setRichTextContent] = useState('');
  const [parsedDocument, setParsedDocument] = useState<ParsedDocument | null>(null);
  const [productName, setProductName] = useState('');
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useUnsavedChanges(uploadedFile !== null);

  // Category
  const [identifiedCategory, setIdentifiedCategory] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [categoryConfidence, setCategoryConfidence] = useState<number>(0);
  const [validCategories, setValidCategories] = useState<string[]>([]);
  const showCategorySelect = identifiedCategory && categoryConfidence < 0.7;

  // Result state
  const [checkingResult, setCheckingResult] = useState<ComplianceReport | null>(null);
  const [streamingViolations, setStreamingViolations] = useState<AuditResultItem[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamProgress, setStreamProgress] = useState('');
  const streamAbortRef = useRef<AbortController | null>(null);

  // Regulation drawer
  const [regulationDrawerVisible, setRegulationDrawerVisible] = useState(false);
  const [selectedRegulation, setSelectedRegulation] = useState<AuditRegulationItem | null>(null);

  // History
  const [history, setHistory] = useState<ComplianceReport[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    loadCategories();
    loadHistory();
  }, []);

  const loadCategories = async () => {
    try { setValidCategories(await complianceApi.fetchCategories()); } catch { /* empty */ }
  };

  const loadHistory = async () => {
    setHistoryLoading(true);
    try { setHistory(await complianceApi.fetchComplianceReports()); }
    finally { setHistoryLoading(false); }
  };

  const applyParseResult = (result: ParsedDocument, name?: string) => {
    setParsedDocument(result);
    setProductName(name || result.file_name || '');
    setIdentifiedCategory(result.identified_category);
    setCategoryConfidence(result.category_confidence);
    setSelectedCategory(result.identified_category || '');
  };

  const handleFileUpload = async (file: File) => {
    setParsing(true);
    setUploadedFile(file);
    try {
      const result = await complianceApi.parseFile(file);
      applyParseResult(result);
    } catch (err: unknown) {
      message.error(`解析失败: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setParsing(false);
    }
  };

  useEffect(() => {
    if (uploadedFile || !richTextContent.trim()) return;
    const timer = setTimeout(async () => {
      setParsing(true);
      try {
        const result = await complianceApi.parseRichText(richTextContent);
        applyParseResult(result, '');
      } catch { /* silent */ }
      finally { setParsing(false); }
    }, 500);
    return () => clearTimeout(timer);
  }, [richTextContent, uploadedFile]);

  const handleStartReview = () => {
    if (!parsedDocument) return;
    setStreamingViolations([]);
    setIsStreaming(true);
    setStreamProgress('法规审查中...');
    setCheckingResult(null);
    setView('result');

    streamAbortRef.current = complianceApi.checkDocumentStream(
      {
        document_content: parsedDocument.combined_text,
        product_name: productName || parsedDocument.file_name || undefined,
        category: selectedCategory || undefined,
      },
      {
        onViolation: (item) => setStreamingViolations(prev => [...prev, item]),
        onProgress: (msg) => setStreamProgress(msg),
        onDone: (data) => {
          setIsStreaming(false);
          setStreamProgress('');
          setCheckingResult({
            id: data.report_id,
            product_name: data.product_name,
            category: data.category,
            mode: 'document',
            result: {
              summary: data.summary,
              items: data.items,
              regulations: [],
              regulation_sources: data.regulation_sources,
              category: data.category,
              negative_list_result: data.negative_list_result,
              clause_coverage: data.clause_coverage,
            },
            created_at: '',
          });
          message.success(`审查完成，发现 ${data.summary.non_compliant} 条不合规`);
          loadHistory();
        },
        onError: (err) => {
          setIsStreaming(false);
          setStreamProgress('');
          message.error(`检查失败: ${err}`);
        },
      },
    );
  };

  const handleBack = () => {
    streamAbortRef.current?.abort();
    setIsStreaming(false);
    setStreamingViolations([]);
    setStreamProgress('');
    setCheckingResult(null);
    setView('input');
  };

  const handleViewReport = async (reportId: string) => {
    try {
      const report = await complianceApi.fetchComplianceReport(reportId);
      setCheckingResult(report);
      setView('result');
    } catch (err: unknown) {
      message.error(`加载报告失败: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleDeleteReport = async (reportId: string) => {
    try {
      await complianceApi.deleteComplianceReport(reportId);
      message.success('删除成功');
      loadHistory();
    } catch (err: unknown) {
      message.error(`删除失败: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleRegulationClick = (chunkId: string) => {
    const regulations = checkingResult?.result?.regulations;
    if (!regulations) return;
    const reg = Object.fromEntries(regulations.map(r => [r.chunk_id, r]))[chunkId];
    if (reg) {
      setSelectedRegulation(reg);
      setRegulationDrawerVisible(true);
    }
  };

  const mergeItemsByClause = (items: AuditResultItem[]): AuditResultItem[] => {
    const groups = new Map<string, AuditResultItem[]>();
    for (const item of items) {
      const key = item.clause_number || '未知';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(item);
    }
    const merged: AuditResultItem[] = [];
    for (const [, group] of groups) {
      if (group.length === 1) { merged.push(group[0]); continue; }
      const statuses = group.map(g => g.status);
      const worst = statuses.includes('non_compliant') ? 'non_compliant' : statuses.includes('attention') ? 'attention' : 'compliant';
      const suggestions = [...new Set(group.map(g => g.suggestion).filter(Boolean))];
      const sources = [...new Set(group.map(g => g.chunk_id).filter(Boolean) as string[])];
      merged.push({
        ...group[0], status: worst, suggestion: suggestions.join('\n'),
        chunk_id: sources[0] || null,
        _mergedChunkIds: sources, _mergedItems: group,
      } as AuditResultItem & { _mergedChunkIds?: string[] });
    }
    return merged;
  };

  // ─── INPUT VIEW ────────────────────────────────────────────
  const renderInputView = () => {
    const canReview = parsedDocument && !parsing;
    return (
      <div style={{ maxWidth: 720, margin: '0 auto' }}>
        {/* Upload area */}
        <Card
          style={{ marginBottom: 16, cursor: 'pointer', textAlign: 'center' }}
          styles={{ body: { padding: isMobile ? 24 : 40 } }}
          onClick={() => fileInputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e: React.KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click(); }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx"
            style={{ display: 'none' }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileUpload(f); }}
          />
          {uploadedFile ? (
            <div>
              <FileTextOutlined style={{ fontSize: 32, color: token.colorPrimary, marginBottom: 8 }} />
              <div><Text strong>{uploadedFile.name}</Text></div>
              <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>点击更换文件</Text>
            </div>
          ) : (
            <div>
              <UploadOutlined style={{ fontSize: 32, color: token.colorTextSecondary, marginBottom: 8 }} />
              <div><Text>点击上传文件</Text></div>
              <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>支持 PDF、DOCX</Text>
            </div>
          )}
        </Card>

        {/* Divider */}
        <div style={{ textAlign: 'center', margin: '8px 0', color: token.colorTextSecondary }}>
          <Text type="secondary">或粘贴文本</Text>
        </div>

        {/* Text input */}
        <TextArea
          style={{ marginBottom: 16, minHeight: 160, resize: 'vertical' }}
          placeholder="请输入或粘贴保险条款文档内容…"
          aria-label="保险条款文档内容"
          spellCheck
          value={richTextContent}
          onChange={(e) => setRichTextContent(e.target.value)}
          disabled={!!uploadedFile}
        />

        {/* Parsing indicator */}
        {parsing && (
          <div style={{ textAlign: 'center', padding: '8px 0' }}>
            <Spin size="small" /> <Text type="secondary" style={{ marginLeft: 8 }}>正在解析文档…</Text>
          </div>
        )}

        {/* Category selection — only show when low confidence */}
        {showCategorySelect && (
          <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
            <Text>险种类型：</Text>
            <Select
              style={{ width: 160 }}
              placeholder="选择险种类型"
              value={selectedCategory || undefined}
              onChange={setSelectedCategory}
              options={validCategories.map(c => ({ label: c, value: c }))}
            />
            <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
              自动识别：{identifiedCategory} ({Math.round(categoryConfidence * 100)}%)
            </Text>
          </div>
        )}

        {/* Start button */}
        <Button
          type="primary"
          size="large"
          block
          disabled={!canReview}
          loading={parsing}
          onClick={handleStartReview}
          icon={<SafetyCertificateOutlined />}
        >
          开始审查
        </Button>

        {/* History */}
        {history.length > 0 && (
          <div style={{ marginTop: 32 }}>
            <Text strong style={{ display: 'block', marginBottom: 12, color: token.colorTextSecondary }}>
              审查历史
            </Text>
            {history.slice(0, 10).map(report => {
              const s = report.result?.summary;
              const hasViolation = (s?.non_compliant || 0) > 0;
              return (
                <div
                  key={report.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => handleViewReport(report.id)}
                  onKeyDown={(e: React.KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') handleViewReport(report.id); }}
                  style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '10px 12px', marginBottom: 4, borderRadius: 6, cursor: 'pointer',
                    background: token.colorBgContainer, border: `1px solid ${token.colorBorderSecondary}`,
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      {hasViolation
                        ? <CloseCircleOutlined style={{ color: token.colorError }} />
                        : <CheckCircleOutlined style={{ color: token.colorSuccess }} />
                      }
                      <Text strong ellipsis style={{ maxWidth: 200 }}>{report.product_name}</Text>
                      <Tag style={{ margin: 0 }}>{report.category}</Tag>
                    </div>
                    <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
                      {s ? `${s.non_compliant || 0} 项不合规` : '—'} · {report.created_at?.slice(0, 10)}
                    </Text>
                  </div>
                  <Popconfirm title="确定删除？" onConfirm={(e) => { e?.stopPropagation(); handleDeleteReport(report.id); }}>
                    <Button type="text" size="small" danger icon={<DeleteOutlined />}
                      onClick={(e) => e.stopPropagation()} />
                  </Popconfirm>
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  // ─── RESULT VIEW ───────────────────────────────────────────
  const renderResultView = () => {
    const docResult = checkingResult?.result;
    const regulationMap: Record<string, AuditRegulationItem> = {};
    if (docResult?.regulations) {
      for (const r of docResult.regulations) regulationMap[r.chunk_id] = r;
    }

    // Streaming state
    if (isStreaming) {
      const merged = mergeItemsByClause(streamingViolations);
      return (
        <div style={{ maxWidth: 800, margin: '0 auto' }}>
          {/* Header */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <Button type="text" icon={<ArrowLeftOutlined />} onClick={handleBack}>返回</Button>
            <Button type="text" danger icon={<CloseOutlined />} onClick={handleBack}>取消审查</Button>
          </div>

          {/* Progress */}
          <Alert
            type="info"
            showIcon
            message={streamProgress || '正在分析…'}
            style={{ marginBottom: 16 }}
          />

          {/* Streaming violations */}
          {merged.length > 0 ? (
            <>
              <Text strong style={{ display: 'block', marginBottom: 12 }}>
                已发现 {streamingViolations.length} 项不合规
              </Text>
              {merged.map((item, i) => (
                <ClauseCard
                  key={`${item.clause_number}-${item.check_type}-${i}`}
                  item={item}
                  regulationMap={regulationMap}
                  onRegulationClick={handleRegulationClick}
                  token={token}
                />
              ))}
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: 40 }}>
              <Spin size="large" />
              <div style={{ marginTop: 16 }}><Text type="secondary">正在分析中…</Text></div>
            </div>
          )}
        </div>
      );
    }

    // Final result
    if (!docResult?.summary) return null;
    const s = docResult.summary;
    const hasViolation = (s.non_compliant || 0) > 0;
    const negResult = docResult.negative_list_result;
    const merged = mergeItemsByClause(docResult.items || []);
    const coverage = docResult.clause_coverage;

    return (
      <div style={{ maxWidth: 800, margin: '0 auto' }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={handleBack}>返回</Button>
          <Text strong>{checkingResult?.product_name}</Text>
          <div />
        </div>

        {/* Summary card */}
        <Card
          style={{ marginBottom: 16, borderLeft: `3px solid ${hasViolation ? token.colorError : token.colorSuccess}` }}
          styles={{ body: { padding: 16 } }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
            {hasViolation
              ? <Tag color="error" icon={<CloseCircleOutlined />} style={{ fontSize: 16, padding: '4px 16px' }}>审核未通过</Tag>
              : <Tag color="success" icon={<CheckCircleOutlined />} style={{ fontSize: 16, padding: '4px 16px' }}>审核通过</Tag>
            }
            <Space size={isMobile ? 'small' : 'middle'} wrap>
              {(s.compliant || 0) > 0 && <Tag color="success" icon={<CheckCircleOutlined />}>合规 {s.compliant}</Tag>}
              <Tag color="error" icon={<CloseCircleOutlined />}>不合规 {s.non_compliant || 0}</Tag>
              {(s.attention || 0) > 0 && <Tag color="warning" icon={<ExclamationCircleOutlined />}>需关注 {s.attention}</Tag>}
              {negResult && (
                <Tag color={negResult === 'violated' ? 'error' : 'success'}
                  icon={negResult === 'violated' ? <CloseCircleOutlined /> : <CheckCircleOutlined />}>
                  负面清单{negResult === 'violated' ? '违规' : '通过'}
                </Tag>
              )}
            </Space>
          </div>
          {coverage && coverage.total > 0 && (
            <div style={{ marginTop: 8, fontSize: token.fontSizeSM, color: token.colorTextSecondary }}>
              条款覆盖率：{coverage.checked}/{coverage.total}
              {coverage.unchecked.length > 0 && (
                <span>（未检查：{coverage.unchecked.slice(0, 10).join('、')}{coverage.unchecked.length > 10 ? '…' : ''}）</span>
              )}
            </div>
          )}
        </Card>

        {/* Clause cards */}
        {merged.map((item, i) => (
          <ClauseCard
            key={`${item.clause_number}-${item.check_type}-${i}`}
            item={item}
            regulationMap={regulationMap}
            onRegulationClick={handleRegulationClick}
            token={token}
          />
        ))}
      </div>
    );
  };

  return (
    <div>
      <PageHeader icon={<SafetyCertificateOutlined />} title="合规检查助手" description="检查保险条款文档的合规性" isMobile={isMobile} />
      {view === 'input' ? renderInputView() : renderResultView()}
      <RegulationDrawer
        visible={regulationDrawerVisible}
        regulation={selectedRegulation}
        onClose={() => setRegulationDrawerVisible(false)}
        isMobile={isMobile}
      />
    </div>
  );
}
