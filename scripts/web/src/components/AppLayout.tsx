import { useState } from 'react';
import { Layout, Menu } from 'antd';
import {
  MessageOutlined,
  DatabaseOutlined,
  BarChartOutlined,
  SafetyCertificateOutlined,
  DislikeOutlined,
} from '@ant-design/icons';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';

const { Sider, Content, Header } = Layout;

const menuItems = [
  { key: '/ask', icon: <MessageOutlined />, label: '法规问答' },
  { key: '/knowledge', icon: <DatabaseOutlined />, label: '知识库管理' },
  { key: '/eval', icon: <BarChartOutlined />, label: 'RAG 评估' },
  { key: '/compliance', icon: <SafetyCertificateOutlined />, label: '合规检查' },
  { key: '/feedback', icon: <DislikeOutlined />, label: '问题反馈' },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);

  const selectedKey = menuItems.find((item) => location.pathname.startsWith(item.key))?.key || '/ask';

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="light"
        style={{ borderRight: '1px solid #f0f0f0' }}
      >
        <div
          style={{
            height: 48,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <span style={{ fontWeight: 600, fontSize: collapsed ? 14 : 16 }}>
            {collapsed ? 'AS' : '精算助手'}
          </span>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ borderRight: 0 }}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 24px',
            borderBottom: '1px solid #f0f0f0',
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <span style={{ fontSize: 16, fontWeight: 500 }}>精算法规知识平台</span>
        </Header>
        <Content style={{ margin: 16, overflow: 'auto' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
