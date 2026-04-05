import TraceView from '../components/observability/TraceView';

export default function ObservabilityPage() {
  return (
    <div style={{ height: 'calc(100vh - 64px - 32px)' }}>
      <TraceView />
    </div>
  );
}
