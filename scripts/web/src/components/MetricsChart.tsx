import { Card, Row, Col, Statistic, Tooltip } from 'antd';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, RadarChart, Radar, PolarGrid,
  PolarAngleAxis, PolarRadiusAxis, LineChart, Line, Legend,
} from 'recharts';
import { resolveMetricMeta, stripCategoryPrefix } from '../utils/evalMetrics';
import { CHART_COLORS } from '../constants/chartColors';

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
  retrieval: CHART_COLORS.retrieval,
  generation: CHART_COLORS.generation,
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
            <Col xs={12} sm={8} md={4} key={item.name}>
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
              <Bar dataKey="value" fill={CATEGORY_COLORS[category] || CHART_COLORS.primary} />
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
              <Radar name="基准" dataKey="baseline" stroke={CHART_COLORS.primary} fill={CHART_COLORS.primary} fillOpacity={0.2} />
              <Radar name="对比" dataKey="compare" stroke={CHART_COLORS.success} fill={CHART_COLORS.success} fillOpacity={0.2} />
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
                <Bar dataKey="baseline" fill={CHART_COLORS.primary} name="基准" />
                <Bar dataKey="compare" fill={CHART_COLORS.success} name="对比" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        );
      })}
    </Card>
  );
}

// ── 多版本对比图表 ──────────────────────────────────────

interface MultiComparisonSeries {
  label: string;
  data: Record<string, number>;
}

interface MultiComparisonChartProps {
  series: MultiComparisonSeries[];
  title?: string;
  k?: number;
}

export function MultiComparisonChart({ series, k }: MultiComparisonChartProps) {
  if (series.length === 0) return null;

  const allKeys = new Set<string>();
  for (const s of series) {
    for (const key of Object.keys(s.data)) {
      allKeys.add(key);
    }
  }

  const comparisonItems = Array.from(allKeys).map((key) => ({
    metric: key,
    values: series.map((s) => s.data[key] ?? 0),
  }));

  const radarData = comparisonItems.slice(0, 12).map((item) => {
    const entry: Record<string, string | number> = {
      metric: metricDisplayName(item.metric, k),
    };
    for (let i = 0; i < series.length; i++) {
      entry[`v${i}`] = Number((item.values[i] * 100).toFixed(1));
    }
    return entry;
  });

  const grouped = groupByCategory(
    comparisonItems.map((item) => ({ name: item.metric, value: item.values[0] })),
  );

  const barData = comparisonItems.map((item) => {
    const entry: Record<string, string | number> = {
      metric: metricDisplayName(item.metric, k),
    };
    for (let i = 0; i < series.length; i++) {
      entry[`v${i}`] = Number((item.values[i] * 100).toFixed(1));
    }
    return entry;
  });

  return (
    <Card size="small">
      {radarData.length > 2 && (
        <ResponsiveContainer width="100%" height={300}>
          <RadarChart data={radarData}>
            <PolarGrid />
            <PolarAngleAxis dataKey="metric" tick={{ fontSize: 11 }} />
            <PolarRadiusAxis domain={[0, 100]} />
            {series.map((s, i) => (
              <Radar
                key={s.label}
                name={s.label}
                dataKey={`v${i}`}
                stroke={CHART_COLORS.palette[i % CHART_COLORS.palette.length]}
                fill={CHART_COLORS.palette[i % CHART_COLORS.palette.length]}
                fillOpacity={0.15}
              />
            ))}
            <Legend />
            <RechartsTooltip />
          </RadarChart>
        </ResponsiveContainer>
      )}

      {Object.entries(grouped).map(([category]) => {
        const categoryBarData = barData.filter((d) => {
          const fullKey = `${category}.${d.metric}`;
          return comparisonItems.some((item) => item.metric === fullKey);
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
                {series.map((s, i) => (
                  <Bar
                    key={s.label}
                    dataKey={`v${i}`}
                    fill={CHART_COLORS.palette[i % CHART_COLORS.palette.length]}
                    name={s.label}
                  />
                ))}
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
    <Card title={title} size="small" styles={{ body: { paddingTop: 0 } }}>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} />
          <YAxis domain={[0, 100]} />
          <RechartsTooltip formatter={(v) => `${metricName || '指标'}: ${Number(v)}%`} />
          <Line type="monotone" dataKey="value" stroke={CHART_COLORS.primary} strokeWidth={2} dot={{ r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
    </Card>
  );
}
