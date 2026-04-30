import { create } from 'zustand';
import client from '../api/client';

interface FeedbackStats {
  total: number;
  up_count: number;
  down_count: number;
  satisfaction_rate: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  by_risk: Record<string, number>;
}

interface AutoQualityDetails {
  faithfulness?: number;
  retrieval_relevance?: number;
  completeness?: number;
}

interface Badcase {
  id: string;
  session_id: string;
  user_question: string | null;
  assistant_answer: string | null;
  rating: 'up' | 'down';
  reason: string | null;
  correction: string | null;
  source_channel: string;
  auto_quality_score: number | null;
  auto_quality_details: AutoQualityDetails | null;
  classified_type: string | null;
  classified_reason: string | null;
  classified_fix_direction: string | null;
  compliance_risk: number;
  status: string;
  created_at: string;
}

interface FeedbackState {
  badcases: Badcase[];
  stats: FeedbackStats | null;
  loading: boolean;

  loadBadcases: (params?: { status?: string }) => Promise<void>;
  loadStats: () => Promise<void>;
  classifyAll: () => Promise<void>;
  updateBadcase: (id: string, updates: { status?: string; classified_type?: string }) => Promise<void>;
}

export const useFeedbackStore = create<FeedbackState>((set) => ({
  badcases: [],
  stats: null,
  loading: false,

  loadBadcases: async (params?: { status?: string }) => {
    set({ loading: true });
    try {
      const { data } = await client.get('/api/feedback/badcases', { params });
      set({ badcases: data, loading: false });
    } catch (err: unknown) {
      set({ loading: false });
      if (import.meta.env.DEV) console.error('Failed to load badcases:', err instanceof Error ? err.message : String(err));
    }
  },

  loadStats: async () => {
    try {
      const { data } = await client.get('/api/feedback/stats');
      set({ stats: data });
    } catch (err: unknown) {
      if (import.meta.env.DEV) console.error('Failed to load feedback stats:', err instanceof Error ? err.message : String(err));
    }
  },

  classifyAll: async () => {
    set({ loading: true });
    try {
      await client.post('/api/feedback/badcases/classify_all');
    } catch (err: unknown) {
      set({ loading: false });
      throw err;
    }
    // 重新加载数据
    const { data } = await client.get('/api/feedback/badcases');
    set({ badcases: data, loading: false });
  },

  updateBadcase: async (id: string, updates: { status?: string; classified_type?: string }) => {
    await client.patch(`/api/feedback/badcases/${id}`, updates);
    // 重新加载以获取最新状态
    const { data } = await client.get('/api/feedback/badcases');
    set({ badcases: data });
  },
}));
