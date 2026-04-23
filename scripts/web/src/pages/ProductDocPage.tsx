import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Card, Table, Button, Modal, Typography, message, Tag, Descriptions,
  Tabs, theme, Grid, Input, Drawer, Form, Select, Space
} from 'antd';
import { FileTextOutlined } from '@ant-design/icons';
import * as api from '../api/productDoc';
import type { ParsedDocument } from '../api/productDoc';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const { Text } = Typography;

export default function ProductDocPage() {
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  const [documents, setDocuments] = useState<ParsedDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState<ParsedDocument | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedItem, setSelectedItem] = useState<{ type: string; index: number } | null>(null);
  const [reviewDrawerOpen, setReviewDrawerOpen] = useState(false);
  const [reviewForm] = Form.useForm();

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    try {
      const docs = await api.fetchParsedDocuments();
      setDocuments(docs);
    } catch (err) {
      message.error(`加载失败: ${err}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  const handleViewDetail = (doc: ParsedDocument) => {
    setSelectedDoc(doc);
    setDetailOpen(true);
    setSelectedItem(null);
  };

  const parseItems = useMemo(() => {
    if (!selectedDoc) return [];
    const items: Array<{ type: string; index: number; label: string; content: string }> = [];
    selectedDoc.clauses.forEach((c, i) => {
      items.push({ type: 'clause', index: i, label: `条款 ${c.number}`, content: c.text });
    });
    selectedDoc.premium_tables.forEach((_, i) => {
      items.push({ type: 'premium_table', index: i, label: `费率表 ${i + 1}`, content: '[表格]' });
    });
    selectedDoc.notices.forEach((n, i) => {
      items.push({ type: 'notice', index: i, label: `须知: ${n.title}`, content: n.content });
    });
    selectedDoc.health_disclosures.forEach((h, i) => {
      items.push({ type: 'health_disclosure', index: i, label: `健康告知 ${i + 1}`, content: h.content });
    });
    selectedDoc.exclusions.forEach((e, i) => {
      items.push({ type: 'exclusion', index: i, label: `责任免除 ${i + 1}`, content: e.content });
    });
    selectedDoc.rider_clauses.forEach((r, i) => {
      items.push({ type: 'rider_clause', index: i, label: `附加险条款 ${r.number}`, content: r.text });
    });
    return items;
  }, [selectedDoc]);

  const handleSubmitReview = async (values: { reviewer: string; comment?: string; status: 'approved' | 'rejected' }) => {
    if (!selectedDoc) return;
    try {
      await api.reviewDocument(selectedDoc.id, values);
      message.success('审核已提交');
      setReviewDrawerOpen(false);
      reviewForm.resetFields();
      loadDocuments();
    } catch (err) {
      message.error(`提交失败: ${err}`);
    }
  };

  const columns = [
    { title: '文件名', dataIndex: 'file_name', key: 'file_name', ellipsis: true },
    { title: '类型', dataIndex: 'file_type', key: 'file_type', width: 80 },
    { title: '条款数', key: 'clause_count', width: 80, render: (_: unknown, r: ParsedDocument) => r.clauses.length },
    { title: '状态', dataIndex: 'review_status', key: 'review_status', width: 100, render: (v: string) => (
      <Tag color={v === 'approved' ? 'green' : 'default'}>{v === 'approved' ? '已通过' : '待审核'}</Tag>
    )},
    { title: '操作', key: 'action', width: 100, render: (_: unknown, r: ParsedDocument) => (
      <Button type="link" size="small" onClick={() => handleViewDetail(r)}>查看</Button>
    )},
  ];

  const detailContent = selectedItem && selectedDoc ? (
    <Descriptions bordered column={1} size="small">
      <Descriptions.Item label="类型">{parseItems.find(p => p.type === selectedItem.type && p.index === selectedItem.index)?.label}</Descriptions.Item>
      <Descriptions.Item label="内容">
        <div className="markdown-body" style={{ maxHeight: 400, overflow: 'auto' }}>
          {selectedItem.type === 'premium_table' ? (
            <pre style={{ whiteSpace: 'pre-wrap' }}>{selectedDoc.premium_tables[selectedItem.index]?.raw_text}</pre>
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {parseItems.find(p => p.type === selectedItem.type && p.index === selectedItem.index)?.content || ''}
            </ReactMarkdown>
          )}
        </div>
      </Descriptions.Item>
    </Descriptions>
  ) : (
    <div style={{ color: token.colorTextSecondary, padding: 24 }}>点击左侧项查看详情</div>
  );

  return (
    <Card title="产品文档解析审核">
      <Table
        dataSource={documents}
        rowKey="id"
        columns={columns}
        loading={loading}
        pagination={{ pageSize: 20 }}
      />

      <Modal
        title={selectedDoc?.file_name}
        open={detailOpen}
        onCancel={() => { setDetailOpen(false); setSelectedDoc(null); }}
        footer={
          <Space>
            <Button onClick={() => { setDetailOpen(false); setSelectedDoc(null); }}>关闭</Button>
            <Button type="primary" onClick={() => setReviewDrawerOpen(true)}>提交审核</Button>
          </Space>
        }
        width={isMobile ? '100%' : '90vw'}
        style={{ top: 20 }}
      >
        {selectedDoc && (
          isMobile ? (
            <Tabs
              size="small"
              items={[
                {
                  key: 'list',
                  label: `解析项 (${parseItems.length})`,
                  children: (
                    <div style={{ height: 'calc(100vh - 200px)', overflow: 'auto' }}>
                      <Table
                        dataSource={parseItems}
                        rowKey={(_, i) => String(i)}
                        size="small"
                        pagination={false}
                        onRow={(record) => ({
                          onClick: () => setSelectedItem({ type: record.type, index: record.index }),
                          style: { cursor: 'pointer' },
                        })}
                        columns={[
                          { title: '类型', dataIndex: 'label', key: 'label', ellipsis: true },
                          { title: '摘要', dataIndex: 'content', key: 'content', ellipsis: true, render: (v: string) => v.slice(0, 50) },
                        ]}
                      />
                    </div>
                  ),
                },
                {
                  key: 'detail',
                  label: '详情',
                  children: <div style={{ height: 'calc(100vh - 200px)', overflow: 'auto' }}>{detailContent}</div>,
                },
              ]}
            />
          ) : (
            <div style={{ display: 'flex', height: 'calc(100vh - 200px)' }}>
              <div style={{ width: '45%', borderRight: `1px solid ${token.colorBorderSecondary}`, overflow: 'auto' }}>
                <Table
                  dataSource={parseItems}
                  rowKey={(_, i) => String(i)}
                  size="small"
                  pagination={false}
                  onRow={(record) => ({
                    onClick: () => setSelectedItem({ type: record.type, index: record.index }),
                    style: { cursor: 'pointer' },
                  })}
                  columns={[
                    { title: '类型', dataIndex: 'label', key: 'label', ellipsis: true },
                    { title: '内容摘要', dataIndex: 'content', key: 'content', ellipsis: true, render: (v: string) => v.slice(0, 50) },
                  ]}
                />
              </div>
              <div style={{ width: '55%', padding: 16, overflow: 'auto' }}>{detailContent}</div>
            </div>
          )
        )}
      </Modal>

      <Drawer
        title="提交审核"
        open={reviewDrawerOpen}
        onClose={() => setReviewDrawerOpen(false)}
        width={400}
      >
        <Form form={reviewForm} layout="vertical" onFinish={handleSubmitReview}>
          <Form.Item name="reviewer" label="审核人" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="status" label="审核结果" rules={[{ required: true }]} initialValue="approved">
            <Select options={[
              { value: 'approved', label: '通过' },
              { value: 'rejected', label: '不通过' },
            ]} />
          </Form.Item>
          <Form.Item name="comment" label="备注">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">提交</Button>
          </Form.Item>
        </Form>
      </Drawer>
    </Card>
  );
}