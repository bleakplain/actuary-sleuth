import TraceView from '../components/observability/TraceView';

export default function ObservabilityPage() {
  return (
    <div style={{ height: 'calc(100vh - var(--header-height) - var(--content-padding) * 2)' }}>
      <TraceView />
    </div>
  );
}
