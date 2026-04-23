import React, { useState, useEffect, useMemo } from 'react';
import {
  Card, Form, Input, Button, Table, Tag, Typography, theme,
  message, Tabs, Space, Descriptions, Popconfirm, Drawer, Grid,
  Collapse, Empty, Divider, Alert,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined,
  HistoryOutlined, DeleteOutlined, BookOutlined,
  FileTextOutlined, CaretRightOutlined, PlusOutlined,
} from '@ant-design/icons';
import * as complianceApi from '../api/compliance';
import type { ComplianceReport, ComplianceItem, Source, ParsedDocument } from '../types';
import { DRAWER_MD } from '../constants/layout';
import { DocumentViewer } from '../components/DocumentViewer';

const { Title, Text } = Typography;
const { TextArea } = Input;

const STATUS_CONFIG: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  compliant: { color: 'success', icon: <CheckCircleOutlined />, label: '合规' },
  non_compliant: { color: 'error', icon: <CloseCircleOutlined />, label: '不合规' },
  attention: { color: 'warning', icon: <ExclamationCircleOutlined />, label: '需关注' },
};

function SourceDrawer({
  visible,
  source,
  excerpt,
  onClose,
  isMobile,
}: {
  visible: boolean;
  source: Source | undefined;
  excerpt?: string;
  onClose: () => void;
  isMobile: boolean;
}) {
  const { token } = theme.useToken();

  if (!source) return null;

  return (
    <Drawer
      title={<Space><BookOutlined />法规来源详情</Space>}
      placement="right"
      size={isMobile ? '100%' : DRAWER_MD}
      open={visible}
      onClose={onClose}
    >
      <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
        <Descriptions.Item label="法规名称">{source.law_name}</Descriptions.Item>
        <Descriptions.Item label="条款编号">{source.article_number}</Descriptions.Item>
        {source.doc_number && (
          <Descriptions.Item label="文号">{source.doc_number}</Descriptions.Item>
        )}
        {source.issuing_authority && (
          <Descriptions.Item label="发布机关">{source.issuing_authority}</Descriptions.Item>
        )}
        {source.effective_date && (
          <Descriptions.Item label="生效日期">{source.effective_date}</Descriptions.Item>
        )}
        <Descriptions.Item label="分类">{source.category}</Descriptions.Item>
        {source.hierarchy_path && (
          <Descriptions.Item label="层级路径">{source.hierarchy_path}</Descriptions.Item>
        )}
        {source.score != null && (
          <Descriptions.Item label="检索相关度">
            <Tag color={source.score > 0.02 ? 'green' : source.score > 0.01 ? 'orange' : 'red'}>
              {source.score.toFixed(4)}
            </Tag>
          </Descriptions.Item>
        )}
      </Descriptions>

      {excerpt && (
        <div style={{ marginBottom: 16 }}>
          <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
            引用原文片段
          </Typography.Text>
          <div
            style={{
              background: token.colorPrimaryBg,
              border: `1px solid ${token.colorPrimaryBorder}`,
              borderRadius: 4,
              padding: '8px 12px',
              color: token.colorPrimaryText,
              fontSize: token.fontSize ?? 14,
            }}
          >
            {excerpt}
          </div>
        </div>
      )}

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
          {source.content}
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
}: {
  document: ParsedDocument | null;
  file: File | null;
  richText: string;
  onRichTextChange: (v: string) => void;
  onFileUpload: (file: File) => void;
  onConfirm: () => void;
  loading: boolean;
}) {
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const [activeKeys, setActiveKeys] = useState<string[]>(['clauses']);
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({});
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const hasParsedDoc = !!doc;
  const totalItems = doc ? doc.clauses.length + doc.premium_tables.length + doc.exclusions.length + doc.notices.length + doc.health_disclosures.length + doc.rider_clauses.length : 0;

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
          {hasLongContent && !isExpanded && '...'}
        </div>
      </div>
    );
  };

  const panelItems = doc ? [
    { key: 'clauses', label: `条款 (${doc.clauses.length})`, count: doc.clauses.length,
      items: doc.clauses.map(c => ({ id: c.number, title: `${c.number} ${c.title}`, content: c.text || '' })) },
    { key: 'premium_tables', label: `费率表 (${doc.premium_tables.length})`, count: doc.premium_tables.length,
      items: doc.premium_tables.map((t, i) => ({ id: `table-${i}`, title: `费率表 ${i + 1}`, content: t.raw_text || '' })) },
    { key: 'exclusions', label: `责任免除 (${doc.exclusions.length})`, count: doc.exclusions.length,
      items: doc.exclusions.map((s, i) => ({ id: `excl-${i}`, title: s.title || `条款 ${i + 1}`, content: s.content || '' })) },
    { key: 'notices', label: `投保须知 (${doc.notices.length})`, count: doc.notices.length,
      items: doc.notices.map((s, i) => ({ id: `notice-${i}`, title: s.title || `须知 ${i + 1}`, content: s.content || '' })) },
    { key: 'health_disclosures', label: `健康告知 (${doc.health_disclosures.length})`, count: doc.health_disclosures.length,
      items: doc.health_disclosures.map((s, i) => ({ id: `health-${i}`, title: s.title || `告知 ${i + 1}`, content: s.content || '' })) },
    { key: 'rider_clauses', label: `附加险条款 (${doc.rider_clauses.length})`, count: doc.rider_clauses.length,
      items: doc.rider_clauses.map(c => ({ id: c.number, title: `${c.number} ${c.title}`, content: c.text || '' })) },
  ].filter(p => p.count > 0) : [];

  // 左侧内容：有文档时显示 DocumentViewer，无文档时显示可编辑文本区
  const leftContent = hasParsedDoc && file ? (
    <DocumentViewer file={file} fileType={doc!.file_type} />
  ) : hasParsedDoc && !file ? (
    <div style={{ padding: '8px 12px' }}>
      <pre style={{ whiteSpace: 'pre-wrap', fontSize: token.fontSizeSM, lineHeight: 1.6, margin: 0 }}>{doc!.combined_text}</pre>
    </div>
  ) : (
    <TextArea
      style={{ height: '100%', resize: 'none', border: 'none', borderRadius: 0 }}
      placeholder="请输入或粘贴保险条款文档内容..."
      value={richText}
      onChange={(e) => onRichTextChange(e.target.value)}
    />
  );

  // 右侧内容：解析结果
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

  // 隐藏的文件输入
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
              {hasParsedDoc && (
                <Text type="secondary">
                  {[
                    doc!.clauses.length > 0 ? `${doc!.clauses.length} 条条款` : null,
                    doc!.premium_tables.length > 0 ? `${doc!.premium_tables.length} 个费率表` : null,
                  ].filter(Boolean).join('，')}
                </Text>
              )}
            </div>
            {hasParsedDoc && (
              <Button type="primary" onClick={onConfirm} loading={loading}>确认并检查</Button>
            )}
          </div>
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
  const [activeTab, setActiveTab] = useState('product');
  const [productForm] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [currentReport, setCurrentReport] = useState<ComplianceReport | null>(null);
  const [history, setHistory] = useState<ComplianceReport[]>([]);
  const reportRef = React.useRef<HTMLDivElement>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [sourceDrawerVisible, setSourceDrawerVisible] = useState(false);
  const [selectedSource, setSelectedSource] = useState<Source | undefined>();
  const [selectedExcerpt, setSelectedExcerpt] = useState<string | undefined>();

  // 文档审查状态
  const [parsing, setParsing] = useState(false);
  const [richTextContent, setRichTextContent] = useState('');
  const [parsedDocument, setParsedDocument] = useState<ParsedDocument | null>(null);
  const [productName, setProductName] = useState('');
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [checkingResult, setCheckingResult] = useState<ComplianceReport | null>(null);

  useEffect(() => {
    loadHistory();
  }, []);

  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const data = await complianceApi.fetchComplianceReports();
      setHistory(data);
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleProductCheck = async () => {
    try {
      const values = await productForm.validateFields();
      setLoading(true);
      const report = await complianceApi.checkProduct({
        product_name: values.product_name,
        category: values.category,
        params: parseParams(values.params_text),
      });
      setCurrentReport(report);
      message.success('检查完成');
      loadHistory();
    } catch (err) {
      message.error(`检查失败: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  const parseParams = (text: string): Record<string, string> => {
    const params: Record<string, string> = {};
    text.split('\n').forEach((line) => {
      const idx = line.indexOf(':');
      if (idx > 0) {
        params[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
      }
    });
    return params;
  };

  const handleFileUpload = async (file: File) => {
    setParsing(true);
    setUploadedFile(file);
    try {
      const result = await complianceApi.parseFile(file);
      setParsedDocument(result);
      setProductName(result.file_name);
      setCheckingResult(null);
    } catch (err) {
      message.error(`解析失败: ${err}`);
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
      } catch (err) {
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
        parse_id: parsedDocument.parse_id,
      });
      setCheckingResult(report);
      message.success('合规检查完成');
      loadHistory();
    } catch (err) {
      message.error(`检查失败: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  const handleResetDocumentReview = () => {
    setParsedDocument(null);
    setRichTextContent('');
    setProductName('');
    setUploadedFile(null);
    setCheckingResult(null);
  };

  const itemColumns = [
    {
      title: '检查项', dataIndex: 'param', key: 'param', width: 120,
    },
    {
      title: '产品值', dataIndex: 'value', key: 'value', width: 120,
    },
    {
      title: '法规要求', dataIndex: 'requirement', key: 'requirement', ellipsis: true,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (s: string) => {
        const cfg = STATUS_CONFIG[s] || STATUS_CONFIG.attention;
        return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>;
      },
    },
    {
      title: '法规来源', dataIndex: 'source', key: 'source', width: 150,
      render: (text: string, record: ComplianceItem) => {
        if (!text) return '-';
        const tags = [...text.matchAll(/\[来源(\d+)\]/g)];
        if (tags.length === 0) return text;
        return (
          <Space size={4} wrap>
            {tags.map(([tag, numStr]) => {
              const idx = parseInt(numStr, 10) - 1;
              return (
                <Tag
                  key={tag}
                  color="blue"
                  style={{ cursor: 'pointer' }}
                  onClick={() => handleSourceClick(idx, record.source_excerpt)}
                >
                  {tag}
                </Tag>
              );
            })}
          </Space>
        );
      },
    },
    {
      title: '建议', dataIndex: 'suggestion', key: 'suggestion', ellipsis: true, width: 200,
    },
  ];

  const groupedByClause = useMemo(() => {
    const items = checkingResult?.result?.items || [];
    if (items.length === 0) return {};
    const groups: Record<string, ComplianceItem[]> = {};
    for (const item of items) {
      const clauseNum = item.clause_number || '其他';
      if (!groups[clauseNum]) groups[clauseNum] = [];
      groups[clauseNum].push(item);
    }
    const sortedKeys = Object.keys(groups).sort((a, b) => {
      const aParts = a.split('.').map(Number);
      const bParts = b.split('.').map(Number);
      for (let i = 0; i < Math.max(aParts.length, bParts.length); i++) {
        const aVal = aParts[i] || 0;
        const bVal = bParts[i] || 0;
        if (aVal !== bVal) return aVal - bVal;
      }
      return 0;
    });
    const sorted: Record<string, ComplianceItem[]> = {};
    for (const key of sortedKeys) {
      sorted[key] = groups[key];
    }
    return sorted;
  }, [checkingResult?.result?.items]);

  const getClauseSummary = (items: ComplianceItem[]) => {
    const compliant = items.filter(i => i.status === 'compliant').length;
    const nonCompliant = items.filter(i => i.status === 'non_compliant').length;
    const attention = items.filter(i => i.status === 'attention').length;
    return { compliant, nonCompliant, attention };
  };

  const handleDeleteReport = async (reportId: string) => {
    try {
      await complianceApi.deleteComplianceReport(reportId);
      message.success('删除成功');
      if (currentReport?.id === reportId) setCurrentReport(null);
      loadHistory();
    } catch (err) {
      message.error(`删除失败: ${err}`);
    }
  };

  const handleSelectReport = (record: ComplianceReport) => {
    setCurrentReport(record);
    setActiveTab('history');
    setTimeout(() => reportRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100);
  };

  const handleSourceClick = (sourceIdx: number, excerpt?: string) => {
    const sources = result?.sources;
    if (sources && sourceIdx < sources.length) {
      setSelectedSource(sources[sourceIdx]);
      setSelectedExcerpt(excerpt);
      setSourceDrawerVisible(true);
    }
  };

  const result = currentReport?.result;
  const summary = result?.summary;

  const renderDocumentReviewTab = () => {
    return (
      <div>
        <DocumentReviewPanel
          document={parsedDocument}
          file={uploadedFile}
          richText={richTextContent}
          onRichTextChange={setRichTextContent}
          onFileUpload={handleFileUpload}
          onConfirm={handleConfirmReview}
          loading={loading || parsing}
        />
        {checkingResult && (() => {
          const docResult = checkingResult.result;
          const docSummary = docResult?.summary;
          return docResult && docSummary ? (
            <Card title={`检查报告 - ${checkingResult.product_name || ''}`} style={{ marginTop: 16 }}>
              <Descriptions size="small" column={isMobile ? 1 : 2} style={{ marginBottom: 16 }}>
                <Descriptions.Item label="模式">
                  {checkingResult.mode === 'product' ? '产品参数检查' : '条款文档审查'}
                </Descriptions.Item>
                <Descriptions.Item label="检查时间">{checkingResult.created_at}</Descriptions.Item>
              </Descriptions>
              <Space size={isMobile ? 'small' : 'large'} wrap style={{ marginBottom: 16 }}>
                <Tag color="success" icon={<CheckCircleOutlined />} style={{ fontSize: token.fontSize ?? 14, padding: '4px 12px' }}>
                  合规 {docSummary.compliant} 项
                </Tag>
                <Tag color="error" icon={<CloseCircleOutlined />} style={{ fontSize: token.fontSize ?? 14, padding: '4px 12px' }}>
                  不合规 {docSummary.non_compliant} 项
                </Tag>
                <Tag color="warning" icon={<ExclamationCircleOutlined />} style={{ fontSize: token.fontSize ?? 14, padding: '4px 12px' }}>
                  需关注 {docSummary.attention} 项
                </Tag>
              </Space>
              {docResult.missing_clauses && docResult.missing_clauses.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 16 }}
                  message="遗漏条款提示"
                  description={
                    <span>
                      以下条款未被检查覆盖：
                      {docResult.missing_clauses.map(c => <Tag key={c} style={{ marginLeft: 4 }}>{c}</Tag>)}
                    </span>
                  }
                />
              )}
              {docResult.warning && (
                <Alert type="warning" showIcon style={{ marginBottom: 16 }} message={docResult.warning} />
              )}
              {Object.keys(groupedByClause).length > 0 ? (
                <Collapse
                  defaultActiveKey={Object.keys(groupedByClause)}
                  items={Object.entries(groupedByClause).map(([clauseNum, items]) => {
                    const clauseSummary = getClauseSummary(items);
                    return {
                      key: clauseNum,
                      label: (
                        <Space>
                          <Text strong>条款 {clauseNum}</Text>
                          <Text type="secondary">({items.length} 项)</Text>
                          {clauseSummary.nonCompliant > 0 && (
                            <Tag color="error">{clauseSummary.nonCompliant} 不合规</Tag>
                          )}
                          {clauseSummary.attention > 0 && (
                            <Tag color="warning">{clauseSummary.attention} 需关注</Tag>
                          )}
                          {clauseSummary.nonCompliant === 0 && clauseSummary.attention === 0 && (
                            <Tag color="success">全部合规</Tag>
                          )}
                        </Space>
                      ),
                      children: (
                        <Table
                          dataSource={items}
                          columns={itemColumns}
                          rowKey={(r: ComplianceItem) => `${r.clause_number}-${r.param}`}
                          size="small"
                          pagination={false}
                        />
                      ),
                    };
                  })}
                />
              ) : (
                <Table
                  dataSource={docResult.items || []}
                  columns={itemColumns}
                  rowKey={(r: ComplianceItem) => r.param}
                  size="small"
                  scroll={{ x: 'max-content' }}
                  pagination={false}
                  rowClassName={(record: ComplianceItem) => record.status === 'non_compliant' ? 'ant-table-row-error' : ''}
                />
              )}
            </Card>
          ) : null;
        })()}
      </div>
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
            key: 'product',
            label: '产品参数检查',
            children: (
              <Card title="输入产品参数" size="small" style={{ marginBottom: 16 }}>
                <Form form={productForm} layout="vertical">
                  <Form.Item name="product_name" label="产品名称" rules={[{ required: true }]}>
                    <Input placeholder="如：XX健康保险" />
                  </Form.Item>
                  <Form.Item name="category" label="险种类型" rules={[{ required: true }]}>
                    <Input placeholder="如：健康险、寿险、财产险" />
                  </Form.Item>
                  <Form.Item name="params_text" label="产品参数" rules={[{ required: true }]}
                    extra="每行一个参数，格式：参数名: 值，如：等待期: 90天">
                    <TextArea rows={6} placeholder={`等待期: 90天\n免赔额: 0元\n保险期间: 1年\n缴费方式: 年缴`} />
                  </Form.Item>
                  <Button type="primary" onClick={handleProductCheck} loading={loading}>
                    开始检查
                  </Button>
                </Form>
              </Card>
            ),
          },
          {
            key: 'document',
            label: <span><FileTextOutlined /> 条款文档审查</span>,
            children: renderDocumentReviewTab(),
          },
          {
            key: 'history',
            label: <span><HistoryOutlined /> 检查历史</span>,
            children: (
              <Table
                dataSource={history}
                loading={historyLoading}
                rowKey="id"
                size="small"
                pagination={{ pageSize: 20 }}
                scroll={{ x: 'max-content' }}
                onRow={(record) => ({
                  onClick: () => handleSelectReport(record),
                  style: { cursor: 'pointer' },
                })}
                columns={[
                  { title: '产品名称', dataIndex: 'product_name', key: 'product_name' },
                  { title: '险种', dataIndex: 'category', key: 'category' },
                  {
                    title: '模式', dataIndex: 'mode', key: 'mode', width: 100,
                    render: (m: string) => m === 'product' ? '参数检查' : '文档审查',
                  },
                  { title: '检查时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
                  {
                    title: '操作', key: 'action', width: 80,
                    render: (_: unknown, record: ComplianceReport) => (
                      <Popconfirm title="确定删除该检查记录？" onConfirm={(e) => { e?.stopPropagation(); handleDeleteReport(record.id); }}>
                        <Button type="text" danger size="small" icon={<DeleteOutlined />}
                          onClick={(e) => e.stopPropagation()} />
                      </Popconfirm>
                    ),
                  },
                ]}
              />
            ),
          },
        ]}
      />

      {activeTab === 'product' && result && summary && (
        <div ref={reportRef}>
        <Card title={`检查报告 - ${currentReport?.product_name || ''}`} className="mt-16">
          <Descriptions size="small" column={isMobile ? 1 : 2} style={{ marginBottom: 16 }}>
            <Descriptions.Item label="模式">
              {currentReport?.mode === 'product' ? '产品参数检查' : '条款文档审查'}
            </Descriptions.Item>
            <Descriptions.Item label="检查时间">{currentReport?.created_at}</Descriptions.Item>
          </Descriptions>

          <Space size={isMobile ? 'small' : 'large'} wrap style={{ marginBottom: 16 }}>
            <Tag color="success" icon={<CheckCircleOutlined />} style={{ fontSize: token.fontSize ?? 14, padding: '4px 12px' }}>
              合规 {summary.compliant} 项
            </Tag>
            <Tag color="error" icon={<CloseCircleOutlined />} style={{ fontSize: token.fontSize ?? 14, padding: '4px 12px' }}>
              不合规 {summary.non_compliant} 项
            </Tag>
            <Tag color="warning" icon={<ExclamationCircleOutlined />} style={{ fontSize: token.fontSize ?? 14, padding: '4px 12px' }}>
              需关注 {summary.attention} 项
            </Tag>
          </Space>

          <Table
            dataSource={result.items || []}
            columns={itemColumns}
            rowKey={(r: ComplianceItem) => r.param}
            size="small"
            scroll={{ x: 'max-content' }}
            pagination={false}
            rowClassName={(record: ComplianceItem) => {
              if (record.status === 'non_compliant') return 'ant-table-row-error';
              return '';
            }}
          />
        </Card>
        </div>
      )}

      <SourceDrawer
        visible={sourceDrawerVisible}
        source={selectedSource}
        excerpt={selectedExcerpt}
        onClose={() => setSourceDrawerVisible(false)}
        isMobile={isMobile}
      />
    </div>
  );
}
