import { Typography } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import CitationTag from './CitationTag';
import FeedbackButtons from './FeedbackButtons';
import type { Message, Citation, Source } from '../types';

const { Text } = Typography;

interface Props {
  message: Message;
  onCitationClick?: (source: Source, messageSources: Source[]) => void;
}

export default function MessageBubble({ message, onCitationClick }: Props) {
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
            background: '#1677ff',
            color: '#fff',
            padding: '8px 16px',
            borderRadius: 12,
            borderBottomRightRadius: 4,
          }}
        >
          {message.content}
        </div>
      </div>
    );
  }

  const content = message.content || '';
  const hasSources = message.sources && message.sources.length > 0;

  return (
    <div style={{ marginBottom: 16 }}>
      <div
        style={{
          maxWidth: '85%',
          background: '#f5f5f5',
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
        {message.role === 'assistant' && (
          <FeedbackButtons messageId={message.id} />
        )}
      </div>
    </div>
  );
}
