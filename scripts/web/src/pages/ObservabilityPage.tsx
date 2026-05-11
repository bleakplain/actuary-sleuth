import { Tabs, Grid } from 'antd';
import { ExperimentOutlined } from '@ant-design/icons';
import PageHeader from '../components/PageHeader';
import TraceView from '../components/observability/TraceView';
import CacheView from '../components/observability/CacheView';

export default function ObservabilityPage() {
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  const items = [
    { key: 'trace', label: 'Trace', children: <TraceView /> },
    { key: 'cache', label: 'Cache', children: <CacheView /> },
  ];

  return (
    <div style={{
      height: isMobile
        ? 'calc(100vh - 48px - var(--mobile-nav-height) - env(safe-area-inset-bottom, 0px))'
        : 'calc(100vh - var(--header-height) - var(--content-padding) * 2)',
      display: 'flex',
      flexDirection: 'column',
    }}>
      <PageHeader icon={<ExperimentOutlined />} title="可观测性" description="Trace 链路追踪与缓存监控" isMobile={isMobile} />
      <Tabs
        defaultActiveKey="trace"
        items={items}
        style={{ flex: 1, minHeight: 0 }}
        tabBarStyle={{ padding: '0 16px', marginBottom: 0 }}
      />
    </div>
  );
}
