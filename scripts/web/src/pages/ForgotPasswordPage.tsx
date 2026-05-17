import { useState } from 'react';
import { Form, Input, Button, Card, Typography, message, theme } from 'antd';
import { MailOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import client from '../api/client';

export default function ForgotPasswordPage() {
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const { token: themeToken } = theme.useToken();

  const onFinish = async (values: { email: string }) => {
    setLoading(true);
    try {
      await client.post('/api/auth/forgot-password', values);
      setSent(true);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '请求失败');
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
          忘记密码
        </Typography.Title>
        {sent ? (
          <>
            <Typography.Paragraph type="success" style={{ textAlign: 'center' }}>
              如果该邮箱已注册，重置邮件已发送。
            </Typography.Paragraph>
            <div style={{ textAlign: 'center' }}>
              <Link to="/login">返回登录</Link>
            </div>
          </>
        ) : (
          <Form onFinish={onFinish} size="large" autoComplete="off">
            <Form.Item name="email" rules={[{ required: true, type: 'email', message: '请输入有效邮箱' }]}>
              <Input prefix={<MailOutlined />} placeholder="注册邮箱" />
            </Form.Item>
            <Form.Item>
              <Button type="primary" htmlType="submit" loading={loading} block>
                发送重置邮件
              </Button>
            </Form.Item>
            <div style={{ textAlign: 'center' }}>
              <Link to="/login">返回登录</Link>
            </div>
          </Form>
        )}
      </Card>
    </div>
  );
}
