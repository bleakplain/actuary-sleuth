import { create } from 'zustand';
import type { Conversation, Message, Source } from '../types';
import * as askApi from '../api/ask';

let _searchTimer: ReturnType<typeof setTimeout> | null = null;

interface AskState {
  conversations: Conversation[];
  currentConversationId: string | null;
  messages: Message[];
  streaming: boolean;
  currentSources: Source[];
  activeTraceMessageId: number | null;
  traceLoading: boolean;
  debugMode: boolean;
  conversationSearch: string;

  loadConversations: (search?: string) => Promise<void>;
  selectConversation: (id: string) => Promise<void>;
  sendMessage: (question: string, mode: 'qa' | 'search') => void;
  deleteConversation: (id: string) => Promise<void>;
  openTrace: (messageId: number) => void;
  closeTrace: () => void;
  toggleDebugMode: () => void;
  setConversationSearch: (search: string) => void;
  batchDeleteConversations: (ids: string[]) => Promise<void>;
}

export const useAskStore = create<AskState>((set, get) => ({
  conversations: [],
  currentConversationId: null,
  messages: [],
  streaming: false,
  currentSources: [],
  activeTraceMessageId: null,
  traceLoading: false,
  debugMode: false,
  conversationSearch: "",

  loadConversations: async (search?: string) => {
    const conversations = await askApi.fetchConversations(search);
    set({ conversations });
  },

  selectConversation: async (id: string) => {
    set({ currentConversationId: id, currentSources: [], activeTraceMessageId: null, traceLoading: false });
    const messages = await askApi.fetchMessages(id);
    set({ messages });
  },

  sendMessage: (question: string, mode: 'qa' | 'search') => {
    const { currentConversationId, messages } = get();

    const userMsg: Message = {
      id: Date.now(),
      conversation_id: currentConversationId || '',
      role: 'user',
      content: question,
      citations: [],
      sources: [],
      timestamp: new Date().toISOString(),
    };
    const assistantMsg: Message = {
      id: Date.now() + 1,
      conversation_id: currentConversationId || '',
      role: 'assistant',
      content: '',
      citations: [],
      sources: [],
      timestamp: new Date().toISOString(),
    };
    set({ messages: [...messages, userMsg, assistantMsg], streaming: true, currentSources: [], activeTraceMessageId: null, traceLoading: false });

    if (mode === 'search') {
      askApi
        .chatSearch(question, currentConversationId || undefined)
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
          get().loadConversations();
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
      { question, conversation_id: currentConversationId || undefined, mode: 'qa', debug: get().debugMode },
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
            currentConversationId: doneData.conversation_id || currentConversationId,
            currentSources: doneData.sources || [],
            streaming: false,
          }));
          get().loadConversations();
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

  deleteConversation: async (id: string) => {
    await askApi.deleteConversation(id);
    const { currentConversationId } = get();
    if (currentConversationId === id) {
      set({ currentConversationId: null, messages: [], activeTraceMessageId: null, traceLoading: false });
    }
    get().loadConversations();
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

  setConversationSearch: (search: string) => {
    set({ conversationSearch: search });
    if (_searchTimer) clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => {
      get().loadConversations(search);
      _searchTimer = null;
    }, 300);
  },

  batchDeleteConversations: async (ids: string[]) => {
    await askApi.batchDeleteConversations(ids);
    const { currentConversationId } = get();
    if (ids.includes(currentConversationId || "")) {
      set({ currentConversationId: null, messages: [], activeTraceMessageId: null, traceLoading: false });
    }
    get().loadConversations(get().conversationSearch || undefined);
  },

  toggleDebugMode: () => {
    set((s) => ({ debugMode: !s.debugMode }));
  },
}));
