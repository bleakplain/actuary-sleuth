import { useEffect, useState, useCallback } from 'react';
import {
  Table, Button, Tag, Modal, Form, Input, Select, Space, message, Popconfirm, Typography, Card, Tabs,
} from 'antd';
import { PlusOutlined, StopOutlined, CheckOutlined } from '@ant-design/icons';
import client from '../api/client';

interface User {
  id: string;
  email: string;
  display_name: string;
  role_id: string;
  status: string;
  email_verified_at: string | null;
  created_at: string;
}

interface InviteCode {
  id: string;
  code: string;
  role_id: string;
  created_by: string;
  used_by: string | null;
  used_at: string | null;
  expires_at: string;
  created_at: string;
}

interface Role {
  id: string;
  display_name: string;
  permissions_json: string;
  created_at: string;
}

const ROLES = ['admin', 'actuary', 'compliance', 'viewer'];
const ALL_PERMISSIONS = ['ask', 'compliance', 'eval', 'knowledge', 'memory', 'admin'];
const STATUS_COLORS: Record<string, string> = { active: 'green', pending: 'orange', disabled: 'red' };

function UsersTab() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [editModal, setEditModal] = useState<{ open: boolean; user: User | null }>({ open: false, user: null });
  const [form] = Form.useForm();

  const fetchUsers = useCallback(() => {
    setLoading(true);
    client.get('/api/admin/users').then((r) => setUsers(r.data)).finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const handleUpdate = async (values: { status?: string; role_id?: string; display_name?: string }) => {
    if (!editModal.user) return;
    try {
      await client.patch(`/api/admin/users/${editModal.user.id}`, values);
      message.success('更新成功');
      setEditModal({ open: false, user: null });
      fetchUsers();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '更新失败');
    }
  };

  const handleActivate = async (user: User) => {
    try {
      await client.patch(`/api/admin/users/${user.id}`, { email_verified: true, status: 'active' });
      message.success('已激活');
      fetchUsers();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '操作失败');
    }
  };

  const columns = [
    { title: '邮箱', dataIndex: 'email', key: 'email' },
    { title: '显示名', dataIndex: 'display_name', key: 'display_name' },
    { title: '角色', dataIndex: 'role_id', key: 'role_id', render: (v: string) => <Tag>{v}</Tag> },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (v: string) => <Tag color={STATUS_COLORS[v]}>{v}</Tag>,
    },
    {
      title: '邮箱验证', dataIndex: 'email_verified_at', key: 'verified',
      render: (v: string | null) => v ? <Tag color="green">已验证</Tag> : <Tag color="orange">未验证</Tag>,
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: (v: string) => v?.slice(0, 19) },
    {
      title: '操作', key: 'actions',
      render: (_: unknown, record: User) => (
        <Space>
          {record.status === 'pending' && (
            <Button size="small" icon={<CheckOutlined />} onClick={() => handleActivate(record)}>激活</Button>
          )}
          <Button size="small" onClick={() => { setEditModal({ open: true, user: record }); form.setFieldsValue(record); }}>
            编辑
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Table dataSource={users} columns={columns} rowKey="id" loading={loading} size="small" />
      <Modal
        title="编辑用户"
        open={editModal.open}
        onCancel={() => setEditModal({ open: false, user: null })}
        onOk={() => form.submit()}
      >
        <Form form={form} onFinish={handleUpdate} layout="vertical">
          <Form.Item name="display_name" label="显示名"><Input /></Form.Item>
          <Form.Item name="role_id" label="角色">
            <Select options={ROLES.map((r) => ({ value: r, label: r }))} />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={[{ value: 'active', label: '启用' }, { value: 'disabled', label: '禁用' }]} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

function InviteCodesTab() {
  const [codes, setCodes] = useState<InviteCode[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm();

  const fetchCodes = useCallback(() => {
    setLoading(true);
    client.get('/api/admin/invite-codes').then((r) => setCodes(r.data)).finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchCodes(); }, [fetchCodes]);

  const handleCreate = async (values: { role_id: string; expires_hours: number }) => {
    try {
      await client.post('/api/admin/invite-codes', values);
      message.success('邀请码已创建');
      setCreateOpen(false);
      form.resetFields();
      fetchCodes();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '创建失败');
    }
  };

  const handleDisable = async (id: string) => {
    try {
      await client.patch(`/api/admin/invite-codes/${id}/disable`);
      message.success('已禁用');
      fetchCodes();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '操作失败');
    }
  };

  const isExpired = (expires_at: string) => new Date(expires_at) < new Date();

  const columns = [
    { title: '邀请码', dataIndex: 'code', key: 'code', render: (v: string) => <Typography.Text copyable code>{v}</Typography.Text> },
    { title: '角色', dataIndex: 'role_id', key: 'role_id', render: (v: string) => <Tag>{v}</Tag> },
    {
      title: '状态', key: 'status',
      render: (_: unknown, r: InviteCode) => {
        if (r.used_by) return <Tag color="blue">已使用</Tag>;
        if (isExpired(r.expires_at)) return <Tag color="red">已过期</Tag>;
        return <Tag color="green">有效</Tag>;
      },
    },
    { title: '过期时间', dataIndex: 'expires_at', key: 'expires_at', render: (v: string) => v?.slice(0, 19) },
    {
      title: '操作', key: 'actions',
      render: (_: unknown, r: InviteCode) =>
        !r.used_by && !isExpired(r.expires_at) ? (
          <Popconfirm title="确定禁用？" onConfirm={() => handleDisable(r.id)}>
            <Button size="small" danger icon={<StopOutlined />}>禁用</Button>
          </Popconfirm>
        ) : null,
    },
  ];

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>创建邀请码</Button>
      </div>
      <Table dataSource={codes} columns={columns} rowKey="id" loading={loading} size="small" />
      <Modal
        title="创建邀请码"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); form.resetFields(); }}
        onOk={() => form.submit()}
      >
        <Form form={form} onFinish={handleCreate} layout="vertical" initialValues={{ role_id: 'viewer', expires_hours: 72 }}>
          <Form.Item name="role_id" label="分配角色" rules={[{ required: true }]}>
            <Select options={ROLES.filter((r) => r !== 'admin').map((r) => ({ value: r, label: r }))} />
          </Form.Item>
          <Form.Item name="expires_hours" label="有效时长（小时）" rules={[{ required: true }]}>
            <Input type="number" min={1} max={720} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

function RolesTab() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(false);
  const [editModal, setEditModal] = useState<{ open: boolean; role: Role | null }>({ open: false, role: null });
  const [form] = Form.useForm();

  const fetchRoles = useCallback(() => {
    setLoading(true);
    client.get('/api/admin/roles').then((r) => setRoles(r.data)).finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchRoles(); }, [fetchRoles]);

  const handleUpdate = async (values: { permissions: string[] }) => {
    if (!editModal.role) return;
    try {
      await client.patch(`/api/admin/roles/${editModal.role.id}`, values);
      message.success('权限已更新');
      setEditModal({ open: false, role: null });
      fetchRoles();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '更新失败');
    }
  };

  const columns = [
    { title: '角色 ID', dataIndex: 'id', key: 'id' },
    { title: '显示名', dataIndex: 'display_name', key: 'display_name' },
    {
      title: '权限', dataIndex: 'permissions_json', key: 'perms',
      render: (v: string) => {
        try {
          return JSON.parse(v).map((p: string) => <Tag key={p}>{p}</Tag>);
        } catch { return v; }
      },
    },
    {
      title: '操作', key: 'actions',
      render: (_: unknown, record: Role) => (
        <Button size="small" onClick={() => {
          setEditModal({ open: true, role: record });
          try { form.setFieldsValue({ permissions: JSON.parse(record.permissions_json) }); } catch { /* */ }
        }}>编辑权限</Button>
      ),
    },
  ];

  return (
    <>
      <Table dataSource={roles} columns={columns} rowKey="id" loading={loading} size="small" pagination={false} />
      <Modal
        title={`编辑权限 - ${editModal.role?.display_name || ''}`}
        open={editModal.open}
        onCancel={() => setEditModal({ open: false, role: null })}
        onOk={() => form.submit()}
      >
        <Form form={form} onFinish={handleUpdate} layout="vertical">
          <Form.Item name="permissions" label="权限" rules={[{ required: true }]}>
            <Select mode="multiple" options={ALL_PERMISSIONS.map((p) => ({ value: p, label: p }))} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default function AdminPage() {
  const items = [
    { key: 'users', label: '用户管理', children: <UsersTab /> },
    { key: 'invite-codes', label: '邀请码管理', children: <InviteCodesTab /> },
    { key: 'roles', label: '角色权限', children: <RolesTab /> },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Card bordered={false}>
        <Typography.Title level={4} style={{ marginBottom: 24 }}>系统管理</Typography.Title>
        <Tabs items={items} />
      </Card>
    </div>
  );
}
