import { create } from 'zustand';
import type { Feedback, FeedbackStats, FeedbackActionLog } from '../types';
import * as feedbackApi from '../api/feedback';

interface FeedbackState {
  badcases: Feedback[];
  stats: FeedbackStats | null;
  loading: boolean;
  history: Record<string, FeedbackActionLog[]>;

  loadBadcases: (params?: { status?: string; classified_type?: string }) => Promise<void>;
  loadStats: () => Promise<void>;
  loadHistory: (feedbackId: string) => Promise<void>;
  updateBadcase: (id: string, updates: Record<string, unknown>) => Promise<void>;
  classifyAll: () => Promise<void>;
}

export const useFeedbackStore = create<FeedbackState>((set, get) => ({
  badcases: [],
  stats: null,
  loading: false,
  history: {},

  loadBadcases: async (params) => {
    set({ loading: true });
    const badcases = await feedbackApi.fetchBadcases(params);
    set({ badcases, loading: false });
  },

  loadStats: async () => {
    const stats = await feedbackApi.fetchFeedbackStats();
    set({ stats });
  },

  loadHistory: async (feedbackId) => {
    const logs = await feedbackApi.fetchBadcaseHistory(feedbackId);
    set((state) => ({ history: { ...state.history, [feedbackId]: logs } }));
  },

  updateBadcase: async (id, updates) => {
    await feedbackApi.updateBadcase(id, updates as Parameters<typeof feedbackApi.updateBadcase>[1]);
    get().loadBadcases();
  },

  classifyAll: async () => {
    set({ loading: true });
    await feedbackApi.classifyBadcases();
    get().loadBadcases();
    get().loadStats();
    set({ loading: false });
  },
}));
