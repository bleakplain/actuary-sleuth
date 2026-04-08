import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  fetchSessions,
  fetchMessages,
  deleteSession,
  chatSearch,
  chatSSE,
} from './ask';

// Mock the axios client
vi.mock('./client', () => {
  const mockGet = vi.fn();
  const mockPost = vi.fn();
  const mockDelete = vi.fn();
  return {
    default: { get: mockGet, post: mockPost, delete: mockDelete },
  };
});

// Need to import after mock setup to get the mocked module
import client from './client';

const mockedClient = vi.mocked(client);

describe('ask API', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('fetchSessions', () => {
    it('returns session list', async () => {
      const sessions = [
        { id: 'c1', title: 'test', created_at: '2026-01-01', message_count: 2 },
      ];
      mockedClient.get.mockResolvedValueOnce({ data: sessions });

      const result = await fetchSessions();
      expect(result).toEqual(sessions);
      expect(mockedClient.get).toHaveBeenCalledWith('/api/ask/sessions');
    });
  });

  describe('fetchMessages', () => {
    it('returns messages for a session', async () => {
      const messages = [
        { id: 1, role: 'user', content: 'hello' },
        { id: 2, role: 'assistant', content: 'hi' },
      ];
      mockedClient.get.mockResolvedValueOnce({ data: messages });

      const result = await fetchMessages('c1');
      expect(result).toEqual(messages);
      expect(mockedClient.get).toHaveBeenCalledWith('/api/ask/sessions/c1/messages');
    });
  });

  describe('deleteSession', () => {
    it('calls delete endpoint', async () => {
      mockedClient.delete.mockResolvedValueOnce({});

      await deleteSession('c1');
      expect(mockedClient.delete).toHaveBeenCalledWith('/api/ask/sessions/c1');
    });
  });

  describe('chatSearch', () => {
    it('posts search request and returns result', async () => {
      const searchResult = {
        session_id: 'c1',
        mode: 'search',
        content: '[{"law_name":"保险法"}]',
        sources: [{ law_name: '保险法', article_number: '第一条' }],
      };
      mockedClient.post.mockResolvedValueOnce({ data: searchResult });

      const result = await chatSearch('等待期多久');
      expect(result).toEqual(searchResult);
      expect(mockedClient.post).toHaveBeenCalledWith('/api/ask/chat', {
        question: '等待期多久',
        session_id: undefined,
        mode: 'search',
      });
    });

    it('passes session_id when provided', async () => {
      mockedClient.post.mockResolvedValueOnce({ data: { session_id: 'c1', mode: 'search', content: '', sources: [] } });

      await chatSearch('问题', 'c1');
      expect(mockedClient.post).toHaveBeenCalledWith('/api/ask/chat', {
        question: '问题',
        session_id: 'c1',
        mode: 'search',
      });
    });
  });

  describe('chatSSE', () => {
    it('returns AbortController', () => {
      // Mock fetch to return a ReadableStream
      const mockStream = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('data: {"type":"done","data":{"session_id":"c1","message_id":42,"citations":[],"sources":[]}}\n\n'));
          controller.close();
        },
      });
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ body: mockStream }));

      const controller = chatSSE(
        { question: '测试', mode: 'qa' },
        { onToken: vi.fn(), onDone: vi.fn(), onError: vi.fn() },
      );

      expect(controller).toBeInstanceOf(AbortController);
      vi.unstubAllGlobals();
    });

    it('parses SSE token events and done with message_id', async () => {
      const onToken = vi.fn();
      const onDone = vi.fn();

      const sseData = [
        'data: {"type":"token","data":"你好"}\n',
        'data: {"type":"token","data":"世界"}\n',
        'data: {"type":"done","data":{"session_id":"c1","message_id":42,"citations":[],"sources":[]}}\n\n',
      ].join('');

      const mockStream = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(sseData));
          controller.close();
        },
      });
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ body: mockStream }));

      chatSSE({ question: '测试', mode: 'qa' }, { onToken, onDone, onError: vi.fn() });

      // Wait for stream processing
      await new Promise((r) => setTimeout(r, 100));

      expect(onToken).toHaveBeenCalledWith('你好');
      expect(onToken).toHaveBeenCalledWith('世界');
      expect(onDone).toHaveBeenCalledWith(expect.objectContaining({
        session_id: 'c1',
        message_id: 42,
      }));
      vi.unstubAllGlobals();
    });

    it('calls onError when fetch fails', async () => {
      const onError = vi.fn();
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')));

      chatSSE({ question: '测试', mode: 'qa' }, { onToken: vi.fn(), onDone: vi.fn(), onError });

      await new Promise((r) => setTimeout(r, 100));

      expect(onError).toHaveBeenCalledWith('Network error');
      vi.unstubAllGlobals();
    });
  });
});
