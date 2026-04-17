import { useEffect } from 'react';
import { Row, Col } from 'antd';
import CacheMetrics from './CacheMetrics';
import CacheTrendChart from './CacheTrendChart';
import CacheEntryList from './CacheEntryList';
import { useCacheStore } from '../../stores/cacheStore';

export default function CacheView() {
  const { loadStats, loadTrend, loadEntries } = useCacheStore();

  useEffect(() => {
    loadStats();
    loadTrend(24);
    loadEntries();
  }, [loadStats, loadTrend, loadEntries]);

  return (
    <div style={{ padding: 16, overflow: 'auto', height: '100%' }}>
      <Row gutter={[16, 16]}>
        <Col span={24}>
          <CacheMetrics />
        </Col>
        <Col span={24}>
          <CacheTrendChart />
        </Col>
        <Col span={24}>
          <CacheEntryList />
        </Col>
      </Row>
    </div>
  );
}
