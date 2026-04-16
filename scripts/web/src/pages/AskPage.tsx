import { Grid } from 'antd';
import ChatPanel from '../components/ChatPanel';

export default function AskPage() {
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  return (
    <div style={{
      height: isMobile
        ? 'calc(100vh - 48px - var(--mobile-nav-height) - env(safe-area-inset-bottom, 0px))'
        : 'calc(100vh - var(--header-height) - var(--content-padding) * 2)',
    }}>
      <ChatPanel />
    </div>
  );
}
