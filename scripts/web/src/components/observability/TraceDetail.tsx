import { useState } from 'react';
import { CopyOutlined } from '@ant-design/icons';
import TracePanel from '../TracePanel';
import { useObservabilityStore } from '../../stores/observabilityStore';

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <CopyOutlined
      style={{ fontSize: 11, color: '#d9d9d9', cursor: 'pointer', marginLeft: 4 }}
      onClick={() => handleCopy()}
      title={copied ? '已复制' : '复制'}
    />
  );
}

export default function TraceDetail() {
  const { selectedTraceId, traceDetail, traceLoading, traceList } = useObservabilityStore();

  if (!selectedTraceId) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#bfbfbf' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.25 }}>&#x1f50d;</div>
          <div style={{ fontSize: 13 }}>选择一条 Trace 查看详情</div>
        </div>
      </div>
    );
  }

  const selectedItem = traceList.find((t) => t.trace_id === selectedTraceId);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '10px 16px', borderBottom: '1px solid #f0f0f0', fontSize: 12, color: '#8c8c8c' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <span>
            <span style={{ color: '#bfbfbf' }}>trace_id:</span>{' '}
            <span style={{ fontFamily: "'SF Mono', monospace", color: '#262626' }}>{selectedTraceId}</span>
            <CopyBtn text={selectedTraceId} />
          </span>
          {selectedItem?.conversation_id && (
            <span>
              <span style={{ color: '#bfbfbf' }}>conversation_id:</span>{' '}
              <span style={{ fontFamily: "'SF Mono', monospace" }}>{selectedItem.conversation_id}</span>
              <CopyBtn text={selectedItem.conversation_id} />
            </span>
          )}
          {selectedItem?.message_id != null && (
            <span>
              <span style={{ color: '#bfbfbf' }}>message_id:</span>{' '}
              <span style={{ fontFamily: "'SF Mono', monospace" }}>{selectedItem.message_id}</span>
              <CopyBtn text={String(selectedItem.message_id)} />
            </span>
          )}
          {selectedItem?.created_at && (
            <span>
              <span style={{ color: '#bfbfbf' }}>created_at:</span>{' '}
              <span>{selectedItem.created_at}</span>
            </span>
          )}
        </div>
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <TracePanel trace={traceDetail} loading={traceLoading} />
      </div>
    </div>
  );
}
