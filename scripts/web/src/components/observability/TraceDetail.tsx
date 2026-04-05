import { CloseOutlined } from '@ant-design/icons';
import TracePanel from '../TracePanel';
import { useObservabilityStore } from '../../stores/observabilityStore';

export default function TraceDetail() {
  const { selectedTraceId, traceDetail, traceLoading } = useObservabilityStore();

  if (!selectedTraceId) return null;

  return (
    <div style={{
      width: '55%', minWidth: 500, maxWidth: 800,
      borderLeft: '1px solid #f0f0f0',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
      background: '#fff',
    }}>
      <div style={{
        padding: '8px 16px', borderBottom: '1px solid #f0f0f0',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 14, fontWeight: 500, color: '#262626' }}>Trace 详情</span>
        <CloseOutlined
          onClick={() => useObservabilityStore.getState().closeDetail()}
          style={{ fontSize: 14, color: '#bfbfbf', cursor: 'pointer', padding: '2px 4px' }}
          title="关闭"
        />
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <TracePanel trace={traceDetail} loading={traceLoading} />
      </div>
    </div>
  );
}
