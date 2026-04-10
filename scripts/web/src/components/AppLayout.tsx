import { useState } from 'react';
import { Layout, Menu, ConfigProvider, theme } from 'antd';
import {
  MessageOutlined,
  DatabaseOutlined,
  BarChartOutlined,
  SafetyCertificateOutlined,
  DislikeOutlined,
  ExperimentOutlined,
} from '@ant-design/icons';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import { sidebarDarkTheme } from '../theme';

const { Sider, Content, Header } = Layout;

function SidebarLogo({ collapsed }: { collapsed: boolean }) {
  const { token } = theme.useToken();
  return (
    <div
      style={{
        height: 48,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        borderBottom: `1px solid ${token.colorBorder}`,
      }}
    >
      <span style={{ fontWeight: token.fontWeightStrong, fontSize: collapsed ? 14 : 16, color: token.colorText }}>
        {collapsed ? 'AS' : '精算助手'}
      </span>
    </div>
  );
}

const menuItems = [
  { key: '/ask', icon: <MessageOutlined />, label: '法规问答' },
  { key: '/knowledge', icon: <DatabaseOutlined />, label: '知识库管理' },
  { key: '/eval', icon: <BarChartOutlined />, label: 'RAG 评估' },
  { key: '/compliance', icon: <SafetyCertificateOutlined />, label: '合规检查' },
  { key: '/feedback', icon: <DislikeOutlined />, label: '问题反馈' },
  { key: '/observability', icon: <ExperimentOutlined />, label: '可测性' },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const { token } = theme.useToken();

  const selectedKey = menuItems.find((item) => location.pathname.startsWith(item.key))?.key || '/ask';

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <ConfigProvider theme={sidebarDarkTheme}>
        <Sider
          collapsible
          collapsed={collapsed}
          onCollapse={setCollapsed}
          theme="dark"
        >
          <SidebarLogo collapsed={collapsed} />
          <Menu
            mode="inline"
            selectedKeys={[selectedKey]}
            items={menuItems}
            onClick={({ key }) => navigate(key)}
            style={{ borderRight: 0 }}
          />
        </Sider>
      </ConfigProvider>
      <Layout>
        <Header
          style={{
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <span style={{ fontSize: 16, fontWeight: token.fontWeightStrong }}>精算法规知识平台</span>
        </Header>
        <Content style={{ margin: 'var(--content-padding)', overflow: 'auto' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
