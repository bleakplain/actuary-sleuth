import { useState } from 'react';
import { Layout, Menu, ConfigProvider, theme, Grid } from 'antd';
import {
  MessageOutlined,
  DatabaseOutlined,
  BarChartOutlined,
  SafetyCertificateOutlined,
  DislikeOutlined,
  ExperimentOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import { sidebarDarkTheme } from '../theme';
import { MOBILE_NAV_HEIGHT } from '../constants/layout';

const { Sider, Content, Header } = Layout;
const { useBreakpoint } = Grid;

const menuItems = [
  { key: '/ask', icon: <MessageOutlined />, label: '法规问答' },
  { key: '/knowledge', icon: <DatabaseOutlined />, label: '知识库管理' },
  { key: '/product-docs', icon: <FileTextOutlined />, label: '产品文档审核' },
  { key: '/eval', icon: <BarChartOutlined />, label: 'RAG 评估' },
  { key: '/compliance', icon: <SafetyCertificateOutlined />, label: '合规检查' },
  { key: '/feedback', icon: <DislikeOutlined />, label: '问题反馈' },
  { key: '/observability', icon: <ExperimentOutlined />, label: '可测性' },
];

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

function MobileTabBar({ selectedKey, onSelect }: { selectedKey: string; onSelect: (key: string) => void }) {
  const { token } = theme.useToken();
  return (
    <div
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        height: MOBILE_NAV_HEIGHT,
        background: token.colorBgContainer,
        borderTop: `1px solid ${token.colorBorderSecondary}`,
        zIndex: 1000,
        display: 'flex',
        alignItems: 'stretch',
        padding: '4px 0',
        paddingBottom: 'max(4px, env(safe-area-inset-bottom))',
        overflowX: 'hidden',
      }}
    >
      {menuItems.map((item) => {
        const active = selectedKey === item.key;
        return (
          <div
            key={item.key}
            onClick={() => onSelect(item.key)}
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              color: active ? token.colorPrimary : token.colorTextSecondary,
              fontSize: 10,
              lineHeight: 1,
              WebkitTapHighlightColor: 'transparent',
              userSelect: 'none',
            }}
          >
            <span style={{ fontSize: 20, lineHeight: 1, display: 'flex', alignItems: 'center' }}>{item.icon}</span>
            <span style={{ marginTop: 1, fontSize: 10, maxWidth: 48, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {item.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const { token } = theme.useToken();
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  const selectedKey = menuItems.find((item) => location.pathname.startsWith(item.key))?.key || '/ask';

  if (isMobile) {
    return (
      <Layout style={{ minHeight: '100vh' }}>
        <Header
          style={{
            padding: '0 12px',
            display: 'flex',
            alignItems: 'center',
            height: 48,
            lineHeight: '48px',
          }}
        >
          <span style={{ fontSize: 15, fontWeight: token.fontWeightStrong }}>精算助手</span>
        </Header>
        <Content
          style={{
            margin: 'var(--content-padding)',
            marginBottom: `calc(var(--content-padding) + var(--mobile-nav-height))`,
            overflow: 'auto',
          }}
        >
          <Outlet />
        </Content>
        <MobileTabBar selectedKey={selectedKey} onSelect={(key) => navigate(key)} />
      </Layout>
    );
  }

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
