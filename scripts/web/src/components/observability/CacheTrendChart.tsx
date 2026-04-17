import { Card, Segmented, Spin } from 'antd';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { useCacheStore } from '../../stores/cacheStore';

const RANGE_OPTIONS = [
  { label: '1小时', value: 1 },
  { label: '6小时', value: 6 },
  { label: '24小时', value: 24 },
  { label: '7天', value: 168 },
];

function formatTime(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export default function CacheTrendChart() {
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
          <Spin />
        </div>
      ) : data.length === 0 ? (
        <div style={{ textAlign: 'center', color: '#999', padding: 40 }}>
          无历史数据
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="time" tick={{ fontSize: 10 }} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} />
            <Tooltip
              formatter={(value: number, name: string) => {
                if (name === 'hitRate') return [`${value}%`, '命中率'];
                return [value, name];
              }}
            />
            <Line
              type="monotone"
              dataKey="hitRate"
              stroke="#1890ff"
              dot={false}
              strokeWidth={2}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}
