import { Card, Row, Col, Statistic, Tooltip } from 'antd';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, RadarChart, Radar, PolarGrid,
  PolarAngleAxis, PolarRadiusAxis, LineChart, Line, Legend,
} from 'recharts';
import { resolveMetricMeta, stripCategoryPrefix } from '../utils/evalMetrics';

interface MetricItem {
  name: string;
  value: number;
}

interface Props {
  metrics: Record<string, number>;
  title?: string;
  k?: number;
}

export function formatMetric(value: number | undefined): string {
  if (value === undefined || value === null) return '-';
  return (value * 100).toFixed(1) + '%';
}

const CATEGORY_LABELS: Record<string, string> = {
  retrieval: '检索指标',
  generation: '生成指标',
};

const CATEGORY_COLORS: Record<string, string> = {
  retrieval: '#1677ff',
  generation: '#52c41a',
};

function groupByCategory(items: MetricItem[]): Record<string, MetricItem[]> {
  const groups: Record<string, MetricItem[]> = {};
  for (const item of items) {
    const dotIndex = item.name.indexOf('.');
    const category = dotIndex > 0 ? item.name.slice(0, dotIndex) : '_default';
    if (!groups[category]) groups[category] = [];
    groups[category].push(item);
  }
  return groups;
}

function metricDisplayName(name: string, k?: number): string {
  return resolveMetricMeta(stripCategoryPrefix(name), k).label;
}

export default function MetricsChart({ metrics, title = '评测指标', k }: Props) {
  const items: MetricItem[] = Object.entries(metrics)
    .filter(([, val]) => typeof val === 'number')
    .map(([key, val]) => ({ name: key, value: val }));

  const grouped = groupByCategory(items);

  return (
    <Card title={title} size="small">
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {items.slice(0, 6).map((item) => {
          const meta = resolveMetricMeta(stripCategoryPrefix(item.name), k);
          return (
            <Col span={4} key={item.name}>
              <Tooltip title={meta.tooltip}>
                <Statistic
                  title={meta.label}
                  value={(item.value * 100).toFixed(1)}
                  suffix="%"
                  valueStyle={{ fontSize: 16 }}
                />
              </Tooltip>
            </Col>
          );
        })}
      </Row>

      {Object.entries(grouped).map(([category, categoryItems]) => (
        <div key={category} style={Object.keys(grouped).indexOf(category) < Object.keys(grouped).length - 1 ? { marginBottom: 24 } : undefined}>
          <h4 style={{ marginBottom: 8 }}>{CATEGORY_LABELS[category] || category}</h4>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={categoryItems.map((i) => ({ name: metricDisplayName(i.name, k), value: Number((i.value * 100).toFixed(1)) }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 100]} />
              <RechartsTooltip formatter={(v) => `${Number(v)}%`} />
              <Bar dataKey="value" fill={CATEGORY_COLORS[category] || '#1677ff'} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ))}
    </Card>
  );
}

// ── 对比图表 ────────────────────────────────────────────

interface ComparisonData {
  metric: string;
  baseline: number;
  compare: number;
  delta: number;
  pct_change: number;
}

interface ComparisonChartProps {
  data: ComparisonData[];
  title?: string;
  k?: number;
}

export function ComparisonChart({ data, title = '指标对比', k }: ComparisonChartProps) {
  const grouped = groupByCategory(
    data.map((d) => ({ name: d.metric, value: d.compare }))
  );

  const radarData = data.slice(0, 10).map((d) => ({
    metric: metricDisplayName(d.metric, k),
    baseline: Number((d.baseline * 100).toFixed(1)),
    compare: Number((d.compare * 100).toFixed(1)),
  }));

  const barData = data.map((d) => ({
    metric: metricDisplayName(d.metric, k),
    baseline: Number((d.baseline * 100).toFixed(1)),
    compare: Number((d.compare * 100).toFixed(1)),
  }));

  return (
    <Card title={title} size="small">
      {radarData.length > 2 && (
        <div style={{ marginBottom: 24 }}>
          <h4 style={{ marginBottom: 8 }}>雷达图</h4>
          <ResponsiveContainer width="100%" height={300}>
            <RadarChart data={radarData}>
              <PolarGrid />
              <PolarAngleAxis dataKey="metric" tick={{ fontSize: 11 }} />
              <PolarRadiusAxis domain={[0, 100]} />
              <Radar name="基准" dataKey="baseline" stroke="#1677ff" fill="#1677ff" fillOpacity={0.2} />
              <Radar name="对比" dataKey="compare" stroke="#52c41a" fill="#52c41a" fillOpacity={0.2} />
              <Legend />
              <RechartsTooltip />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      )}

      {Object.entries(grouped).map(([category]) => {
        const categoryBarData = barData.filter((d) => {
          const fullKey = `${category}.${d.metric}`;
          return data.some((item) => item.metric === fullKey);
        });
        if (categoryBarData.length === 0) return null;

        return (
          <div key={category} style={{ marginBottom: 24 }}>
            <h4 style={{ marginBottom: 8 }}>{CATEGORY_LABELS[category] || category}</h4>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={categoryBarData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="metric" tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 100]} />
                <RechartsTooltip formatter={(v) => `${Number(v)}%`} />
                <Legend />
                <Bar dataKey="baseline" fill="#1677ff" name="基准" />
                <Bar dataKey="compare" fill="#52c41a" name="对比" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        );
      })}
    </Card>
  );
}

// ── 趋势图表 ────────────────────────────────────────────

interface TrendPoint {
  run_id: string;
  label: string;
  value: number;
  timestamp: string;
}

interface TrendChartProps {
  data: TrendPoint[];
  metricName?: string;
  title?: string;
}

export function TrendChart({ data, metricName, title = '指标趋势' }: TrendChartProps) {
  const chartData = data.map((d) => ({
    label: d.label || d.run_id.slice(0, 12),
    value: Number((d.value * 100).toFixed(1)),
  }));

  if (chartData.length === 0) return null;

  return (
    <Card title={title} size="small" bodyStyle={{ paddingTop: 0 }}>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} />
          <YAxis domain={[0, 100]} />
          <RechartsTooltip formatter={(v) => `${metricName || '指标'}: ${Number(v)}%`} />
          <Line type="monotone" dataKey="value" stroke="#1677ff" strokeWidth={2} dot={{ r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
    </Card>
  );
}
