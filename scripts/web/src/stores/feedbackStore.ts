import { create } from 'zustand';
import type { Feedback, FeedbackStats } from '../types';
import * as feedbackApi from '../api/feedback';

interface FeedbackState {
  badcases: Feedback[];
  stats: FeedbackStats | null;
  loading: boolean;

  loadBadcases: (params?: { status?: string; classified_type?: string }) => Promise<void>;
  loadStats: () => Promise<void>;
  updateBadcase: (id: string, updates: Record<string, unknown>) => Promise<void>;
  classifyAll: () => Promise<void>;
}

export const useFeedbackStore = create<FeedbackState>((set, get) => ({
  badcases: [],
  stats: null,
  loading: false,

  loadBadcases: async (params) => {
    set({ loading: true });
    const badcases = await feedbackApi.fetchBadcases(params);
    set({ badcases, loading: false });
  },

  loadStats: async () => {
    const stats = await feedbackApi.fetchFeedbackStats();
    set({ stats });
  },

  updateBadcase: async (id, updates) => {
    await feedbackApi.updateBadcase(id, updates as Parameters<typeof feedbackApi.updateBadcase>[1]);
    get().loadBadcases();
  },

  classifyAll: async () => {
    set({ loading: true });
    const res = await fetch('/api/feedback/badcases/classify', {
      method: 'POST',
    });
    await res.json();
    get().loadBadcases();
    get().loadStats();
    set({ loading: false });
  },
}));
