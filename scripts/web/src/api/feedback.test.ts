import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  submitFeedback,
  fetchBadcases,
  fetchBadcase,
  updateBadcase,
  fetchFeedbackStats,
} from './feedback';

// Mock the axios client
vi.mock('./client', () => {
  const mockGet = vi.fn();
  const mockPost = vi.fn();
  const mockPut = vi.fn();
  return {
    default: { get: mockGet, post: mockPost, put: mockPut },
  };
});

import client from './client';

const mockedClient = vi.mocked(client);

describe('feedback API', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('submitFeedback', () => {
    it('posts feedback and returns result', async () => {
      const feedback = {
        id: 'fb_test1',
        message_id: 1,
        conversation_id: 'conv_1',
        rating: 'down',
        reason: '答案错误',
        correction: '',
        source_channel: 'user_button',
        status: 'pending',
        compliance_risk: 0,
        created_at: '2026-04-01T00:00:00',
        updated_at: '2026-04-01T00:00:00',
        user_question: '等待期多长？',
        assistant_answer: '不超过90天',
        auto_quality_score: null,
        auto_quality_details: null,
        classified_type: null,
        classified_reason: null,
        classified_fix_direction: null,
      };
      mockedClient.post.mockResolvedValueOnce({ data: feedback });

      const result = await submitFeedback({
        message_id: 1,
        rating: 'down',
        reason: '答案错误',
      });

      expect(result).toEqual(feedback);
      expect(mockedClient.post).toHaveBeenCalledWith('/api/feedback/submit', {
        message_id: 1,
        rating: 'down',
        reason: '答案错误',
        correction: undefined,
      });
    });

    it('rejects when server returns error', async () => {
      mockedClient.post.mockRejectedValueOnce(new Error('消息不存在'));

      await expect(
        submitFeedback({ message_id: 99999, rating: 'down' }),
      ).rejects.toThrow('消息不存在');
    });
  });

  describe('fetchBadcases', () => {
    it('fetches badcases with no filters', async () => {
      const badcases = [{ id: 'fb_1', rating: 'down', status: 'pending' }];
      mockedClient.get.mockResolvedValueOnce({ data: badcases });

      const result = await fetchBadcases();

      expect(result).toEqual(badcases);
      expect(mockedClient.get).toHaveBeenCalledWith('/api/feedback/badcases', {
        params: undefined,
      });
    });

    it('passes status filter', async () => {
      mockedClient.get.mockResolvedValueOnce({ data: [] });

      await fetchBadcases({ status: 'pending' });

      expect(mockedClient.get).toHaveBeenCalledWith('/api/feedback/badcases', {
        params: { status: 'pending' },
      });
    });

    it('passes multiple filters', async () => {
      mockedClient.get.mockResolvedValueOnce({ data: [] });

      await fetchBadcases({ status: 'classified', classified_type: 'hallucination' });

      expect(mockedClient.get).toHaveBeenCalledWith('/api/feedback/badcases', {
        params: { status: 'classified', classified_type: 'hallucination' },
      });
    });
  });

  describe('fetchBadcase', () => {
    it('fetches a single badcase by id', async () => {
      const badcase = { id: 'fb_1', rating: 'down' };
      mockedClient.get.mockResolvedValueOnce({ data: badcase });

      const result = await fetchBadcase('fb_1');

      expect(result).toEqual(badcase);
      expect(mockedClient.get).toHaveBeenCalledWith('/api/feedback/badcases/fb_1');
    });
  });

  describe('updateBadcase', () => {
    it('puts updates to badcase', async () => {
      const updated = { id: 'fb_1', status: 'classified', classified_type: 'hallucination' };
      mockedClient.put.mockResolvedValueOnce({ data: updated });

      const result = await updateBadcase('fb_1', {
        status: 'classified',
        classified_type: 'hallucination',
      });

      expect(result).toEqual(updated);
      expect(mockedClient.put).toHaveBeenCalledWith('/api/feedback/badcases/fb_1', {
        status: 'classified',
        classified_type: 'hallucination',
      });
    });
  });

  describe('fetchFeedbackStats', () => {
    it('fetches feedback statistics', async () => {
      const stats = {
        total: 10,
        up_count: 6,
        down_count: 4,
        satisfaction_rate: 0.6,
        by_type: {},
        by_status: {},
        by_risk: {},
      };
      mockedClient.get.mockResolvedValueOnce({ data: stats });

      const result = await fetchFeedbackStats();

      expect(result).toEqual(stats);
      expect(mockedClient.get).toHaveBeenCalledWith('/api/feedback/stats');
    });
  });
});
