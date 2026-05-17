import { useState } from 'react';
import { Form, Input, Button, Card, Typography, message, theme } from 'antd';
import { LockOutlined, MailOutlined, GiftOutlined } from '@ant-design/icons';
import { useNavigate, Link } from 'react-router-dom';
import client from '../api/client';

export default function RegisterPage() {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { token: themeToken } = theme.useToken();

  const onFinish = async (values: { email: string; password: string; invite_code: string }) => {
    setLoading(true);
    try {
      const res = await client.post('/api/auth/register', values);
      message.info(res.data.message || '注册成功');
      navigate('/login', { replace: true });
    } catch (e: any) {
      message.error(e?.detail || e?.response?.data?.detail || '注册失败');
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
          注册账号
        </Typography.Title>
        <Form onFinish={onFinish} size="large" autoComplete="off">
          <Form.Item name="email" rules={[{ required: true, type: 'email', message: '请输入有效邮箱' }]}>
            <Input prefix={<MailOutlined />} placeholder="邮箱" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, min: 8, message: '密码至少 8 位' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码（至少 8 位）" />
          </Form.Item>
          <Form.Item name="invite_code" rules={[{ required: true, message: '请输入邀请码' }]}>
            <Input prefix={<GiftOutlined />} placeholder="邀请码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              注册
            </Button>
          </Form.Item>
          <div style={{ textAlign: 'center' }}>
            <Link to="/login">已有账号？去登录</Link>
          </div>
        </Form>
      </Card>
    </div>
  );
}
