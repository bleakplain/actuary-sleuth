import { useState } from 'react';
import { Form, Input, Button, Card, Typography, message, theme } from 'antd';
import { LockOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import client from '../api/client';

export default function ChangePasswordPage() {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { token: themeToken } = theme.useToken();

  const onFinish = async (values: { old_password: string; new_password: string }) => {
    setLoading(true);
    try {
      await client.post('/api/auth/change-password', values);
      message.success('密码修改成功');
      navigate(-1);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '修改失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Card style={{ maxWidth: 480 }} bordered={false}>
        <Typography.Title level={4}>修改密码</Typography.Title>
        <Form onFinish={onFinish} layout="vertical" autoComplete="off">
          <Form.Item name="old_password" label="当前密码" rules={[{ required: true, message: '请输入当前密码' }]}>
            <Input.Password prefix={<LockOutlined />} />
          </Form.Item>
          <Form.Item name="new_password" label="新密码" rules={[{ required: true, min: 8, message: '密码至少 8 位' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="至少 8 位" />
          </Form.Item>
          <Form.Item name="confirm" label="确认新密码" dependencies={['new_password']} rules={[
            { required: true, message: '请确认新密码' },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || getFieldValue('new_password') === value) return Promise.resolve();
                return Promise.reject(new Error('两次密码不一致'));
              },
            }),
          ]}>
            <Input.Password prefix={<LockOutlined />} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading}>
              确认修改
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
