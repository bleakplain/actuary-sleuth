import React, { useRef, useEffect, useState, useCallback } from 'react';
import { Input, Button, Radio, Popconfirm, Switch } from 'antd';
import { SendOutlined, DeleteOutlined, CloseOutlined, BugOutlined } from '@ant-design/icons';
import MessageBubble from './MessageBubble';
import SourcePanel from './SourcePanel';
import TracePanel from './TracePanel';
import { useAskStore } from '../stores/askStore';
import type { Source } from '../types';

const { TextArea } = Input;

function formatConvTime(ts: string): string {
  if (!ts) return '';
  const date = new Date(ts.replace(' ', 'T'));
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diffDays = Math.floor((today.getTime() - target.getTime()) / 86400000);
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  const time = `${hh}:${mm}`;

  if (diffDays === 0) return time;
  if (diffDays === 1) return `昨天 ${time}`;
  if (date.getFullYear() === now.getFullYear())
    return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${time}`;
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

const DEFAULT_TRACE_WIDTH = 600;
const MIN_TRACE_WIDTH = 360;
const MAX_TRACE_WIDTH = 800;

export default function ChatPanel() {
  const [input, setInput] = React.useState('');
  const [mode, setMode] = React.useState<'qa' | 'search'>('qa');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const {
    messages,
    streaming,
    currentConversationId,
    conversations,
    sendMessage,
    selectConversation,
    deleteConversation,
    loadConversations,
    activeTraceMessageId,
    traceLoading,
    closeTrace,
    debugMode,
    toggleDebugMode,
  } = useAskStore();

  const [sourcePanelOpen, setSourcePanelOpen] = React.useState(false);
  const [selectedSource, setSelectedSource] = React.useState<Source | null>(null);
  const [panelSources, setPanelSources] = React.useState<Source[]>([]);
  const [traceWidth, setTraceWidth] = useState(DEFAULT_TRACE_WIDTH);
  const [dragging, setDragging] = useState(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(0);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragStartX.current = e.clientX;
    dragStartWidth.current = traceWidth;
    setDragging(true);

    const handleDragMove = (ev: MouseEvent) => {
      const delta = dragStartX.current - ev.clientX;
      const newWidth = Math.min(MAX_TRACE_WIDTH, Math.max(MIN_TRACE_WIDTH, dragStartWidth.current + delta));
      setTraceWidth(newWidth);
    };

    const handleDragEnd = () => {
      setDragging(false);
      document.removeEventListener('mousemove', handleDragMove);
      document.removeEventListener('mouseup', handleDragEnd);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.addEventListener('mousemove', handleDragMove);
    document.addEventListener('mouseup', handleDragEnd);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [traceWidth]);

  const handleSend = () => {
    const q = input.trim();
    if (!q || streaming) return;
    setInput('');
    sendMessage(q, mode);
  };

  const handleCitationClick = (source: Source, messageSources: Source[]) => {
    setSelectedSource(source);
    setPanelSources(messageSources);
    setSourcePanelOpen(true);
  };

  const activeMessage = activeTraceMessageId
    ? messages.find((m) => m.id === activeTraceMessageId)
    : null;

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
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  fontSize: 13,
                }}
              >
                {conv.title || conv.id}
              </div>
              <div style={{ fontSize: 11, color: '#bfbfbf', marginTop: 2 }}>
                {formatConvTime(conv.created_at)}
                {conv.message_count > 0 && ` · ${conv.message_count} 条`}
              </div>
            </div>
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

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div style={{ flex: 1, overflow: 'auto', padding: '16px 24px' }}>
          {messages.length === 0 && (
            <div style={{ textAlign: 'center', color: '#999', marginTop: 100 }}>
              <div style={{ fontSize: 24, marginBottom: 8 }}>法规问答</div>
              <div>输入问题，检索保险法规并获取带引用的回答</div>
            </div>
          )}
          {messages.map((msg) => (
            <div key={msg.id}>
              <MessageBubble message={msg} streaming={streaming} onCitationClick={handleCitationClick} />
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        <div style={{ borderTop: '1px solid #f0f0f0', padding: '12px 24px' }}>
          <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Radio.Group
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              size="small"
            >
              <Radio.Button value="qa">智能问答</Radio.Button>
              <Radio.Button value="search">精确检索</Radio.Button>
            </Radio.Group>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: debugMode ? '#1677ff' : '#8c8c8c' }}>
              <BugOutlined />
              <span>调试</span>
              <Switch size="small" checked={debugMode} onChange={toggleDebugMode} />
            </span>
          </div>
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

      {activeTraceMessageId != null && (
        <>
          {/* Drag handle */}
          <div
            onMouseDown={handleDragStart}
            style={{
              width: 4,
              cursor: 'col-resize',
              background: dragging ? '#1677ff' : 'transparent',
              borderLeft: '1px solid #e8e8e8',
              transition: dragging ? 'none' : 'background 0.2s',
              position: 'relative',
              flexShrink: 0,
            }}
            onMouseEnter={(e) => {
              if (!dragging) {
                (e.currentTarget as HTMLDivElement).style.background = '#d9d9d9';
              }
            }}
            onMouseLeave={(e) => {
              if (!dragging) {
                (e.currentTarget as HTMLDivElement).style.background = 'transparent';
              }
            }}
          >
            {/* Center grip indicator */}
            <div
              style={{
                position: 'absolute',
                top: '50%',
                left: -1,
                transform: 'translateY(-50%)',
                width: 6,
                height: 32,
                borderRadius: 3,
                background: dragging ? '#1677ff' : '#d9d9d9',
                opacity: 0.6,
                transition: dragging ? 'none' : 'opacity 0.2s',
              }}
            />
          </div>

          {/* Right trace panel */}
          <div
            style={{
              width: traceWidth,
              flexShrink: 0,
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              background: '#fff',
            }}
          >
            <div
              style={{
                padding: '10px 16px',
                borderBottom: '1px solid #f0f0f0',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <span style={{ fontWeight: 600, fontSize: 14, color: '#262626' }}>
                调试
              </span>
              <Button
                type="text"
                size="small"
                icon={<CloseOutlined />}
                onClick={closeTrace}
                style={{ color: '#8c8c8c' }}
              />
            </div>
            <div style={{ flex: 1, overflow: 'auto' }}>
              <TracePanel
                trace={activeMessage?.trace ?? null}
                loading={traceLoading}
              />
            </div>
          </div>
        </>
      )}

      <SourcePanel
        open={sourcePanelOpen}
        sources={panelSources}
        selectedSource={selectedSource}
        onSelect={setSelectedSource}
        onClose={() => setSourcePanelOpen(false)}
      />
    </div>
  );
}
