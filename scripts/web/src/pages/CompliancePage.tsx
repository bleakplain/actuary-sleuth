import React, { useState, useEffect } from 'react';
import {
  Card, Form, Input, Button, Table, Tag, Typography, theme,
  message, Tabs, Space, Descriptions, Popconfirm, Drawer,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined,
  HistoryOutlined, DeleteOutlined, BookOutlined,
} from '@ant-design/icons';
import * as complianceApi from '../api/compliance';
import type { ComplianceReport, ComplianceItem, Source } from '../types';
import { DRAWER_MD } from '../constants/layout';

const { Title } = Typography;
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
}: {
  visible: boolean;
  source: Source | undefined;
  excerpt?: string;
  onClose: () => void;
}) {
  const { token } = theme.useToken();

  if (!source) return null;

  return (
    <Drawer
      title={<Space><BookOutlined />法规来源详情</Space>}
      placement="right"
      width={DRAWER_MD}
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
              fontSize: token.fontSize,
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
            fontSize: token.fontSize,
          }}
        >
          {source.content}
        </div>
      </div>
    </Drawer>
  );
}

export default function CompliancePage() {
  const [activeTab, setActiveTab] = useState('product');
  const [productForm] = Form.useForm();
  const [docForm] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [currentReport, setCurrentReport] = useState<ComplianceReport | null>(null);
  const [history, setHistory] = useState<ComplianceReport[]>([]);
  const reportRef = React.useRef<HTMLDivElement>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [sourceDrawerVisible, setSourceDrawerVisible] = useState(false);
  const [selectedSource, setSelectedSource] = useState<Source | undefined>();
  const [selectedExcerpt, setSelectedExcerpt] = useState<string | undefined>();

  useEffect(() => {
    loadHistory();
  }, []);

  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const data = await complianceApi.fetchComplianceReports();
      setHistory(data);
    } catch {
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

  const handleDocumentCheck = async () => {
    try {
      const values = await docForm.validateFields();
      setLoading(true);
      const report = await complianceApi.checkDocument({
        document_content: values.document_content,
        product_name: values.product_name || undefined,
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
            label: '条款文档审查',
            children: (
              <Card title="上传条款文档" size="small" style={{ marginBottom: 16 }}>
                <Form form={docForm} layout="vertical">
                  <Form.Item name="product_name" label="产品名称（可选）">
                    <Input placeholder="如：XX健康保险" />
                  </Form.Item>
                  <Form.Item name="document_content" label="条款内容" rules={[{ required: true }]}>
                    <TextArea rows={10} placeholder="粘贴保险条款文档内容..." />
                  </Form.Item>
                  <Button type="primary" onClick={handleDocumentCheck} loading={loading}>
                    开始审查
                  </Button>
                </Form>
              </Card>
            ),
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

      {result && summary && (
        <div ref={reportRef}>
        <Card title={`检查报告 - ${currentReport?.product_name || ''}`} className="mt-16">
          <Descriptions size="small" style={{ marginBottom: 16 }}>
            <Descriptions.Item label="模式">
              {currentReport?.mode === 'product' ? '产品参数检查' : '条款文档审查'}
            </Descriptions.Item>
            <Descriptions.Item label="检查时间">{currentReport?.created_at}</Descriptions.Item>
          </Descriptions>

          <Space size="large" style={{ marginBottom: 16 }}>
            <Tag color="success" icon={<CheckCircleOutlined />} style={{ fontSize: token.fontSize, padding: '4px 12px' }}>
              合规 {summary.compliant} 项
            </Tag>
            <Tag color="error" icon={<CloseCircleOutlined />} style={{ fontSize: token.fontSize, padding: '4px 12px' }}>
              不合规 {summary.non_compliant} 项
            </Tag>
            <Tag color="warning" icon={<ExclamationCircleOutlined />} style={{ fontSize: token.fontSize, padding: '4px 12px' }}>
              需关注 {summary.attention} 项
            </Tag>
          </Space>

          <Table
            dataSource={result.items || []}
            columns={itemColumns}
            rowKey={(r: ComplianceItem) => r.param}
            size="small"
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
      />
    </div>
  );
}
