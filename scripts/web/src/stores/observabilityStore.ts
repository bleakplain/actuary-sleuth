import { create } from 'zustand';
import type { TraceListItem, TraceData } from '../types';
import type { TraceSearchParams } from '../api/observability';
import * as api from '../api/observability';

interface ObservabilityState {
  traceList: TraceListItem[];
  traceTotal: number;
  tracePage: number;
  traceParams: TraceSearchParams;
  selectedTraceId: string | null;
  traceDetail: TraceData | null;
  traceLoading: boolean;

  loadTraces: (params?: TraceSearchParams) => Promise<void>;
  selectTrace: (traceId: string) => void;
  closeDetail: () => void;
  setPage: (page: number) => void;
  deleteTraces: (ids: string[]) => Promise<void>;
}

export const useObservabilityStore = create<ObservabilityState>((set, get) => ({
  traceList: [],
  traceTotal: 0,
  tracePage: 1,
  traceParams: {},
  selectedTraceId: null,
  traceDetail: null,
  traceLoading: false,

  loadTraces: async (params?: TraceSearchParams) => {
    const merged = { ...get().traceParams, ...params, page: params?.page ?? get().tracePage };
    set({ traceParams: merged });
    try {
      const resp = await api.fetchTraces(merged);
      set({ traceList: resp.items, traceTotal: resp.total });
    } catch {
      // 网络错误时不清空已有数据，保留陈旧数据供用户查看
    }
  },

  selectTrace: (traceId: string) => {
    set({ selectedTraceId: traceId, traceLoading: true });
    api.fetchTraceDetail(traceId)
      .then((detail) => {
        if (get().selectedTraceId === traceId) {
          set({ traceDetail: detail, traceLoading: false });
        }
      })
      .catch(() => {
        if (get().selectedTraceId === traceId) {
          set({ traceDetail: null, traceLoading: false });
        }
      });
  },

  closeDetail: () => {
    set({ selectedTraceId: null, traceDetail: null });
  },

  setPage: (page: number) => {
    set({ tracePage: page });
    get().loadTraces({ page });
  },

  deleteTraces: async (ids: string[]) => {
    await api.batchDeleteTraces(ids);
    const { selectedTraceId } = get();
    if (selectedTraceId && ids.includes(selectedTraceId)) {
      get().closeDetail();
    }
    get().loadTraces();
  },
}));
