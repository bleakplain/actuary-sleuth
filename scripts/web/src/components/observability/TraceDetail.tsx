import { CloseOutlined } from '@ant-design/icons';
import { theme } from 'antd';
import TracePanel from '../TracePanel';
import { useObservabilityStore } from '../../stores/observabilityStore';

export default function TraceDetail() {
  const { token } = theme.useToken();
  const { selectedTraceId, traceDetail, traceLoading } = useObservabilityStore();

  if (!selectedTraceId) return null;

  return (
    <div style={{
      width: '55%', minWidth: 500, maxWidth: 800,
      borderLeft: `1px solid ${token.colorBorderSecondary}`,
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
      background: token.colorBgContainer,
    }}>
      <div
        className="section-header flex-between"
        style={{ flexShrink: 0 }}
      >
        <span style={{ fontSize: 14, fontWeight: token.fontWeightStrong, color: token.colorText }}>Trace 详情</span>
        <CloseOutlined
          onClick={() => useObservabilityStore.getState().closeDetail()}
          style={{ fontSize: 14, color: token.colorTextQuaternary, cursor: 'pointer', padding: '2px 4px' }}
          title="关闭"
        />
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <TracePanel trace={traceDetail} loading={traceLoading} />
      </div>
    </div>
  );
}
