import React, { useEffect } from 'react';
import { Table, Tag, Select, Button, Space, message, Popconfirm, Modal, Descriptions, Card, Statistic, Row, Col, Tooltip, Typography, theme } from 'antd';
import { ReloadOutlined, ThunderboltOutlined, DislikeOutlined, LikeOutlined, WarningOutlined } from '@ant-design/icons';
import { useFeedbackStore } from '../stores/feedbackStore';
import { DRAWER_LG } from '../constants/layout';
import { verifyBadcase, convertBadcase } from '../api/feedback';

const TYPE_COLORS: Record<string, string> = {
  retrieval_failure: 'orange', hallucination: 'red', knowledge_gap: 'blue',
};
const TYPE_LABELS: Record<string, string> = {
  retrieval_failure: '检索失败', hallucination: '幻觉生成', knowledge_gap: '知识缺失',
};
const STATUS_LABELS: Record<string, string> = {
  pending: '待分类', classified: '已分类', fixing: '修复中',
  fixed: '已修复', rejected: '已驳回', converted: '已转化',
};
const RISK_COLORS: Record<number, string> = { 0: 'green', 1: 'orange', 2: 'red' };
const RISK_LABELS: Record<number, string> = { 0: '低', 1: '中', 2: '高' };

export default function FeedbackPage() {
  const { badcases, stats, loading, loadBadcases, loadStats, classifyAll, updateBadcase } = useFeedbackStore();
  const { token } = theme.useToken();
  const [filterStatus, setFilterStatus] = React.useState<string | undefined>();

  useEffect(() => { loadBadcases({ status: filterStatus }); }, [filterStatus, loadBadcases]);
  useEffect(() => { loadStats(); }, [loadStats]);

  const handleClassify = async () => {
    try {
      await classifyAll();
      message.success('批量分类完成');
    } catch {
      message.error('分类失败');
    }
  };

  const expandedRowRender = (record: typeof badcases[0]) => (
    <div style={{ padding: '8px 16px' }}>
      <Descriptions bordered size="small" column={1}>
        <Descriptions.Item label="用户问题">
          <span style={{ fontWeight: token.fontWeightStrong }}>{record.user_question || '（无法获取）'}</span>
        </Descriptions.Item>
        <Descriptions.Item label="助手回答">
          <div style={{ maxHeight: 200, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
            {record.assistant_answer || '（无法获取）'}
          </div>
        </Descriptions.Item>
        <Descriptions.Item label="用户反馈">
          <Space>
            {record.rating === 'up'
              ? <Tag icon={<LikeOutlined />} color="green">满意</Tag>
              : <Tag icon={<DislikeOutlined />} color="red">不满意</Tag>}
            {record.reason && <span>原因：{record.reason}</span>}
            {record.correction && (
              <span>修正建议：<span style={{ color: token.colorPrimary }}>{record.correction}</span></span>
            )}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="来源渠道">
          {record.source_channel === 'user_button' ? '用户按钮' : record.source_channel === 'auto_detect' ? '自动检测' : record.source_channel}
        </Descriptions.Item>
        {record.classified_type && (
          <Descriptions.Item label="分类详情">
            <Space direction="vertical">
              <span>类型：<Tag color={TYPE_COLORS[record.classified_type]}>{TYPE_LABELS[record.classified_type] || record.classified_type}</Tag></span>
              <span>原因：{record.classified_reason}</span>
              <span>修复方向：{record.classified_fix_direction}</span>
            </Space>
          </Descriptions.Item>
        )}
        {record.auto_quality_details && (
          <Descriptions.Item label="质量评估">
            <Space>
              <Tag>忠实度: {record.auto_quality_details.faithfulness?.toFixed(2) ?? '-'}</Tag>
              <Tag>检索相关: {record.auto_quality_details.retrieval_relevance?.toFixed(2) ?? '-'}</Tag>
              <Tag>完整性: {record.auto_quality_details.completeness?.toFixed(2) ?? '-'}</Tag>
              <Tag color="blue">综合: {record.auto_quality_score?.toFixed(2) ?? '-'}</Tag>
            </Space>
          </Descriptions.Item>
        )}
      </Descriptions>
    </div>
  );

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 140, ellipsis: true },
    {
      title: '问题摘要', dataIndex: 'user_question', key: 'user_question', ellipsis: true,
      render: (q: string) => q || '-',
    },
    {
      title: '反馈', key: 'feedback', width: 100,
      render: (_: unknown, record: typeof badcases[0]) => (
        record.rating === 'up'
          ? <Tag icon={<LikeOutlined />} color="green">满意</Tag>
          : <Tag icon={<DislikeOutlined />} color="red">不满意</Tag>
      ),
    },
    {
      title: '分类', dataIndex: 'classified_type', key: 'classified_type', width: 100,
      render: (type: string | null) =>
        type ? <Tag color={TYPE_COLORS[type]}>{TYPE_LABELS[type] || type}</Tag> : <Tag>未分类</Tag>,
    },
    {
      title: '风险', dataIndex: 'compliance_risk', key: 'compliance_risk', width: 70,
      render: (risk: number) => <Tag color={RISK_COLORS[risk]}>{RISK_LABELS[risk]}</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (status: string) => <Tag>{STATUS_LABELS[status] || status}</Tag>,
    },
    {
      title: '质量分', dataIndex: 'auto_quality_score', key: 'auto_quality_score', width: 70,
      render: (score: number | null) => score !== null ? score.toFixed(2) : '-',
    },
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 150 },
    {
      title: '操作', key: 'actions', width: 200,
      render: (_: unknown, record: typeof badcases[0]) => (
        <Space size={4}>
          <Button size="small" onClick={async () => {
            try {
              const result = await verifyBadcase(record.id);
              Modal.info({
                title: '验证结果',
                width: DRAWER_LG,
                content: (
                  <div>
                    <Typography.Text strong>新回答：</Typography.Text>
                    <p>{result.new_answer}</p>
                    <p>忠实度: {result.new_faithfulness != null ? (result.new_faithfulness as number).toFixed(2) : '未计算'}</p>
                    {result.new_unverified_claims?.length > 0 && (
                      <>
                        <Typography.Text strong>未验证陈述：</Typography.Text>
                        <ul>{(result.new_unverified_claims as string[]).map((c, i) => <li key={i}>{c}</li>)}</ul>
                      </>
                    )}
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

  const pendingCount = stats?.by_status?.['pending'] ?? 0;
  const highRiskCount = Object.entries(stats?.by_risk ?? {})
    .filter(([k]) => k !== '0').reduce((sum, [, v]) => sum + v, 0);

  return (
    <div>
      <Typography.Title level={4} className="mb-16">问题反馈</Typography.Title>

      {/* 统计概览 */}
      {stats && (
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={8}>
            <Card size="small"><Statistic title="总反馈" value={stats.total} /></Card>
          </Col>
          <Col span={8}>
            <Card size="small"><Statistic title="好评" value={stats.up_count} valueStyle={{ color: token.colorSuccess }} /></Card>
          </Col>
          <Col span={8}>
            <Card size="small"><Statistic title="差评" value={stats.down_count} valueStyle={{ color: token.colorError }} /></Card>
          </Col>
          <Col span={8}>
            <Card size="small"><Statistic title="满意度" value={stats.satisfaction_rate * 100} suffix="%" precision={1} /></Card>
          </Col>
          <Col span={8}>
            <Tooltip title="待分类的反馈数量">
              <Card size="small"><Statistic title="待处理" value={pendingCount} valueStyle={{ color: pendingCount > 0 ? token.colorWarning : undefined }} /></Card>
            </Tooltip>
          </Col>
          <Col span={8}>
            <Tooltip title="合规风险为中/高的反馈数量">
              <Card size="small"><Statistic title="高风险" value={highRiskCount} prefix={<WarningOutlined />} valueStyle={{ color: highRiskCount > 0 ? token.colorError : undefined }} /></Card>
            </Tooltip>
          </Col>
        </Row>
      )}

      {/* Badcase 列表 */}
      <div className="flex-between" style={{ marginBottom: 16 }}>
        <span style={{ color: token.colorTextSecondary, fontSize: token.fontSize }}>
          共 {badcases.length} 条反馈，点击行展开查看详情
        </span>
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
          <Button icon={<ReloadOutlined />} onClick={() => { loadBadcases({ status: filterStatus }); loadStats(); }}>刷新</Button>
        </Space>
      </div>
      <Table
        columns={columns}
        dataSource={badcases}
        rowKey="id"
        loading={loading}
        size="small"
        expandable={{ expandedRowRender }}
        pagination={{ pageSize: 20 }}
      />
    </div>
  );
}
