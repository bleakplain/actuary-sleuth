import { Tag } from 'antd';
import type { Citation } from '../types';

interface Props {
  citation: Citation;
  onClick?: (citation: Citation) => void;
}

export default function CitationTag({ citation, onClick }: Props) {
  return (
    <Tag
      color="blue"
      style={{ cursor: onClick ? 'pointer' : 'default' }}
      onClick={() => onClick?.(citation)}
    >
      [{citation.law_name} {citation.article_number}]
    </Tag>
  );
}
