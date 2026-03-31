import { Card, Row, Col, Statistic } from 'antd';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts';

interface MetricItem {
  name: string;
  value: number;
}

interface Props {
  metrics: Record<string, number>;
  title?: string;
}

export function formatMetric(value: number | undefined): string {
  if (value === undefined || value === null) return '-';
  return (value * 100).toFixed(1) + '%';
}

function extractMetricItems(metrics: Record<string, number>): MetricItem[] {
  const items: MetricItem[] = [];
  for (const [key, val] of Object.entries(metrics)) {
    if (typeof val === 'number') {
      items.push({ name: key, value: val });
    }
  }
  return items;
}

export default function MetricsChart({ metrics, title = '评估指标' }: Props) {
  const items = extractMetricItems(metrics);

  const retrievalMetrics = items.filter((i) =>
    ['retrieval.precision_at_k', 'retrieval.recall_at_k', 'retrieval.mrr', 'retrieval.ndcg',
     'precision_at_k', 'recall_at_k', 'mrr', 'ndcg'].includes(i.name),
  );
  const generationMetrics = items.filter((i) =>
    ['generation.faithfulness', 'generation.answer_relevancy', 'generation.answer_correctness',
     'faithfulness', 'answer_relevancy', 'answer_correctness'].includes(i.name),
  );

  return (
    <Card title={title} size="small">
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {items.slice(0, 6).map((item) => (
          <Col span={4} key={item.name}>
            <Statistic
              title={item.name}
              value={(item.value * 100).toFixed(1)}
              suffix="%"
              valueStyle={{ fontSize: 16 }}
            />
          </Col>
        ))}
      </Row>

      {retrievalMetrics.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <h4 style={{ marginBottom: 8 }}>检索指标</h4>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={retrievalMetrics.map((i) => ({ name: i.name, value: Number((i.value * 100).toFixed(1)) }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis domain={[0, 100]} />
              <Tooltip formatter={(v) => `${Number(v)}%`} />
              <Bar dataKey="value" fill="#1677ff" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {generationMetrics.length > 0 && (
        <div>
          <h4 style={{ marginBottom: 8 }}>生成指标</h4>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={generationMetrics.map((i) => ({ name: i.name, value: Number((i.value * 100).toFixed(1)) }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis domain={[0, 100]} />
              <Tooltip formatter={(v) => `${Number(v)}%`} />
              <Bar dataKey="value" fill="#52c41a" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
