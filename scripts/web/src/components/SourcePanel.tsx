import { Drawer, Typography, Empty } from 'antd';
import type { Source } from '../types';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  sources: Source[];
  selectedSource: Source | null;
  onSelect: (source: Source) => void;
  onClose: () => void;
}

export default function SourcePanel({ open, sources, selectedSource, onSelect, onClose }: Props) {
  return (
    <Drawer
      title="法规来源"
      placement="right"
      width={420}
      open={open}
      onClose={onClose}
    >
      {sources.length === 0 ? (
        <Empty description="暂无来源" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {sources.map((s, i) => (
            <div
              key={i}
              onClick={() => onSelect(s)}
              style={{
                padding: 12,
                border: '1px solid #f0f0f0',
                borderRadius: 8,
                cursor: 'pointer',
                background: selectedSource === s ? '#e6f4ff' : '#fff',
                borderLeft: selectedSource === s ? '3px solid #1677ff' : '3px solid transparent',
              }}
            >
              <Text strong>
                [{i + 1}] {s.law_name}
              </Text>
              {s.article_number && (
                <Text type="secondary" style={{ marginLeft: 8 }}>
                  {s.article_number}
                </Text>
              )}
              <Paragraph
                ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}
                style={{ marginTop: 4, marginBottom: 0, fontSize: 13 }}
              >
                {s.content}
              </Paragraph>
            </div>
          ))}
        </div>
      )}
    </Drawer>
  );
}
