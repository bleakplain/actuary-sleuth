import { Card, Row, Col, Statistic, Progress, theme } from 'antd';
import { useCacheStore } from '../../stores/cacheStore';
import type { CacheStats } from '../../types';

function NamespaceMetrics({ stats }: { stats: CacheStats }) {
  const { token } = theme.useToken();
  const namespaces = Object.entries(stats.by_namespace);

  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ fontSize: 12, color: token.colorTextTertiary, marginBottom: 8 }}>
        命名空间详情
      </div>
      <Row gutter={[8, 8]}>
        {namespaces.map(([ns, data]) => {
          const total = data.hits + data.misses;
          const rate = total > 0 ? data.hits / total : 0;
          return (
            <Col key={ns} span={8}>
              <Card size="small" style={{ background: token.colorFillQuaternary }}>
                <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 4 }}>{ns}</div>
                <Progress
                  percent={Math.round(rate * 100)}
                  size="small"
                  format={() => `${data.hits}/${total}`}
                />
              </Card>
            </Col>
          );
        })}
      </Row>
    </div>
  );
}

export default function CacheMetrics() {
  const { token } = theme.useToken();
  const { stats, loadStats } = useCacheStore();

  if (!stats) {
    return (
      <Card>
        <div style={{ color: token.colorTextTertiary, textAlign: 'center', padding: 20 }}>
          缓存未启用
        </div>
      </Card>
    );
  }

  const l1Usage = stats.memory_size / stats.max_memory_entries;

  return (
    <Card
      title="缓存统计"
      extra={
        <a onClick={() => loadStats()} style={{ fontSize: 12 }}>刷新</a>
      }
    >
      <Row gutter={16}>
        <Col span={6}>
          <Statistic
            title="命中率"
            value={Math.round(stats.hit_rate * 100)}
            suffix="%"
            valueStyle={{ color: stats.hit_rate > 0.8 ? token.colorSuccess : token.colorWarning }}
          />
        </Col>
        <Col span={6}>
          <Statistic title="命中" value={stats.hits} />
        </Col>
        <Col span={6}>
          <Statistic title="未命中" value={stats.misses} />
        </Col>
        <Col span={6}>
          <Statistic title="驱逐" value={stats.evictions} />
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={12}>
          <div style={{ fontSize: 12, color: token.colorTextTertiary, marginBottom: 4 }}>
            L1 内存缓存
          </div>
          <Progress
            percent={Math.round(l1Usage * 100)}
            format={() => `${stats.memory_size} / ${stats.max_memory_entries}`}
          />
        </Col>
        <Col span={12}>
          <div style={{ fontSize: 12, color: token.colorTextTertiary, marginBottom: 4 }}>
            L2 持久化缓存
          </div>
          <div style={{ fontSize: 16 }}>{stats.l2_size} 条</div>
        </Col>
      </Row>

      <NamespaceMetrics stats={stats} />
    </Card>
  );
}
