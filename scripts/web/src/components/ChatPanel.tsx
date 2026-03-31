import React, { useRef, useEffect } from 'react';
import { Input, Button, Radio, Space, Popconfirm } from 'antd';
import { SendOutlined, DeleteOutlined } from '@ant-design/icons';
import MessageBubble from './MessageBubble';
import SourcePanel from './SourcePanel';
import { useAskStore } from '../stores/askStore';
import type { Citation, Source } from '../types';

const { TextArea } = Input;

export default function ChatPanel() {
  const [input, setInput] = React.useState('');
  const [mode, setMode] = React.useState<'qa' | 'search'>('qa');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const {
    messages,
    streaming,
    currentSources,
    currentConversationId,
    conversations,
    sendMessage,
    selectConversation,
    deleteConversation,
    loadConversations,
  } = useAskStore();

  const [sourcePanelOpen, setSourcePanelOpen] = React.useState(false);
  const [selectedSource, setSelectedSource] = React.useState<Source | null>(null);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    const q = input.trim();
    if (!q || streaming) return;
    setInput('');
    sendMessage(q, mode);
  };

  const handleCitationClick = (citation: Citation) => {
    const source = currentSources.find((_, i) => i === citation.source_idx);
    if (source) {
      setSelectedSource(source);
      setSourcePanelOpen(true);
    }
  };

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      <div
        style={{
          width: 220,
          borderRight: '1px solid #f0f0f0',
          overflow: 'auto',
        }}
      >
        <div style={{ padding: '8px 12px', fontWeight: 600, fontSize: 14 }}>
          对话历史
        </div>
        {conversations.map((conv) => (
          <div
            key={conv.id}
            onClick={() => selectConversation(conv.id)}
            style={{
              padding: '8px 12px',
              cursor: 'pointer',
              background: currentConversationId === conv.id ? '#e6f4ff' : '#fff',
              borderBottom: '1px solid #f5f5f5',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <span
              style={{
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                flex: 1,
                fontSize: 13,
              }}
            >
              {conv.title || conv.id}
            </span>
            <Popconfirm
              title="确定删除？"
              onConfirm={(e) => {
                e?.stopPropagation();
                deleteConversation(conv.id);
              }}
              onCancel={(e) => e?.stopPropagation()}
            >
              <Button
                type="text"
                size="small"
                icon={<DeleteOutlined />}
                onClick={(e) => e.stopPropagation()}
                style={{ color: '#999' }}
              />
            </Popconfirm>
          </div>
        ))}
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1, overflow: 'auto', padding: '16px 24px' }}>
          {messages.length === 0 && (
            <div style={{ textAlign: 'center', color: '#999', marginTop: 100 }}>
              <div style={{ fontSize: 24, marginBottom: 8 }}>法规问答</div>
              <div>输入问题，检索保险法规并获取带引用的回答</div>
            </div>
          )}
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} onCitationClick={handleCitationClick} />
          ))}
          <div ref={messagesEndRef} />
        </div>

        <div style={{ borderTop: '1px solid #f0f0f0', padding: '12px 24px' }}>
          <Space style={{ marginBottom: 8 }}>
            <Radio.Group
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              size="small"
            >
              <Radio.Button value="qa">智能问答</Radio.Button>
              <Radio.Button value="search">精确检索</Radio.Button>
            </Radio.Group>
          </Space>
          <div style={{ display: 'flex', gap: 8 }}>
            <TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="输入法规相关问题..."
              autoSize={{ minRows: 1, maxRows: 4 }}
              disabled={streaming}
              style={{ flex: 1 }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              loading={streaming}
              disabled={!input.trim()}
            />
          </div>
        </div>
      </div>

      <SourcePanel
        open={sourcePanelOpen}
        sources={currentSources}
        selectedSource={selectedSource}
        onSelect={setSelectedSource}
        onClose={() => setSourcePanelOpen(false)}
      />
    </div>
  );
}
