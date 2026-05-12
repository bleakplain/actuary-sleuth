import { create } from 'zustand';
import type { Session, Message, Source } from '../types';
import * as askApi from '../api/ask';

// 生成客户端临时 ID（递减负数，避免与服务端 ID 冲突）
let _nextTempId = -1;
function nextTempId(): number {
  return _nextTempId--;
}

interface AskState {
  sessions: Session[];
  currentSessionId: string | null;
  messages: Message[];
  streaming: boolean;
  currentSources: Source[];
  activeTraceMessageId: number | null;
  traceLoading: boolean;
  debugMode: boolean;
  sessionSearch: string;
  abortController: AbortController | null;
  requestSequence: number;
  searchTimer: ReturnType<typeof setTimeout> | null;

  loadSessions: (search?: string) => Promise<void>;
  selectSession: (id: string) => Promise<void>;
  sendMessage: (question: string) => void;
  abortStreaming: () => void;
  deleteSession: (id: string) => Promise<void>;
  deleteMessage: (messageId: number) => Promise<void>;
  openTrace: (messageId: number) => void;
  closeTrace: () => void;
  toggleDebugMode: () => void;
  setSessionSearch: (search: string) => void;
  batchDeleteSessions: (ids: string[]) => Promise<void>;
}

export const useAskStore = create<AskState>((set, get) => ({
  sessions: [],
  currentSessionId: null,
  messages: [],
  streaming: false,
  currentSources: [],
  activeTraceMessageId: null,
  traceLoading: false,
  debugMode: false,
  sessionSearch: "",
  abortController: null,
  requestSequence: 0,
  searchTimer: null,

  loadSessions: async (search?: string) => {
    const sessions = await askApi.fetchSessions(search);
    set({ sessions });
  },

  selectSession: async (id: string) => {
    get().abortStreaming();
    set({ currentSessionId: id, currentSources: [], activeTraceMessageId: null, traceLoading: false });
    const messages = await askApi.fetchMessages(id);
    set({ messages });
  },

  abortStreaming: () => {
    const { abortController } = get();
    if (abortController) {
      abortController.abort();
      set({ abortController: null, streaming: false });
    }
  },

  sendMessage: (question: string) => {
    const { currentSessionId, messages, abortController } = get();

    // 取消之前的请求
    if (abortController) {
      abortController.abort();
    }

    const currentSequence = get().requestSequence + 1;
    set({ requestSequence: currentSequence });

    const userMsg: Message = {
      id: nextTempId(),
      session_id: currentSessionId || '',
      role: 'user',
      content: question,
      citations: [],
      sources: [],
      timestamp: new Date().toISOString(),
    };
    const assistantMsg: Message = {
      id: nextTempId(),
      session_id: currentSessionId || '',
      role: 'assistant',
      content: '',
      citations: [],
      sources: [],
      timestamp: new Date().toISOString(),
    };
    set({ messages: [...messages, userMsg, assistantMsg], streaming: true, currentSources: [], activeTraceMessageId: null, traceLoading: false });

    let fullAnswer = '';
    const controller = askApi.chatSSE(
      { question, session_id: currentSessionId || undefined, debug: get().debugMode },
      {
        onToken: (token) => {
          if (get().requestSequence !== currentSequence) return;
          fullAnswer += token;
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id ? { ...m, content: fullAnswer } : m,
            ),
          }));
        },
        onDone: (doneData) => {
          if (get().requestSequence !== currentSequence) return;
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id
                ? {
                    ...m,
                    id: doneData.message_id ?? m.id,
                    citations: doneData.citations || [],
                    sources: doneData.sources || [],
                    trace: doneData.trace ?? null,
                  }
                : m,
            ),
            currentSessionId: doneData.session_id || currentSessionId,
            currentSources: doneData.sources || [],
            streaming: false,
            abortController: null,
          }));
          get().loadSessions();
        },
        onError: (err) => {
          if (get().requestSequence !== currentSequence) return;
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id ? { ...m, content: `错误: ${err}` } : m,
            ),
            streaming: false,
            abortController: null,
          }));
        },
        onClarify: (clarifyData) => {
          if (get().requestSequence !== currentSequence) return;
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id
                ? {
                    ...m,
                    content: clarifyData.message,
                    clarificationOptions: clarifyData.options,
                    needsClarification: true,
                  }
                : m,
            ),
            streaming: false,
            abortController: null,
          }));
        },
      },
    );
    set({ abortController: controller });
  },

  deleteSession: async (id: string) => {
    await askApi.deleteSession(id);
    const { currentSessionId } = get();
    if (currentSessionId === id) {
      get().abortStreaming();
      set({ currentSessionId: null, messages: [], activeTraceMessageId: null, traceLoading: false });
    }
    get().loadSessions();
  },

  deleteMessage: async (messageId: number) => {
    const { messages } = get();
    const msg = messages.find((m) => m.id === messageId);
    if (!msg) return;
    await askApi.deleteMessage(messageId);
    const idsToRemove = new Set([messageId]);
    if (msg.role === 'user') {
      const idx = messages.indexOf(msg);
      const next = messages[idx + 1];
      if (next && next.role === 'assistant') {
        idsToRemove.add(next.id);
      }
    }
    set((s) => ({
      messages: s.messages.filter((m) => !idsToRemove.has(m.id)),
      activeTraceMessageId: idsToRemove.has(s.activeTraceMessageId ?? -1) ? null : s.activeTraceMessageId,
    }));
    get().loadSessions();
  },

  openTrace: (messageId: number) => {
    const { messages, traceLoading, activeTraceMessageId } = get();
    if (activeTraceMessageId === messageId) {
      set({ activeTraceMessageId: null });
      return;
    }
    set({ activeTraceMessageId: messageId });
    const msg = messages.find((m) => m.id === messageId);
    if (msg?.trace) return;
    if (traceLoading) return;
    set({ traceLoading: true });
    askApi.fetchTrace(messageId)
      .then((trace) => {
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === messageId ? { ...m, trace } : m,
          ),
          traceLoading: false,
        }));
      })
      .catch(() => {
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === messageId ? { ...m, trace: null } : m,
          ),
          traceLoading: false,
        }));
      });
  },

  closeTrace: () => {
    set({ activeTraceMessageId: null });
  },

  setSessionSearch: (search: string) => {
    const { searchTimer } = get();
    if (searchTimer) clearTimeout(searchTimer);
    set({ sessionSearch: search });
    const timer = setTimeout(() => {
      if (get().sessionSearch === search) {
        get().loadSessions(search);
      }
    }, 300);
    set({ searchTimer: timer });
  },

  batchDeleteSessions: async (ids: string[]) => {
    await askApi.batchDeleteSessions(ids);
    const { currentSessionId } = get();
    if (ids.includes(currentSessionId || "")) {
      get().abortStreaming();
      set({ currentSessionId: null, messages: [], activeTraceMessageId: null, traceLoading: false });
    }
    get().loadSessions(get().sessionSearch || undefined);
  },

  toggleDebugMode: () => {
    set((s) => ({ debugMode: !s.debugMode }));
  },
}));