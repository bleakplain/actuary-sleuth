import React, { useState, useEffect } from 'react';
import {
  Card, Form, Input, Button, Table, Tag, Typography,
  message, Tabs, Space, Descriptions, Popconfirm,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined,
  HistoryOutlined, DeleteOutlined,
} from '@ant-design/icons';
import * as complianceApi from '../api/compliance';
import type { ComplianceReport, ComplianceItem } from '../types';

const { Title } = Typography;
const { TextArea } = Input;

const STATUS_CONFIG: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  compliant: { color: 'success', icon: <CheckCircleOutlined />, label: '合规' },
  non_compliant: { color: 'error', icon: <CloseCircleOutlined />, label: '不合规' },
  attention: { color: 'warning', icon: <ExclamationCircleOutlined />, label: '需关注' },
};

export default function CompliancePage() {
  const [activeTab, setActiveTab] = useState('product');
  const [productForm] = Form.useForm();
  const [docForm] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [currentReport, setCurrentReport] = useState<ComplianceReport | null>(null);
  const [history, setHistory] = useState<ComplianceReport[]>([]);
  const reportRef = React.useRef<HTMLDivElement>(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    loadHistory();
  }, []);

  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const data = await complianceApi.fetchComplianceReports();
      setHistory(data);
    } catch {
      // ignore
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
      title: '法规来源', dataIndex: 'source', key: 'source', width: 150, ellipsis: true,
    },
    {
      title: '建议', dataIndex: 'suggestion', key: 'suggestion', ellipsis: true,
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

  const result = currentReport?.result;
  const summary = result?.summary;

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>合规检查助手</Title>

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
                pagination={{ pageSize: 10 }}
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
        <Card title={`检查报告 - ${currentReport?.product_name || ''}`} style={{ marginTop: 16 }}>
          <Descriptions size="small" style={{ marginBottom: 16 }}>
            <Descriptions.Item label="模式">
              {currentReport?.mode === 'product' ? '产品参数检查' : '条款文档审查'}
            </Descriptions.Item>
            <Descriptions.Item label="检查时间">{currentReport?.created_at}</Descriptions.Item>
          </Descriptions>

          <Space size="large" style={{ marginBottom: 16 }}>
            <Tag color="success" icon={<CheckCircleOutlined />} style={{ fontSize: 14, padding: '4px 12px' }}>
              合规 {summary.compliant} 项
            </Tag>
            <Tag color="error" icon={<CloseCircleOutlined />} style={{ fontSize: 14, padding: '4px 12px' }}>
              不合规 {summary.non_compliant} 项
            </Tag>
            <Tag color="warning" icon={<ExclamationCircleOutlined />} style={{ fontSize: 14, padding: '4px 12px' }}>
              需关注 {summary.attention} 项
            </Tag>
          </Space>

          <Table
            dataSource={result.items || []}
            columns={itemColumns}
            rowKey={(r: ComplianceItem) => r.param}
            size="middle"
            pagination={false}
            rowClassName={(record: ComplianceItem) => {
              if (record.status === 'non_compliant') return 'ant-table-row-error';
              return '';
            }}
          />
        </Card>
        </div>
      )}
    </div>
  );
}
