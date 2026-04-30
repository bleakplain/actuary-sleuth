import axios from 'axios';

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly data: unknown;

  constructor(status: number, detail: string, data?: unknown) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.data = data;
  }
}

const client = axios.create({
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
});

client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (!axios.isAxiosError(err)) return Promise.reject(err);
    const status = err.response?.status ?? 0;
    const detail = err.response?.data?.detail || err.message || '请求失败';
    throw new ApiError(status, detail, err.response?.data);
  },
);

export default client;
