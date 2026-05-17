import { useEffect, useState } from 'react';
import { Card, Typography, Button, Spin, theme } from 'antd';
import { useSearchParams, useNavigate } from 'react-router-dom';
import client from '../api/client';

export default function VerifyEmailPage() {
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [msg, setMsg] = useState('');
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { token: themeToken } = theme.useToken();
  const token = searchParams.get('token') || '';

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setMsg('验证链接无效，缺少验证令牌。');
      return;
    }
    client.post('/api/auth/verify-email', { token })
      .then((res) => {
        setStatus('success');
        setMsg(res.data.message || '邮箱验证成功');
      })
      .catch((e) => {
        setStatus('error');
        setMsg(e?.response?.data?.detail || '验证失败');
      });
  }, [token]);

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: themeToken.colorBgLayout,
      }}
    >
      <Card style={{ width: 400, textAlign: 'center' }} bordered={false}>
        {status === 'loading' && <Spin tip="验证中..." />}
        {status === 'success' && (
          <>
            <Typography.Paragraph type="success" style={{ fontSize: 16 }}>
              {msg}
            </Typography.Paragraph>
            <Button type="primary" onClick={() => navigate('/login')}>去登录</Button>
          </>
        )}
        {status === 'error' && (
          <>
            <Typography.Paragraph type="danger" style={{ fontSize: 16 }}>
              {msg}
            </Typography.Paragraph>
            <Button onClick={() => navigate('/login')}>返回登录</Button>
          </>
        )}
      </Card>
    </div>
  );
}
