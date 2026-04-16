import { useEffect } from 'react';
import { Grid } from 'antd';
import TraceList from './TraceList';
import TraceDetail from './TraceDetail';
import { useObservabilityStore } from '../../stores/observabilityStore';

export default function TraceView() {
  const { loadTraces, selectedTraceId } = useObservabilityStore();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  useEffect(() => {
    loadTraces();
  }, [loadTraces]);

  return (
    <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', height: '100%', overflow: 'hidden' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
        <TraceList />
      </div>
      {selectedTraceId != null && <TraceDetail />}
    </div>
  );
}
