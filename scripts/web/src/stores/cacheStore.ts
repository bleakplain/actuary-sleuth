import { create } from 'zustand';
import type { CacheStats, CacheEntry, CacheTrendPoint } from '../types';
import * as api from '../api/observability';

interface CacheState {
  stats: CacheStats | null;
  statsLoading: boolean;
  trendPoints: CacheTrendPoint[];
  trendRangeHours: number;
  trendLoading: boolean;
  entries: CacheEntry[];
  entriesTotal: number;
  entriesPage: number;
  entriesNamespace: string;
  entriesLoading: boolean;

  loadStats: () => Promise<void>;
  loadTrend: (rangeHours?: number) => Promise<void>;
  loadEntries: (namespace?: string, page?: number) => Promise<void>;
  cleanup: () => Promise<number>;
}

export const useCacheStore = create<CacheState>((set, get) => ({
  stats: null,
  statsLoading: false,
  trendPoints: [],
  trendRangeHours: 24,
  trendLoading: false,
  entries: [],
  entriesTotal: 0,
  entriesPage: 1,
  entriesNamespace: '',
  entriesLoading: false,

  loadStats: async () => {
    set({ statsLoading: true });
    try {
      const data = await api.fetchCacheStats();
      if ('status' in data) {
        set({ stats: null, statsLoading: false });
      } else {
        set({ stats: data, statsLoading: false });
      }
    } catch {
      set({ statsLoading: false });
    }
  },

  loadTrend: async (rangeHours?: number) => {
    const hours = rangeHours ?? get().trendRangeHours;
    set({ trendLoading: true, trendRangeHours: hours });
    try {
      const data = await api.fetchCacheTrend(hours);
      set({ trendPoints: data.points, trendLoading: false });
    } catch {
      set({ trendLoading: false });
    }
  },

  loadEntries: async (namespace?: string, page?: number) => {
    const ns = namespace ?? get().entriesNamespace;
    const p = page ?? get().entriesPage;
    set({ entriesLoading: true, entriesNamespace: ns, entriesPage: p });
    try {
      const data = await api.fetchCacheEntries({
        namespace: ns || undefined,
        page: p,
        size: 20,
      });
      set({ entries: data.items, entriesTotal: data.total, entriesLoading: false });
    } catch {
      set({ entriesLoading: false });
    }
  },

  cleanup: async () => {
    const result = await api.cleanupCache();
    get().loadStats();
    get().loadEntries();
    return result.deleted;
  },
}));
