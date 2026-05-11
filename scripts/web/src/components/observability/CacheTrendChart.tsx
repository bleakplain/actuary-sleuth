import { Card, Segmented, Skeleton, theme } from 'antd';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { useCacheStore } from '../../stores/cacheStore';
import { CHART_COLORS } from '../../constants/chartColors';

const RANGE_OPTIONS = [
  { label: '1小时', value: 1 },
  { label: '6小时', value: 6 },
  { label: '24小时', value: 24 },
  { label: '7天', value: 168 },
];

const timeFmt = new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit' });

function formatTime(iso: string): string {
  return timeFmt.format(new Date(iso));
}

export default function CacheTrendChart() {
  const { token } = theme.useToken();
  const { trendPoints, trendRangeHours, trendLoading, loadTrend } = useCacheStore();

  const data = trendPoints.map((p) => ({
    time: formatTime(p.timestamp),
    hitRate: Math.round(p.hit_rate * 100),
    hits: p.hits,
    misses: p.misses,
  }));

  return (
    <Card
      title="命中率趋势"
      extra={
        <Segmented
          size="small"
          options={RANGE_OPTIONS}
          value={trendRangeHours}
          onChange={(v) => loadTrend(v as number)}
        />
      }
    >
      {trendLoading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Skeleton active paragraph={{ rows: 3 }} />
        </div>
      ) : data.length === 0 ? (
        <div style={{ textAlign: 'center', color: token.colorTextTertiary, padding: 40 }}>
          无历史数据
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="time" tick={{ fontSize: 10 }} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} />
            <Tooltip
              formatter={(value, name) => {
                if (name === 'hitRate') return [`${value}%`, '命中率'];
                return [String(value), String(name)];
              }}
            />
            <Line
              type="monotone"
              dataKey="hitRate"
              stroke={CHART_COLORS.primary}
              dot={false}
              strokeWidth={2}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}
