import { Tag } from 'antd';
import type { Citation } from '../types';

interface Props {
  citation: Citation;
  onClick?: (citation: Citation) => void;
}

export default function CitationTag({ citation, onClick }: Props) {
  const displayName = citation.law_name.length > 20
    ? citation.law_name.slice(0, 20) + '…'
    : citation.law_name;

  return (
    <Tag
      color="blue"
      style={{ cursor: onClick ? 'pointer' : 'default', maxWidth: 300 }}
      onClick={() => onClick?.(citation)}
    >
      [{displayName} {citation.article_number}]
    </Tag>
  );
}
