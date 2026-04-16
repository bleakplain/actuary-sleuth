import { Tabs, Grid } from 'antd';
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
    }}>
      <Tabs
        defaultActiveKey="trace"
        items={items}
        style={{ height: '100%' }}
        tabBarStyle={{ padding: '0 16px', marginBottom: 0 }}
      />
    </div>
  );
}
