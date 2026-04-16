import { Drawer, Typography, Empty, theme, Grid } from 'antd';
import type { Source } from '../types';
import { DRAWER_SM } from '../constants/layout';

const { Text, Paragraph } = Typography;
const { useBreakpoint } = Grid;

interface Props {
  open: boolean;
  sources: Source[];
  selectedSource: Source | null;
  onSelect: (source: Source) => void;
  onClose: () => void;
}

export default function SourcePanel({ open, sources, selectedSource, onSelect, onClose }: Props) {
  const { token } = theme.useToken();
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  return (
    <Drawer
      title="法规来源"
      placement="right"
      size={isMobile ? '100%' : DRAWER_SM}
      open={open}
      onClose={onClose}
    >
      {!selectedSource ? (
        <Empty description="暂无来源" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {sources.map((s, i) => (
            <div
              key={i}
              onClick={() => onSelect(s)}
              style={{
                padding: 12,
                border: `1px solid ${token.colorBorderSecondary}`,
                borderRadius: token.borderRadiusLG,
                cursor: 'pointer',
                background: selectedSource === s ? token.colorPrimaryBg : token.colorBgContainer,
                borderLeft: selectedSource === s ? `3px solid ${token.colorPrimary}` : '3px solid transparent',
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
                style={{ marginTop: 4, marginBottom: 0, fontSize: token.fontSizeSM }}
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
