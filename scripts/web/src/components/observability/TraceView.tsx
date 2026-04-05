import { useState, useEffect } from 'react';
import TraceList from './TraceList';
import TraceDetail from './TraceDetail';
import CleanupDialog from './CleanupDialog';
import { useObservabilityStore } from '../../stores/observabilityStore';

export default function TraceView() {
  const { loadTraces } = useObservabilityStore();
  const [cleanupOpen, setCleanupOpen] = useState(false);

  useEffect(() => {
    loadTraces();
  }, [loadTraces]);

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      <TraceList onCleanupOpen={() => setCleanupOpen(true)} />
      <TraceDetail />
      <CleanupDialog
        open={cleanupOpen}
        onClose={() => setCleanupOpen(false)}
        onCleanupDone={() => loadTraces()}
      />
    </div>
  );
}
