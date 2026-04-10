import { Typography, Button, theme } from 'antd';
import { BugOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import CitationTag from './CitationTag';
import FeedbackButtons from './FeedbackButtons';
import { useAskStore } from '../stores/askStore';
import type { Message, Citation, Source } from '../types';

const { Text } = Typography;

function formatMsgTime(ts: string): string {
  if (!ts) return '';
  const parts = ts.split(' ');
  if (parts.length < 2) return ts;
  return parts[1].slice(0, 5);
}

interface Props {
  message: Message;
  streaming?: boolean;
  onCitationClick?: (source: Source, messageSources: Source[]) => void;
}

export default function MessageBubble({ message, streaming, onCitationClick }: Props) {
  const { token } = theme.useToken();
  const { activeTraceMessageId, openTrace, debugMode } = useAskStore();

  const handleCitationClick = (citation: Citation) => {
    const source = message.sources.find((_, i) => i === citation.source_idx);
    if (source && onCitationClick) {
      onCitationClick(source, message.sources);
    }
  };

  if (message.role === 'user') {
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <div
          style={{
            maxWidth: '70%',
            background: token.colorPrimary,
            color: token.colorTextInverse,
            padding: '8px 16px',
            borderRadius: 12,
            borderBottomRightRadius: 4,
          }}
        >
          {message.content}
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.7)', textAlign: 'right', marginTop: 4 }}>
            {formatMsgTime(message.timestamp)}
          </div>
        </div>
      </div>
    );
  }

  const content = message.content || '';
  const hasSources = message.sources && message.sources.length > 0;
  const isActive = activeTraceMessageId === message.id;
  const isThinking = streaming && !content;

  return (
    <div style={{ marginBottom: 16 }}>
      <div
        style={{
          maxWidth: '85%',
          background: token.colorFillTertiary,
          padding: '8px 16px',
          borderRadius: 12,
          borderBottomLeftRadius: 4,
        }}
      >
        {content ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        ) : (
          <Text type="secondary">思考中...</Text>
        )}
        {hasSources && (
          <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {message.sources.map((s: Source, i: number) => (
              <CitationTag
                key={i}
                citation={{
                  source_idx: i,
                  law_name: s.law_name,
                  article_number: s.article_number,
                  content: s.content,
                }}
                onClick={handleCitationClick}
              />
            ))}
          </div>
        )}
        {message.role === 'assistant' && !isThinking && (
          <div style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11, color: token.colorTextQuaternary, marginRight: 4 }}>
              {formatMsgTime(message.timestamp)}
            </span>
            <FeedbackButtons messageId={message.id} />
            {debugMode && (
              <Button
                type="text"
                size="small"
                icon={<BugOutlined />}
                onClick={() => openTrace(message.id)}
                style={{ color: isActive ? token.colorPrimary : undefined }}
              >
                调试
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
