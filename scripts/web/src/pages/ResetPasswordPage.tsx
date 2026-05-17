import { useState } from 'react';
import { Form, Input, Button, Card, Typography, message, theme } from 'antd';
import { LockOutlined } from '@ant-design/icons';
import { useSearchParams, useNavigate, Link } from 'react-router-dom';
import client from '../api/client';

export default function ResetPasswordPage() {
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { token: themeToken } = theme.useToken();
  const token = searchParams.get('token') || '';

  const onFinish = async (values: { new_password: string }) => {
    if (!token) {
      message.error('重置链接无效');
      return;
    }
    setLoading(true);
    try {
      await client.post('/api/auth/reset-password', { token, new_password: values.new_password });
      setDone(true);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '重置失败');
    } finally {
      setLoading(false);
    }
  };

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
      <Card style={{ width: 380 }} bordered={false}>
        <Typography.Title level={3} style={{ textAlign: 'center', marginBottom: 32 }}>
          重置密码
        </Typography.Title>
        {!token ? (
          <>
            <Typography.Paragraph type="error" style={{ textAlign: 'center' }}>
              重置链接无效，缺少验证令牌。
            </Typography.Paragraph>
            <div style={{ textAlign: 'center' }}>
              <Link to="/forgot-password">重新申请</Link>
            </div>
          </>
        ) : done ? (
          <>
            <Typography.Paragraph type="success" style={{ textAlign: 'center' }}>
              密码重置成功，请使用新密码登录。
            </Typography.Paragraph>
            <div style={{ textAlign: 'center' }}>
              <Button type="primary" onClick={() => navigate('/login')}>去登录</Button>
            </div>
          </>
        ) : (
          <Form onFinish={onFinish} size="large" autoComplete="off">
            <Form.Item name="new_password" rules={[{ required: true, min: 8, message: '密码至少 8 位' }]}>
              <Input.Password prefix={<LockOutlined />} placeholder="新密码（至少 8 位）" />
            </Form.Item>
            <Form.Item name="confirm" dependencies={['new_password']} rules={[
              { required: true, message: '请确认密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('new_password') === value) return Promise.resolve();
                  return Promise.reject(new Error('两次密码不一致'));
                },
              }),
            ]}>
              <Input.Password prefix={<LockOutlined />} placeholder="确认新密码" />
            </Form.Item>
            <Form.Item>
              <Button type="primary" htmlType="submit" loading={loading} block>
                重置密码
              </Button>
            </Form.Item>
          </Form>
        )}
      </Card>
    </div>
  );
}
