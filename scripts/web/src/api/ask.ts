import client from './client';
import type { Session, Message, Source, Citation, TraceData } from '../types';

interface ChatDoneData {
  session_id: string;
  message_id?: number;
  citations: Citation[];
  sources: Source[];
  faithfulness_score?: number;
  trace?: TraceData;
}

export async function fetchSessions(search?: string): Promise<Session[]> {
  const { data } = await client.get('/api/ask/sessions', {
    params: search ? { search } : undefined,
  });
  return data;
}

export async function fetchMessages(sessionId: string): Promise<Message[]> {
  const { data } = await client.get(`/api/ask/sessions/${sessionId}/messages`);
  return data;
}

export async function deleteSession(sessionId: string): Promise<void> {
  await client.delete(`/api/ask/sessions/${sessionId}`);
}

export async function batchDeleteSessions(ids: string[]): Promise<{ deleted: number }> {
  const { data } = await client.delete('/api/ask/sessions', {
    params: { ids: ids.join(',') },
  });
  return data;
}

interface ClarifyData {
  message: string;
  options: string[];
  session_context: Record<string, unknown>;
}

export function chatSSE(
  req: { question: string; session_id?: string; mode: 'qa' | 'search'; debug?: boolean; skip_clarify?: boolean },
  callbacks: {
    onToken: (token: string) => void;
    onDone: (data: ChatDoneData) => void;
    onError: (err: string) => void;
    onClarify?: (data: ClarifyData) => void;
  },
): AbortController {
  const controller = new AbortController();
  fetch('/api/ask/chat', {
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
      let currentEvent = 'message';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            try {
              const data = JSON.parse(line.slice(5).trim());
              if (currentEvent === 'clarify') {
                callbacks.onClarify?.(data);
                callbacks.onDone({ session_id: '', citations: [], sources: [] });
              } else if (data.type === 'token') {
                callbacks.onToken(data.data);
              } else if (data.type === 'done') {
                callbacks.onDone(data.data);
              } else if (data.type === 'error') {
                callbacks.onError(data.data);
              }
              currentEvent = 'message';
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
  sessionId?: string,
): Promise<{ session_id: string; mode: string; content: string; sources: Source[] }> {
  const { data } = await client.post('/api/ask/chat', {
    question,
    session_id: sessionId,
    mode: 'search',
  });
  return data;
}

export async function fetchTrace(messageId: number): Promise<TraceData> {
  const { data } = await client.get(`/api/ask/messages/${messageId}/trace`);
  return data;
}

export async function deleteMessage(messageId: number): Promise<{ deleted_messages: number }> {
  const { data } = await client.delete(`/api/ask/messages/${messageId}`);
  return data;
}
