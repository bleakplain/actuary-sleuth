import ChatPanel from '../components/ChatPanel';

export default function AskPage() {
  return (
    <div style={{ height: 'calc(100vh - var(--header-height) - var(--content-padding) * 2)' }}>
      <ChatPanel />
    </div>
  );
}
