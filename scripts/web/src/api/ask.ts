import client from './client';
import type { Conversation, Message, Source, Citation, TraceData } from '../types';

interface ChatDoneData {
  conversation_id: string;
  message_id?: number;
  citations: Citation[];
  sources: Source[];
  faithfulness_score?: number;
  trace?: TraceData;
}

export async function fetchConversations(): Promise<Conversation[]> {
  const { data } = await client.get('/api/ask/conversations');
  return data;
}

export async function fetchMessages(conversationId: string): Promise<Message[]> {
  const { data } = await client.get(`/api/ask/conversations/${conversationId}/messages`);
  return data;
}

export async function deleteConversation(conversationId: string): Promise<void> {
  await client.delete(`/api/ask/conversations/${conversationId}`);
}

export function chatSSE(
  req: { question: string; conversation_id?: string; mode: 'qa' | 'search' },
  callbacks: {
    onToken: (token: string) => void;
    onDone: (data: ChatDoneData) => void;
    onError: (err: string) => void;
  },
): AbortController {
  const controller = new AbortController();
  const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

  fetch(`${API_BASE}/api/ask/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal: controller.signal,
  })
    .then(async (res) => {
      const reader = res.body?.getReader();
      if (!reader) throw new Error('No response body');
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data:')) {
            try {
              const event = JSON.parse(line.slice(5).trim());
              if (event.type === 'token') callbacks.onToken(event.data);
              else if (event.type === 'done') callbacks.onDone(event.data);
              else if (event.type === 'error') callbacks.onError(event.data);
            } catch {
              // skip malformed lines
            }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') callbacks.onError(err.message);
    });

  return controller;
}

export async function chatSearch(
  question: string,
  conversationId?: string,
): Promise<{ conversation_id: string; mode: string; content: string; sources: Source[] }> {
  const { data } = await client.post('/api/ask/chat', {
    question,
    conversation_id: conversationId,
    mode: 'search',
  });
  return data;
}

export async function fetchTrace(messageId: number): Promise<TraceData> {
  const { data } = await client.get(`/api/ask/messages/${messageId}/trace`);
  return data;
}
