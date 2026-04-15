import React, { useRef, useEffect, useState, useCallback } from 'react';
import { Input, Button, Radio, Popconfirm, Switch, theme } from 'antd';
import { SendOutlined, CloseOutlined, BugOutlined, SearchOutlined } from '@ant-design/icons';
import MessageBubble from './MessageBubble';
import SourcePanel from './SourcePanel';
import TracePanel from './TracePanel';
import { useAskStore } from '../stores/askStore';
import type { Source } from '../types';

const { TextArea } = Input;

const DEFAULT_TRACE_WIDTH = 520;
const MIN_TRACE_WIDTH = 360;
const MAX_TRACE_WIDTH = 800;

export default function ChatPanel() {
  const { token } = theme.useToken();
  const [input, setInput] = React.useState('');
  const [mode, setMode] = React.useState<'qa' | 'search'>('qa');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const {
    messages,
    streaming,
    currentSessionId,
    sessions,
    sendMessage,
    selectSession,
    deleteSession,
    loadSessions,
    activeTraceMessageId,
    traceLoading,
    closeTrace,
    debugMode,
    toggleDebugMode,
    sessionSearch,
    setSessionSearch,
  } = useAskStore();

  const [sourcePanelOpen, setSourcePanelOpen] = React.useState(false);
  const [selectedSource, setSelectedSource] = React.useState<Source | null>(null);
  const [panelSources, setPanelSources] = React.useState<Source[]>([]);
  const [traceWidth, setTraceWidth] = useState(DEFAULT_TRACE_WIDTH);
  const [dragging, setDragging] = useState(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(0);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

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
          borderRight: `1px solid ${token.colorBorderSecondary}`,
          overflow: 'auto',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div className="section-header">
          对话历史
        </div>
        <div style={{ padding: '0 8px 8px' }}>
          <Input
            placeholder="搜索会话..."
            prefix={<SearchOutlined style={{ color: token.colorTextQuaternary }} />}
            size="small"
            allowClear
            value={sessionSearch}
            onChange={(e) => setSessionSearch(e.target.value)}
          />
        </div>
        <div style={{ flex: 1, overflow: 'auto' }}>
          {sessions.map((session) => (
            <div
              key={session.id}
              onClick={() => selectSession(session.id)}
              className="flex-between"
              style={{
                padding: '8px 12px',
                cursor: 'pointer',
                background: currentSessionId === session.id ? token.colorPrimaryBg : token.colorBgContainer,
                borderBottom: `1px solid ${token.colorBorderSecondary}`,
              }}
            >
              <span
                style={{
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  flex: 1,
                  fontSize: 13,
                  color: token.colorText,
                }}
              >
                {session.title || session.id}
              </span>
              <Popconfirm
                title="确定删除？"
                onConfirm={(e) => {
                  e?.stopPropagation();
                  deleteSession(session.id);
                }}
                onCancel={(e) => e?.stopPropagation()}
              >
                <Button
                  type="text"
                  size="small"
                  icon={<CloseOutlined />}
                  onClick={(e) => e.stopPropagation()}
                  onMouseDown={(e) => e.stopPropagation()}
                  style={{ color: token.colorTextTertiary }}
                />
              </Popconfirm>
            </div>
          ))}
        </div>
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div style={{ flex: 1, overflow: 'auto', padding: '16px 24px' }}>
          {messages.length === 0 && (
            <div className="empty-state" style={{ marginTop: 100 }}>
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

        <div style={{ borderTop: `1px solid ${token.colorBorderSecondary}`, padding: '12px 24px' }}>
          <div className="flex-between" style={{ marginBottom: 8 }}>
            <Radio.Group
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              size="small"
            >
              <Radio.Button value="qa">智能问答</Radio.Button>
              <Radio.Button value="search">精确检索</Radio.Button>
            </Radio.Group>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: debugMode ? token.colorPrimary : token.colorTextTertiary }}>
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
              background: dragging ? token.colorPrimary : 'transparent',
              borderLeft: `1px solid ${token.colorBorderSecondary}`,
              transition: dragging ? 'none' : 'background 0.2s',
              position: 'relative',
              flexShrink: 0,
            }}
            onMouseEnter={(e) => {
              if (!dragging) {
                (e.currentTarget as HTMLDivElement).style.background = token.colorBorder;
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
                borderRadius: 4,
                background: dragging ? token.colorPrimary : token.colorBorder,
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
              background: token.colorBgContainer,
            }}
          >
            <div
              className="section-header flex-between"
              style={{
                padding: '10px 16px',
                borderBottom: `1px solid ${token.colorBorderSecondary}`,
              }}
            >
              <span style={{ fontWeight: token.fontWeightStrong, fontSize: 14, color: token.colorText }}>
                调试
              </span>
              <Button
                type="text"
                size="small"
                icon={<CloseOutlined />}
                onClick={closeTrace}
                style={{ color: token.colorTextTertiary }}
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
