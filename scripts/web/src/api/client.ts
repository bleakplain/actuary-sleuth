import axios from 'axios';

function suggestionForStatus(status: number): string {
  if (status === 0) return '请检查网络连接后重试';
  if (status >= 500) return '服务暂时不可用，请稍后重试';
  if (status >= 400) return '请检查输入参数是否正确';
  return '请刷新页面重试';
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly suggestion: string;
  readonly data: unknown;

  constructor(status: number, detail: string, data?: unknown) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.suggestion = suggestionForStatus(status);
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
    if (status === 401) {
      localStorage.removeItem('auth_token');
      delete axios.defaults.headers.common['Authorization'];
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    const detail = err.response?.data?.detail || err.message || '请求失败，请检查网络后重试';
    throw new ApiError(status, detail, err.response?.data);
  },
);

export default client;
