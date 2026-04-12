import { create } from 'zustand';
import type { Session, Message, Source } from '../types';
import * as askApi from '../api/ask';

let _searchTimer: ReturnType<typeof setTimeout> | null = null;

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

  loadSessions: (search?: string) => Promise<void>;
  selectSession: (id: string) => Promise<void>;
  sendMessage: (question: string, mode: 'qa' | 'search') => void;
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

  loadSessions: async (search?: string) => {
    const sessions = await askApi.fetchSessions(search);
    set({ sessions });
  },

  selectSession: async (id: string) => {
    set({ currentSessionId: id, currentSources: [], activeTraceMessageId: null, traceLoading: false });
    const messages = await askApi.fetchMessages(id);
    set({ messages });
  },

  sendMessage: (question: string, mode: 'qa' | 'search') => {
    const { currentSessionId, messages } = get();

    const userMsg: Message = {
      id: Date.now(),
      session_id: currentSessionId || '',
      role: 'user',
      content: question,
      citations: [],
      sources: [],
      timestamp: new Date().toISOString(),
    };
    const assistantMsg: Message = {
      id: Date.now() + 1,
      session_id: currentSessionId || '',
      role: 'assistant',
      content: '',
      citations: [],
      sources: [],
      timestamp: new Date().toISOString(),
    };
    set({ messages: [...messages, userMsg, assistantMsg], streaming: true, currentSources: [], activeTraceMessageId: null, traceLoading: false });

    if (mode === 'search') {
      askApi
        .chatSearch(question, currentSessionId || undefined)
        .then((data) => {
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id
                ? { ...m, content: typeof data.content === 'string' ? data.content : JSON.stringify(data.sources, null, 2) }
                : m,
            ),
            currentSources: data.sources || [],
            streaming: false,
          }));
          get().loadSessions();
        })
        .catch((err: Error) => {
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id ? { ...m, content: `错误: ${err.message}` } : m,
            ),
            streaming: false,
          }));
        });
      return;
    }

    let fullAnswer = '';
    askApi.chatSSE(
      { question, session_id: currentSessionId || undefined, mode: 'qa', debug: get().debugMode },
      {
        onToken: (token) => {
          fullAnswer += token;
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id ? { ...m, content: fullAnswer } : m,
            ),
          }));
        },
        onDone: (doneData) => {
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id
                ? {
                    ...m,
                    id: doneData.message_id ?? m.id,
                    citations: doneData.citations || [],
                    sources: doneData.sources || [],
                    trace: doneData.trace ?? undefined,
                  }
                : m,
            ),
            currentSessionId: doneData.session_id || currentSessionId,
            currentSources: doneData.sources || [],
            streaming: false,
          }));
          get().loadSessions();
        },
        onError: (err) => {
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id ? { ...m, content: `错误: ${err}` } : m,
            ),
            streaming: false,
          }));
        },
      },
    );
  },

  deleteSession: async (id: string) => {
    await askApi.deleteSession(id);
    const { currentSessionId } = get();
    if (currentSessionId === id) {
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
    set({ sessionSearch: search });
    if (_searchTimer) clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => {
      get().loadSessions(search);
      _searchTimer = null;
    }, 300);
  },

  batchDeleteSessions: async (ids: string[]) => {
    await askApi.batchDeleteSessions(ids);
    const { currentSessionId } = get();
    if (ids.includes(currentSessionId || "")) {
      set({ currentSessionId: null, messages: [], activeTraceMessageId: null, traceLoading: false });
    }
    get().loadSessions(get().sessionSearch || undefined);
  },

  toggleDebugMode: () => {
    set((s) => ({ debugMode: !s.debugMode }));
  },
}));
