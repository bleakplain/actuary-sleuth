import { Typography, Button, Popconfirm, theme } from 'antd';
import { BugOutlined, CloseOutlined } from '@ant-design/icons';
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSanitize from 'rehype-sanitize';
import CitationTag from './CitationTag';
import FeedbackButtons from './FeedbackButtons';
import { ClickableDiv } from './ClickableDiv';
import { useAskStore } from '../stores/askStore';
import type { Message, Citation, Source } from '../types';

const { Text } = Typography;

function formatMsgTime(ts: string): string {
  if (!ts) return '';
  const date = new Date(ts.includes('T') ? ts : ts.replace(' ', 'T') + 'Z');
  if (isNaN(date.getTime())) return ts;
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
}

interface Props {
  message: Message;
  streaming?: boolean;
  onCitationClick?: (source: Source, messageSources: Source[]) => void;
  isMobile?: boolean;
}

export default function MessageBubble({ message, streaming, onCitationClick, isMobile }: Props) {
  const { token } = theme.useToken();
  const { activeTraceMessageId, openTrace, debugMode, deleteMessage, sendMessage } = useAskStore();
  const [hovered, setHovered] = useState(false);

  const handleCitationClick = (citation: Citation) => {
    const source = message.sources.find((_, i) => i === citation.source_idx);
    if (source && onCitationClick) {
      onCitationClick(source, message.sources);
    }
  };

  const handleClarifyOption = (option: string) => {
    sendMessage(option, 'qa');
  };

  if (message.role === 'user') {
    const showDelete = isMobile || hovered;
    return (
      <article
        aria-label={`用户消息 ${formatMsgTime(message.timestamp)}`}
        style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16, position: 'relative' }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {showDelete && (
          <Popconfirm
            title="删除这条消息及其回答？此操作不可恢复。"
            onConfirm={() => deleteMessage(message.id)}
            okText="删除"
            cancelText="取消"
          >
            <Button
              type="text"
              size="small"
              icon={<CloseOutlined />}
              aria-label="删除消息"
              onMouseDown={(e) => e.stopPropagation()}
              style={{
                position: 'absolute',
                right: 0,
                top: -20,
                color: token.colorTextTertiary,
                fontSize: 12,
                zIndex: 1,
                ...(isMobile ? { minWidth: 44, minHeight: 44, top: -4, display: 'flex' as const, alignItems: 'center', justifyContent: 'center' } : {}),
              }}
            />
          </Popconfirm>
        )}
        <div
          style={{
            maxWidth: isMobile ? '92%' : '70%',
            background: token.colorPrimary,
            color: token.colorWhite,
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
      </article>
    );
  }

  const content = message.content || '';
  const hasSources = message.sources && message.sources.length > 0;
  const isActive = activeTraceMessageId === message.id;
  const isThinking = streaming && !content;
  const isSearchResult = content.startsWith('[') && hasSources;

  return (
    <article aria-label={`助手消息 ${formatMsgTime(message.timestamp)}`} style={{ marginBottom: 16 }}>
      <div
        style={{
          maxWidth: isMobile ? '95%' : '85%',
          background: token.colorFillTertiary,
          padding: '8px 16px',
          borderRadius: 12,
          borderBottomLeftRadius: 4,
          overflowWrap: 'break-word',
          wordBreak: 'break-word',
        }}
      >
        {isSearchResult ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {message.sources.map((s: Source, i: number) => (
              <ClickableDiv
                key={i}
                onActivate={() => onCitationClick?.(s, message.sources)}
                style={{
                  background: token.colorBgContainer,
                  border: `1px solid ${token.colorBorderSecondary}`,
                  borderRadius: 8,
                  padding: isMobile ? '12px 16px' : '8px 12px',
                  cursor: 'pointer',
                  minHeight: isMobile ? 48 : undefined,
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 500, color: token.colorText, marginBottom: 4 }}>
                  {s.law_name}
                  {s.article_number ? (
                    <span style={{ color: token.colorTextSecondary, fontWeight: 400 }}> · {s.article_number}</span>
                  ) : null}
                </div>
                <div style={{
                  fontSize: 12,
                  color: token.colorTextSecondary,
                  lineHeight: 1.6,
                  display: '-webkit-box',
                  WebkitLineClamp: 3,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                }}>
                  {s.content}
                </div>
              </ClickableDiv>
            ))}
          </div>
        ) : message.needsClarification ? (
          <div>
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{content}</ReactMarkdown>
            {message.clarificationOptions && message.clarificationOptions.length > 0 && (
              <div style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {message.clarificationOptions.map((option, i) => (
                  <Button
                    key={i}
                    size="small"
                    onClick={() => handleClarifyOption(option)}
                    style={{ borderRadius: 16 }}
                  >
                    {option}
                  </Button>
                ))}
              </div>
            )}
          </div>
        ) : content ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{content}</ReactMarkdown>
        ) : (
          <Text type="secondary">思考中…</Text>
        )}
        {!isSearchResult && hasSources && (
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
    </article>
  );
}
