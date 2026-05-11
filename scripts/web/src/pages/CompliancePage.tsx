import React, { useState, useEffect } from 'react';
import { useUnsavedChanges } from '../hooks/useUnsavedChanges';
import {
  Card, Input, Button, Table, Tag, Typography, theme,
  message, Tabs, Space, Descriptions, Popconfirm, Drawer, Grid,
  Empty, Alert, Select, Collapse,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined,
  HistoryOutlined, DeleteOutlined, EyeOutlined, BookOutlined,
  FileTextOutlined, PlusOutlined, CaretRightOutlined, CloseOutlined,
} from '@ant-design/icons';
import * as complianceApi from '../api/compliance';
import type { ComplianceReport, AuditResultItem, AuditRegulationItem, ParsedDocument, ParsedDataTable } from '../types';
import { DRAWER_MD, DRAWER_LG } from '../constants/layout';
import { DocumentViewer } from '../components/DocumentViewer';

const { Title, Text } = Typography;
const { TextArea } = Input;

const STATUS_CONFIG: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  compliant: { color: 'success', icon: <CheckCircleOutlined />, label: '合规' },
  non_compliant: { color: 'error', icon: <CloseCircleOutlined />, label: '不合规' },
  attention: { color: 'warning', icon: <ExclamationCircleOutlined />, label: '需关注' },
};

const TABLE_TYPE_LABELS: Record<string, string> = {
  premium: '费率表',
  appendix: '附表',
  coverage: '保障计划表',
  drug_list: '药品清单',
  gene_test: '基因检测清单',
  hospital: '医院名单',
  other: '数据表',
  unknown: '表格',
};

function getTableLabel(t: ParsedDataTable, index: number): string {
  const typeLabel = TABLE_TYPE_LABELS[t.table_type] || '表格';
  const remark = t.remark ? ` (${t.remark.slice(0, 20)})` : '';
  return `${typeLabel} ${index + 1}${remark}`;
}

function RegulationDrawer({
  visible,
  regulation,
  onClose,
  isMobile,
}: {
  visible: boolean;
  regulation: AuditRegulationItem | null;
  onClose: () => void;
  isMobile: boolean;
}) {
  const { token } = theme.useToken();

  if (!regulation) return null;

  return (
    <Drawer
      title={<Space><BookOutlined />法规来源详情</Space>}
      placement="right"
      size={isMobile ? '100%' : DRAWER_MD}
      open={visible}
      onClose={onClose}
    >
      <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
        <Descriptions.Item label="法规名称">{regulation.law_name}</Descriptions.Item>
        <Descriptions.Item label="条款编号">{regulation.article_number}</Descriptions.Item>
        {regulation.doc_number && (
          <Descriptions.Item label="文号">{regulation.doc_number}</Descriptions.Item>
        )}
        {regulation.issuing_authority && (
          <Descriptions.Item label="发布机关">{regulation.issuing_authority}</Descriptions.Item>
        )}
        {regulation.effective_date && (
          <Descriptions.Item label="生效日期">{regulation.effective_date}</Descriptions.Item>
        )}
        <Descriptions.Item label="来源类型">
          <Tag color={regulation.source_type === 'category' ? 'blue' : regulation.source_type === 'negative_list' ? 'red' : 'default'}>
            {regulation.source_type === 'category' ? '险种专属' : regulation.source_type === 'general' ? '通用法规' : '负面清单'}
          </Tag>
        </Descriptions.Item>
      </Descriptions>

      <div>
        <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
          法规原文
        </Typography.Text>
        <div
          style={{
            background: token.colorFillQuaternary,
            border: `1px solid ${token.colorBorder}`,
            borderRadius: 4,
            padding: '12px',
            maxHeight: 300,
            overflow: 'auto',
            whiteSpace: 'pre-wrap',
            fontSize: token.fontSize ?? 14,
          }}
        >
          {regulation.content}
        </div>
      </div>
    </Drawer>
  );
}

function DocumentReviewPanel({
  document: doc,
  file,
  richText,
  onRichTextChange,
  onFileUpload,
  onConfirm,
  loading,
  selectedCategory,
  onCategoryChange,
  identifiedCategory,
  categoryConfidence,
  validCategories,
}: {
  document: ParsedDocument | null;
  file: File | null;
  richText: string;
  onRichTextChange: (v: string) => void;
  onFileUpload: (file: File) => void;
  onConfirm: () => void;
  loading: boolean;
  selectedCategory: string;
  onCategoryChange: (v: string) => void;
  identifiedCategory: string | null;
  categoryConfidence: number;
  validCategories: string[];
}) {
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const [activeKeys, setActiveKeys] = useState<string[]>(['clauses']);
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({});
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const hasParsedDoc = !!doc;
  const totalItems = doc ? doc.clauses.length + doc.data_tables.length + doc.exclusions.length + doc.notices.length + doc.health_disclosures.length + doc.rider_clauses.length : 0;

  const toggleItem = (itemKey: string) => {
    setExpandedItems(prev => ({ ...prev, [itemKey]: !prev[itemKey] }));
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onFileUpload(file);
  };

  const renderItemContent = (item: { id: string; title: string; content: string }, categoryKey: string) => {
    const itemKey = `${categoryKey}-${item.id}`;
    const isExpanded = expandedItems[itemKey];
    const hasLongContent = item.content.length > 200;
    const displayContent = isExpanded ? item.content : item.content.slice(0, 200);

    return (
      <div
        style={{
          border: `1px solid ${token.colorBorderSecondary}`,
          borderRadius: 4,
          marginBottom: 8,
          padding: '8px 12px',
          cursor: hasLongContent ? 'pointer' : 'default',
          background: token.colorBgContainer,
        }}
        onClick={hasLongContent ? () => toggleItem(itemKey) : undefined}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Text strong style={{ fontSize: token.fontSize }}>{item.title}</Text>
          {hasLongContent && (
            <span style={{ fontSize: token.fontSizeSM, color: token.colorPrimary }}>
              {isExpanded ? '收起' : '展开'}
            </span>
          )}
        </div>
        <div style={{ whiteSpace: 'pre-wrap', fontSize: token.fontSizeSM, color: token.colorTextSecondary, marginTop: 8 }}>
          {displayContent}
          {hasLongContent && !isExpanded && '…'}
        </div>
      </div>
    );
  };

  const panelItems = doc ? [
    { key: 'clauses', label: `条款 (${doc.clauses.length})`, count: doc.clauses.length,
      items: doc.clauses.map(c => ({ id: c.number, title: `${c.number} ${c.title}`, content: c.text || '' })) },
    { key: 'data_tables', label: `表格 (${doc.data_tables.length})`, count: doc.data_tables.length,
      items: doc.data_tables.map((t, i) => ({ id: `table-${i}`, title: getTableLabel(t, i), content: t.raw_text || '' })) },
    { key: 'exclusions', label: `责任免除 (${doc.exclusions.length})`, count: doc.exclusions.length,
      items: doc.exclusions.map((s, i) => ({ id: `excl-${i}`, title: s.title || `条款 ${i + 1}`, content: s.content || '' })) },
    { key: 'notices', label: `投保须知 (${doc.notices.length})`, count: doc.notices.length,
      items: doc.notices.map((s, i) => ({ id: `notice-${i}`, title: s.title || `须知 ${i + 1}`, content: s.content || '' })) },
    { key: 'health_disclosures', label: `健康告知 (${doc.health_disclosures.length})`, count: doc.health_disclosures.length,
      items: doc.health_disclosures.map((s, i) => ({ id: `health-${i}`, title: s.title || `告知 ${i + 1}`, content: s.content || '' })) },
    { key: 'rider_clauses', label: `附加险条款 (${doc.rider_clauses.length})`, count: doc.rider_clauses.length,
      items: doc.rider_clauses.map(c => ({ id: c.number, title: `${c.number} ${c.title}`, content: c.text || '' })) },
  ].filter(p => p.count > 0) : [];

  const leftContent = hasParsedDoc && file ? (
    <DocumentViewer file={file} fileType={doc!.file_type} />
  ) : hasParsedDoc && !file ? (
    <div style={{ padding: '8px 12px' }}>
      <pre style={{ whiteSpace: 'pre-wrap', fontSize: token.fontSizeSM, lineHeight: 1.6, margin: 0 }}>{doc!.combined_text}</pre>
    </div>
  ) : (
    <TextArea
      style={{ height: '100%', resize: 'none', border: 'none', borderRadius: 0 }}
      placeholder="请输入或粘贴保险条款文档内容…"
      aria-label="保险条款文档内容"
      spellCheck
      value={richText}
      onChange={(e) => onRichTextChange(e.target.value)}
    />
  );

  const rightContent = hasParsedDoc ? (
    <div style={{ flex: 1, overflow: 'auto', padding: '8px 12px' }}>
      {doc!.warnings.length > 0 && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="解析警告" description={
          <ul style={{ margin: 0, paddingLeft: 20 }}>{doc!.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        } />
      )}
      {panelItems.length > 0 ? (
        <Collapse
          activeKey={activeKeys}
          onChange={(keys) => setActiveKeys(keys as string[])}
          expandIcon={({ isActive }) => <CaretRightOutlined rotate={isActive ? 90 : 0} />}
          items={panelItems.map(p => ({
            key: p.key,
            label: p.label,
            children: <div>{p.items.map(item => renderItemContent(item, p.key))}</div>,
          }))}
        />
      ) : (
        <Empty description="未解析到任何内容" />
      )}
    </div>
  ) : (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
      <Empty description="请输入文档内容或点击左侧上传文件" />
    </div>
  );

  const hiddenFileInput = (
    <input
      ref={fileInputRef}
      type="file"
      accept=".pdf,.docx"
      style={{ display: 'none' }}
      onChange={handleFileSelect}
    />
  );

  if (isMobile) {
    return (
      <div style={{ position: 'relative' }}>
        {hiddenFileInput}
        <Tabs
          size="small"
          items={[
            { key: 'input', label: hasParsedDoc ? '原文' : '输入', children: leftContent },
            { key: 'parsed', label: `解析结果 (${totalItems})`, children: rightContent },
          ]}
        />
      </div>
    );
  }

  return (
    <div style={{ position: 'relative' }}>
      {hiddenFileInput}
      <div style={{ display: 'flex', height: 'calc(100vh - 220px)', border: `1px solid ${token.colorBorderSecondary}`, borderRadius: 6 }}>
        {/* 左侧：原文 */}
        <div style={{ width: '40%', borderRight: `1px solid ${token.colorBorderSecondary}`, display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '8px 12px', background: token.colorFillQuaternary, borderBottom: `1px solid ${token.colorBorderSecondary}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
              <Text strong style={{ whiteSpace: 'nowrap' }}>原文</Text>
              {hasParsedDoc && file && (
                <Text type="secondary" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {doc!.file_name}
                </Text>
              )}
            </div>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              size="small"
              onClick={() => fileInputRef.current?.click()}
              loading={loading}
            >
              上传文件
            </Button>
          </div>
          <div style={{ flex: 1, overflow: 'auto' }}>
            {leftContent}
          </div>
        </div>
        {/* 右侧：解析结果 */}
        <div style={{ width: '60%', display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '8px 12px', background: token.colorFillQuaternary, borderBottom: `1px solid ${token.colorBorderSecondary}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
              <Text strong>解析结果</Text>
            </div>
            {hasParsedDoc && (
              <Button type="primary" onClick={onConfirm} loading={loading}>确认并检查</Button>
            )}
          </div>
          {/* 险种选择区域 */}
          {hasParsedDoc && (
            <div style={{ padding: '8px 12px', background: token.colorBgContainer, borderBottom: `1px solid ${token.colorBorderSecondary}` }}>
              <Space>
                <Text strong>险种类型：</Text>
                <Select
                  style={{ width: 160 }}
                  placeholder="选择险种类型"
                  value={selectedCategory || undefined}
                  onChange={onCategoryChange}
                  options={validCategories.map(c => ({ label: c, value: c }))}
                />
                {identifiedCategory && (
                  <Text type="secondary">
                    识别结果：{identifiedCategory} ({Math.round(categoryConfidence * 100)}%)
                  </Text>
                )}
              </Space>
            </div>
          )}
          {rightContent}
        </div>
      </div>
    </div>
  );
}

export default function CompliancePage() {
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const [activeTab, setActiveTab] = useState('document');
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState<ComplianceReport[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [regulationDrawerVisible, setRegulationDrawerVisible] = useState(false);
  const [selectedRegulation, setSelectedRegulation] = useState<AuditRegulationItem | null>(null);

  // 文档审查状态
  const [parsing, setParsing] = useState(false);
  const [richTextContent, setRichTextContent] = useState('');
  const [parsedDocument, setParsedDocument] = useState<ParsedDocument | null>(null);
  const [productName, setProductName] = useState('');
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);

  useUnsavedChanges(uploadedFile !== null);
  const [checkingResult, setCheckingResult] = useState<ComplianceReport | null>(null);

  const [identifiedCategory, setIdentifiedCategory] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [categoryConfidence, setCategoryConfidence] = useState<number>(0);
  const [validCategories, setValidCategories] = useState<string[]>([]);

  useEffect(() => {
    loadHistory();
    loadCategories();
  }, []);

  const loadCategories = async () => {
    try {
      setValidCategories(await complianceApi.fetchCategories());
    } catch {
      // 降级为空列表
    }
  };

  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const data = await complianceApi.fetchComplianceReports();
      setHistory(data);
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleFileUpload = async (file: File) => {
    setParsing(true);
    setUploadedFile(file);
    try {
      const result = await complianceApi.parseFile(file);
      setParsedDocument(result);
      setProductName(result.file_name);
      setCheckingResult(null);
      setIdentifiedCategory(result.identified_category);
      setCategoryConfidence(result.category_confidence);
      setSelectedCategory(result.identified_category || '');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`解析失败: ${msg}`);
    } finally {
      setParsing(false);
    }
  };

  // 富文本解析：当文本变化时实时解析
  useEffect(() => {
    if (uploadedFile || !richTextContent.trim()) return;
    const timer = setTimeout(async () => {
      setParsing(true);
      try {
        const result = await complianceApi.parseRichText(richTextContent);
        setParsedDocument(result);
        setProductName('');
        setCheckingResult(null);
        setIdentifiedCategory(result.identified_category);
        setCategoryConfidence(result.category_confidence);
        setSelectedCategory(result.identified_category || '');
      } catch {
        // 静默失败，不显示错误
      } finally {
        setParsing(false);
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [richTextContent, uploadedFile]);

  const handleConfirmReview = async () => {
    if (!parsedDocument) return;
    setLoading(true);
    try {
      const report = await complianceApi.checkDocument({
        document_content: parsedDocument.combined_text,
        product_name: productName || parsedDocument.file_name || undefined,
        category: selectedCategory || undefined,
      });
      setCheckingResult(report);
      message.success('合规检查完成');
      loadHistory();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`检查失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  const buildItemColumns = (regulationMap: Record<string, AuditRegulationItem>) => [
    {
      title: '检查项', dataIndex: 'param', key: 'param', width: 120,
      render: (_: string, record: AuditResultItem) => {
        const cfg = STATUS_CONFIG[record.status] || STATUS_CONFIG.attention;
        return <Tag color={cfg.color} icon={cfg.icon}>{record.param}</Tag>;
      },
    },
    {
      title: '产品条款', dataIndex: 'value', key: 'value', width: '25%',
      render: (_: string, record: AuditResultItem) => (
        <span>{record.clause_number} {record.value}</span>
      ),
    },
    {
      title: '法规要求', key: 'requirement', width: '40%',
      render: (_: unknown, record: AuditResultItem) => {
        const text = record.requirement || '';
        const refMatch = text.match(/^《[^》]+》[^：:]*[：:]\s*/);
        const stripped = refMatch ? text.slice(refMatch[0].length) : text;
        const reg = record.chunk_id ? regulationMap[record.chunk_id] : undefined;
        if (reg) {
          const lawShort = reg.law_name?.replace(/[《》]/g, '');
          const label = [lawShort, reg.article_number].filter(Boolean).join(' ');
          return (
            <span>
              {stripped}
              <a onClick={() => handleRegulationClick(record.chunk_id!)} style={{ cursor: 'pointer', marginLeft: 4, fontSize: token.fontSizeSM }}>{label}</a>
            </span>
          );
        }
        if (record.source_excerpt) {
          return (
            <span>
              {stripped}
              <Text type="secondary" style={{ fontSize: token.fontSizeSM, marginLeft: 4 }}>（来源：{record.source_excerpt.slice(0, 60)}…）</Text>
            </span>
          );
        }
        return <span>{text}</span>;
      },
    },
    {
      title: '建议', dataIndex: 'suggestion', key: 'suggestion', width: '25%',
    },
  ];

  const handleViewReport = async (reportId: string) => {
    try {
      const report = await complianceApi.fetchComplianceReport(reportId);
      setCheckingResult(report);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`加载报告失败: ${msg}`);
    }
  };

  const handleDeleteReport = async (reportId: string) => {
    try {
      await complianceApi.deleteComplianceReport(reportId);
      message.success('删除成功');
      loadHistory();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`删除失败: ${msg}`);
    }
  };

  const handleRegulationClick = (chunkId: string) => {
    const regulations = checkingResult?.result?.regulations;
    if (!regulations) return;
    const regulationMap = Object.fromEntries(regulations.map(r => [r.chunk_id, r]));
    const regulation = regulationMap[chunkId];
    if (regulation) {
      setSelectedRegulation(regulation);
      setRegulationDrawerVisible(true);
    }
  };

  const SOURCE_TYPE_LABEL: Record<string, { label: string; color: string }> = {
    category: { label: '险种专属', color: 'blue' },
    general: { label: '通用法规', color: 'default' },
    negative_list: { label: '负面清单', color: 'red' },
  };

  const renderConclusionSection = (docResult: ComplianceResult) => {
    const s = docResult.summary;
    const hasViolation = (s.non_compliant || 0) > 0;
    const negResult = docResult.negative_list_result;
    return (
      <div>
        <div style={{ marginBottom: 8 }}>
          {hasViolation
            ? <Tag color="error" icon={<CloseCircleOutlined />} style={{ fontSize: 16, padding: '4px 16px' }}>审核未通过</Tag>
            : <Tag color="success" icon={<CheckCircleOutlined />} style={{ fontSize: 16, padding: '4px 16px' }}>审核通过</Tag>
          }
        </div>
        <Space size={isMobile ? 'small' : 'middle'} wrap>
          <Tag color="success" icon={<CheckCircleOutlined />}>合规 {s.compliant || 0}</Tag>
          <Tag color="error" icon={<CloseCircleOutlined />}>不合规 {s.non_compliant || 0}</Tag>
          <Tag color="warning" icon={<ExclamationCircleOutlined />}>需关注 {s.attention || 0}</Tag>
          {negResult && (
            <Tag color={negResult === 'violated' ? 'error' : 'success'}
              icon={negResult === 'violated' ? <CloseCircleOutlined /> : <CheckCircleOutlined />}>
              负面清单{negResult === 'violated' ? '违规' : '通过'}
            </Tag>
          )}
        </Space>
      </div>
    );
  };

  const renderRegulationSourcesSection = (regulations: AuditRegulationItem[]) => {
    const groups: Record<string, AuditRegulationItem[]> = {};
    for (const r of regulations) {
      const key = r.source_type || 'general';
      (groups[key] ??= []).push(r);
    }
    const ordered = ['category', 'general', 'negative_list'].filter(k => groups[k]?.length);
    const tabItems = ordered.map(type => {
      const cfg = SOURCE_TYPE_LABEL[type] ?? { label: type, color: 'default' };
      const items = groups[type];
      const lawNames = [...new Set(items.map(r => r.law_name))];
      const collapseItems = lawNames.map(name => {
        const articles = items.filter(r => r.law_name === name);
        return {
          key: name,
          label: <span>{name}（{articles.length} 条）</span>,
          children: (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {articles.map(a => (
                <Tag key={a.chunk_id} style={{ cursor: 'pointer' }} onClick={() => handleRegulationClick(a.chunk_id)}>
                  {a.article_number}
                </Tag>
              ))}
            </div>
          ),
        };
      });
      return {
        key: type,
        label: <span><Tag color={cfg.color}>{cfg.label}</Tag> {items.length} 条</span>,
        children: <Collapse size="small" items={collapseItems} />,
      };
    });
    return <Tabs size="small" items={tabItems} />;
  };

  const renderReportDetail = () => {
    if (!checkingResult?.result?.summary) return null;
    const docResult = checkingResult.result;
    const regulationMap: Record<string, AuditRegulationItem> = {};
    for (const r of (docResult.regulations || [])) {
      regulationMap[r.chunk_id] = r;
    }
    const totalItems = (docResult.items || []).length;
    return (
      <>
        <Card type="inner" title="审核结论" size="small" style={{ marginBottom: 16 }}>
          {renderConclusionSection(docResult)}
          {docResult.missing_clauses && docResult.missing_clauses.length > 0 && (
            <Alert type="warning" showIcon style={{ marginTop: 12 }} message="遗漏条款提示" description={
              <span>以下条款未被检查覆盖：{docResult.missing_clauses.map(c => <Tag key={c} style={{ marginLeft: 4 }}>{c}</Tag>)}</span>
            } />
          )}
          {docResult.warning && (
            <Alert type="warning" showIcon style={{ marginTop: 8 }} message={docResult.warning} />
          )}
        </Card>

        {docResult.regulations && docResult.regulations.length > 0 && (
          <Card type="inner" title={`法规依据（${docResult.regulations.length} 条）`} size="small" style={{ marginBottom: 16 }}>
            {renderRegulationSourcesSection(docResult.regulations)}
          </Card>
        )}

        {totalItems > 0 && (
          <Card type="inner" title={`产品条款（共 ${totalItems} 项）`} size="small">
            <Table
              dataSource={docResult.items}
              columns={buildItemColumns(regulationMap)}
              rowKey={(r: AuditResultItem) => `${r.clause_number}-${r.param}`}
              size="small"
              pagination={false}
              rowClassName={(record: AuditResultItem) => record.status === 'non_compliant' ? 'ant-table-row-error' : ''}
            />
          </Card>
        )}
      </>
    );
  };

  return (
    <div>
      <Title level={4} className="mb-16">合规检查助手</Title>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'document',
            label: <span><FileTextOutlined /> 条款文档审查</span>,
            children: (
              <div aria-live="polite">
                <DocumentReviewPanel
                  document={parsedDocument}
                  file={uploadedFile}
                  richText={richTextContent}
                  onRichTextChange={setRichTextContent}
                  onFileUpload={handleFileUpload}
                  onConfirm={handleConfirmReview}
                  loading={loading || parsing}
                  selectedCategory={selectedCategory}
                  onCategoryChange={setSelectedCategory}
                  identifiedCategory={identifiedCategory}
                  categoryConfidence={categoryConfidence}
                  validCategories={validCategories}
                />
              </div>
            ),
          },
          {
            key: 'history',
            label: <span><HistoryOutlined /> 检查历史</span>,
            children: (
              <div>
                <div style={{ marginBottom: 12 }}>
                  <Text strong style={{ fontSize: token.fontSizeHeading5 }}>审核列表</Text>
                </div>
                <Table
                  dataSource={history}
                  loading={historyLoading}
                  rowKey="id"
                  size="small"
                  pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: ['10', '20', '50', '100'], showTotal: (total) => `共 ${total} 条` }}
                  onRow={(record: ComplianceReport) => ({
                    onClick: () => handleViewReport(record.id),
                    style: { cursor: 'pointer' },
                  })}
                  columns={[
                    { title: 'ID', dataIndex: 'id', key: 'id', width: 100, ellipsis: true },
                    { title: '产品名称', dataIndex: 'product_name', key: 'product_name', ellipsis: true },
                    { title: '险种类型', dataIndex: 'category', key: 'category', width: 90 },
                    { title: '审核时间', dataIndex: 'created_at', key: 'created_at', width: 160 },
                    {
                      title: '操作', key: 'action', width: 140,
                      render: (_: unknown, record: ComplianceReport) => (
                        <Space size="small">
                          <Button type="link" size="small" icon={<EyeOutlined />}
                            onClick={(e) => { e.stopPropagation(); handleViewReport(record.id); }}>查看</Button>
                          <Popconfirm title="确定删除？此操作不可恢复。" onConfirm={(e) => { e?.stopPropagation(); handleDeleteReport(record.id); }}>
                            <Button type="link" danger size="small" icon={<DeleteOutlined />}
                              onClick={(e) => e.stopPropagation()}>删除</Button>
                          </Popconfirm>
                        </Space>
                      ),
                    },
                  ]}
                />
                {checkingResult && (
                  <Card
                    style={{ marginTop: 24, borderTop: `2px solid ${token.colorPrimary}` }}
                    title={<span style={{ fontSize: token.fontSizeHeading5 }}>审核详情 — {checkingResult.product_name || ''}</span>}
                    extra={<Button type="text" icon={<CloseOutlined />} onClick={() => setCheckingResult(null)}>关闭</Button>}
                  >
                    {renderReportDetail()}
                  </Card>
                )}
              </div>
            ),
          },
        ]}
      />

      <RegulationDrawer
        visible={regulationDrawerVisible}
        regulation={selectedRegulation}
        onClose={() => setRegulationDrawerVisible(false)}
        isMobile={isMobile}
      />
    </div>
  );
}
