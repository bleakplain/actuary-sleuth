import { useEffect } from 'react';
import TraceList from './TraceList';
import TraceDetail from './TraceDetail';
import { useObservabilityStore } from '../../stores/observabilityStore';

export default function TraceView() {
  const { loadTraces, selectedTraceId } = useObservabilityStore();

  useEffect(() => {
    loadTraces();
  }, [loadTraces]);

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
        <TraceList />
      </div>
      {selectedTraceId != null && <TraceDetail />}
    </div>
  );
}
