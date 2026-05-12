import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useAskStore } from './askStore';

// Mock the ask API module
vi.mock('../api/ask', () => ({
  fetchSessions: vi.fn(),
  fetchMessages: vi.fn(),
  deleteSession: vi.fn(),
  chatSSE: vi.fn((_req, callbacks) => {
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

describe('askStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

  describe('sendMessage', () => {
    it('updates assistant message id from temp to real DB id after SSE done', async () => {
      mockedFetchSessions.mockResolvedValueOnce([]);

      useAskStore.getState().sendMessage('测试问题');

      const stateBefore = useAskStore.getState();
      expect(stateBefore.messages).toHaveLength(2);
      const tempId = stateBefore.messages[1].id;
      expect(typeof tempId).toBe('number');
      expect(tempId).toBeGreaterThan(Date.now() - 1000);

      await new Promise((r) => setTimeout(r, 50));

      const stateAfter = useAskStore.getState();
      expect(stateAfter.streaming).toBe(false);
      expect(stateAfter.messages[1].id).toBe(42);
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
