import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useAskStore } from './askStore';

// Mock the ask API module
vi.mock('../api/ask', () => ({
  fetchSessions: vi.fn(),
  fetchMessages: vi.fn(),
  deleteSession: vi.fn(),
  chatSearch: vi.fn(),
  chatSSE: vi.fn((_req, callbacks) => {
    // Immediately call onDone with message_id for testability
    const ctrl = new AbortController();
    setTimeout(() => {
      callbacks.onDone({
        session_id: 'sess_test',
        message_id: 42,
        citations: [],
        sources: [],
      });
    }, 0);
    return ctrl;
  }),
}));

import * as askApi from '../api/ask';

const mockedFetchSessions = vi.mocked(askApi.fetchSessions);
const mockedFetchMessages = vi.mocked(askApi.fetchMessages);
const mockedDeleteSession = vi.mocked(askApi.deleteSession);
const mockedChatSearch = vi.mocked(askApi.chatSearch);
const mockedChatSSE = vi.mocked(askApi.chatSSE);

describe('askStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset store state between tests
    useAskStore.setState({
      sessions: [],
      currentSessionId: null,
      messages: [],
      streaming: false,
      currentSources: [],
    });
  });

  describe('loadSessions', () => {
    it('loads and sets sessions', async () => {
      const sessions = [
        { id: 'c1', title: 'test', created_at: '2026-01-01', message_count: 2 },
      ];
      mockedFetchSessions.mockResolvedValueOnce(sessions);

      await useAskStore.getState().loadSessions();

      expect(useAskStore.getState().sessions).toEqual(sessions);
    });

    it('handles empty session list', async () => {
      mockedFetchSessions.mockResolvedValueOnce([]);

      await useAskStore.getState().loadSessions();

      expect(useAskStore.getState().sessions).toEqual([]);
    });
  });

  describe('selectSession', () => {
    it('sets current session and loads messages', async () => {
      const messages = [
        { id: 1, role: 'user', content: 'hello', citations: [], sources: [], timestamp: '' },
      ];
      mockedFetchMessages.mockResolvedValueOnce(messages);

      await useAskStore.getState().selectSession('c1');

      const state = useAskStore.getState();
      expect(state.currentSessionId).toBe('c1');
      expect(state.messages).toEqual(messages);
      expect(state.currentSources).toEqual([]);
    });
  });

  describe('sendMessage (search mode)', () => {
    it('adds user and assistant messages, then updates assistant', async () => {
      mockedChatSearch.mockResolvedValueOnce({
        session_id: 'c1',
        mode: 'search',
        content: '搜索结果',
        sources: [{ law_name: '保险法' }],
      });

      useAskStore.getState().sendMessage('测试问题', 'search');

      // Should have user + assistant messages immediately
      const state1 = useAskStore.getState();
      expect(state1.messages).toHaveLength(2);
      expect(state1.messages[0].role).toBe('user');
      expect(state1.messages[1].role).toBe('assistant');
      expect(state1.streaming).toBe(true);

      // Wait for search to complete
      await new Promise((r) => setTimeout(r, 50));

      const state2 = useAskStore.getState();
      expect(state2.streaming).toBe(false);
      expect(state2.messages[1].content).toBe('搜索结果');
      expect(state2.currentSources).toHaveLength(1);
    });

    it('handles search error', async () => {
      mockedChatSearch.mockRejectedValueOnce(new Error('检索失败'));

      useAskStore.getState().sendMessage('测试', 'search');
      await new Promise((r) => setTimeout(r, 50));

      const state = useAskStore.getState();
      expect(state.streaming).toBe(false);
      expect(state.messages[1].content).toContain('错误');
    });
  });

  describe('sendMessage (qa mode — SSE message_id)', () => {
    it('updates assistant message id from temp to real DB id after SSE done', async () => {
      mockedFetchSessions.mockResolvedValueOnce([]);

      useAskStore.getState().sendMessage('测试问题', 'qa');

      // Immediately after sending, assistant has temp ID (Date.now() + 1)
      const stateBefore = useAskStore.getState();
      expect(stateBefore.messages).toHaveLength(2);
      const tempId = stateBefore.messages[1].id;
      expect(typeof tempId).toBe('number');
      expect(tempId).toBeGreaterThan(Date.now() - 1000);

      // Wait for SSE onDone callback
      await new Promise((r) => setTimeout(r, 50));

      const stateAfter = useAskStore.getState();
      expect(stateAfter.streaming).toBe(false);
      // Assistant message id should now be the real DB id (42)
      expect(stateAfter.messages[1].id).toBe(42);
      // session_id should be updated
      expect(stateAfter.currentSessionId).toBe('sess_test');
    });
  });

  describe('deleteSession', () => {
    it('deletes and clears if current', async () => {
      mockedDeleteSession.mockResolvedValueOnce(undefined);
      mockedFetchSessions.mockResolvedValueOnce([]);

      useAskStore.setState({ currentSessionId: 'c1', messages: [{ id: 1 } as any] });
      await useAskStore.getState().deleteSession('c1');

      const state = useAskStore.getState();
      expect(state.currentSessionId).toBeNull();
      expect(state.messages).toEqual([]);
      expect(mockedDeleteSession).toHaveBeenCalledWith('c1');
    });

    it('keeps current session if deleting another', async () => {
      mockedDeleteSession.mockResolvedValueOnce(undefined);
      mockedFetchSessions.mockResolvedValueOnce([]);

      useAskStore.setState({ currentSessionId: 'c2', messages: [{ id: 1 } as any] });
      await useAskStore.getState().deleteSession('c1');

      expect(useAskStore.getState().currentSessionId).toBe('c2');
    });
  });
});
