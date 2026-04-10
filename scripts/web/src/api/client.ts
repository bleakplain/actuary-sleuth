import axios from 'axios';

const client = axios.create({
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
});

client.interceptors.response.use(
  (res) => res,
  (err) => {
    const msg = err.response?.data?.detail || err.message || '请求失败';
    return Promise.reject(new Error(msg));
  },
);

export default client;
