import { CloseOutlined } from '@ant-design/icons';
import { theme, Grid } from 'antd';
import TracePanel from '../TracePanel';
import { useObservabilityStore } from '../../stores/observabilityStore';

export default function TraceDetail() {
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const { selectedTraceId, traceDetail, traceLoading } = useObservabilityStore();

  if (!selectedTraceId) return null;

  return (
    <div style={{
      width: isMobile ? '100%' : '55%',
      minWidth: isMobile ? 0 : 500,
      maxWidth: isMobile ? '100%' : 800,
      height: isMobile ? '50%' : undefined,
      borderLeft: isMobile ? 'none' : `1px solid ${token.colorBorderSecondary}`,
      borderTop: isMobile ? `1px solid ${token.colorBorderSecondary}` : 'none',
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
          style={{ fontSize: 14, color: token.colorTextQuaternary, cursor: 'pointer', padding: '8px', minWidth: 44, minHeight: 44, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          title="关闭"
        />
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <TracePanel trace={traceDetail} loading={traceLoading} />
      </div>
    </div>
  );
}
