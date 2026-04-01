import React, { useEffect } from 'react';
import { Card, Statistic, Row, Col, Table } from 'antd';
import { useFeedbackStore } from '../stores/feedbackStore';

const TYPE_LABELS: Record<string, string> = {
  retrieval_failure: '检索失败', hallucination: '幻觉生成', knowledge_gap: '知识缺失',
};

const STATUS_LABELS: Record<string, string> = {
  pending: '待分类', classified: '已分类', fixing: '修复中',
  fixed: '已修复', rejected: '已驳回', converted: '已转化',
};

export default function FeedbackStatsPage() {
  const { stats, loadStats } = useFeedbackStore();
  useEffect(() => { loadStats(); }, [loadStats]);

  if (!stats) return <div style={{ padding: 24 }}>加载中...</div>;

  const typeData = Object.entries(stats.by_type).map(([type, count]) => ({ type, count }));
  const statusData = Object.entries(stats.by_status).map(([status, count]) => ({ status, count }));

  return (
    <div style={{ padding: 24 }}>
      <h2>反馈统计</h2>
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}><Card><Statistic title="总反馈数" value={stats.total} /></Card></Col>
        <Col span={6}><Card><Statistic title="好评数" value={stats.up_count} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={6}><Card><Statistic title="差评数" value={stats.down_count} valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
        <Col span={6}><Card><Statistic title="满意度" value={stats.satisfaction_rate * 100} suffix="%" precision={1} /></Card></Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Card title="按类型分布">
            <Table dataSource={typeData} rowKey="type" pagination={false} size="small"
              columns={[
                { title: '类型', dataIndex: 'type', render: (t: string) => TYPE_LABELS[t] || t },
                { title: '数量', dataIndex: 'count' },
              ]}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="按状态分布">
            <Table dataSource={statusData} rowKey="status" pagination={false} size="small"
              columns={[
                { title: '状态', dataIndex: 'status', render: (s: string) => STATUS_LABELS[s] || s },
                { title: '数量', dataIndex: 'count' },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
