import React, { useEffect } from 'react';
import { Table, Tag, Select, Button, Space, message, Popconfirm, Modal } from 'antd';
import { ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useFeedbackStore } from '../stores/feedbackStore';
import { verifyBadcase, convertBadcase } from '../api/feedback';

const TYPE_COLORS: Record<string, string> = {
  retrieval_failure: 'orange',
  hallucination: 'red',
  knowledge_gap: 'blue',
};

const TYPE_LABELS: Record<string, string> = {
  retrieval_failure: '检索失败',
  hallucination: '幻觉生成',
  knowledge_gap: '知识缺失',
};

const STATUS_LABELS: Record<string, string> = {
  pending: '待分类',
  classified: '已分类',
  fixing: '修复中',
  fixed: '已修复',
  rejected: '已驳回',
  converted: '已转化',
};

const RISK_COLORS: Record<number, string> = { 0: 'green', 1: 'orange', 2: 'red' };
const RISK_LABELS: Record<number, string> = { 0: '低', 1: '中', 2: '高' };

export default function FeedbackBadcasesPage() {
  const { badcases, loading, loadBadcases, classifyAll, updateBadcase } = useFeedbackStore();
  const [filterStatus, setFilterStatus] = React.useState<string | undefined>();

  useEffect(() => {
    loadBadcases({ status: filterStatus });
  }, [filterStatus, loadBadcases]);

  const handleClassify = async () => {
    try {
      await classifyAll();
      message.success('批量分类完成');
    } catch {
      message.error('分类失败');
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 160, ellipsis: true },
    { title: '原因', dataIndex: 'reason', key: 'reason', width: 150, ellipsis: true },
    {
      title: '分类', dataIndex: 'classified_type', key: 'classified_type', width: 100,
      render: (type: string | null) =>
        type ? <Tag color={TYPE_COLORS[type]}>{TYPE_LABELS[type] || type}</Tag> : <Tag>未分类</Tag>,
    },
    {
      title: '风险', dataIndex: 'compliance_risk', key: 'compliance_risk', width: 80,
      render: (risk: number) => <Tag color={RISK_COLORS[risk]}>{RISK_LABELS[risk]}</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (status: string) => STATUS_LABELS[status] || status,
    },
    {
      title: '质量分', dataIndex: 'auto_quality_score', key: 'auto_quality_score', width: 80,
      render: (score: number | null) => score !== null ? score.toFixed(2) : '-',
    },
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 160 },
    {
      title: '操作', key: 'actions', width: 220,
      render: (_: unknown, record: typeof badcases[0]) => (
        <Space size={4}>
          <Button size="small" onClick={async () => {
            try {
              const result = await verifyBadcase(record.id);
              Modal.info({
                title: '验证结果',
                width: 700,
                content: (
                  <div>
                    <h4>新回答:</h4>
                    <p>{result.new_answer}</p>
                    <p>忠实度: {result.new_faithfulness}</p>
                  </div>
                ),
              });
            } catch { message.error('验证失败'); }
          }}>验证</Button>
          {record.status === 'pending' && (
            <Popconfirm title="标记为已驳回？" onConfirm={() => updateBadcase(record.id, { status: 'rejected' })}>
              <Button size="small" danger>驳回</Button>
            </Popconfirm>
          )}
          {record.status === 'classified' && (
            <Popconfirm title="标记为已修复？" onConfirm={() => updateBadcase(record.id, { status: 'fixed' })}>
              <Button size="small" type="primary">已修复</Button>
            </Popconfirm>
          )}
          {record.status === 'fixed' && (
            <Popconfirm
              title="转化为评估样本？需要提供正确答案"
              onConfirm={async () => {
                const ground_truth = prompt('请输入正确答案（ground_truth）：');
                if (ground_truth) {
                  try {
                    await convertBadcase(record.id, ground_truth);
                    message.success('已转化为评估样本');
                    loadBadcases({ status: filterStatus });
                  } catch { message.error('转化失败'); }
                }
              }}
            >
              <Button size="small" type="dashed">转化</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>Badcase 管理</h2>
        <Space>
          <Select placeholder="按状态筛选" allowClear style={{ width: 120 }}
            value={filterStatus} onChange={setFilterStatus}
            options={[
              { label: '待分类', value: 'pending' },
              { label: '已分类', value: 'classified' },
              { label: '修复中', value: 'fixing' },
              { label: '已修复', value: 'fixed' },
            ]}
          />
          <Button icon={<ThunderboltOutlined />} onClick={handleClassify} loading={loading}>批量分类</Button>
          <Button icon={<ReloadOutlined />} onClick={() => loadBadcases({ status: filterStatus })}>刷新</Button>
        </Space>
      </div>
      <Table columns={columns} dataSource={badcases} rowKey="id" loading={loading} size="small" pagination={{ pageSize: 20 }} />
    </div>
  );
}
