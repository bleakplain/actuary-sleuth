import { useState } from 'react';
import { Layout, Menu, ConfigProvider, theme, Grid, Button } from 'antd';
import {
  MessageOutlined,
  DatabaseOutlined,
  BarChartOutlined,
  SafetyCertificateOutlined,
  DislikeOutlined,
  ExperimentOutlined,
  SunOutlined,
  MoonOutlined,
  LogoutOutlined,
  SettingOutlined,
  KeyOutlined,
} from '@ant-design/icons';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import { sidebarDarkTheme } from '../theme';
import { useThemeContext } from '../App';
import { MOBILE_NAV_HEIGHT } from '../constants/layout';
import { useAuthStore } from '../stores/authStore';

const { Sider, Content, Header } = Layout;
const { useBreakpoint } = Grid;

const baseMenuItems = [
  { key: '/ask', icon: <MessageOutlined />, label: '法规问答' },
  { key: '/knowledge', icon: <DatabaseOutlined />, label: '知识库管理' },
  { key: '/eval', icon: <BarChartOutlined />, label: 'RAG 评估' },
  { key: '/compliance', icon: <SafetyCertificateOutlined />, label: '合规检查' },
  { key: '/feedback', icon: <DislikeOutlined />, label: '问题反馈' },
  { key: '/observability', icon: <ExperimentOutlined />, label: '可测性' },
  { key: '/admin', icon: <SettingOutlined />, label: '系统管理', adminOnly: true },
];

function getMenuItems(isAdmin: boolean) {
  return baseMenuItems.filter((item) => !item.adminOnly || isAdmin).map(({ adminOnly, ...rest }) => rest);
}

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

function MobileTabBar({ selectedKey, onSelect, items }: { selectedKey: string; onSelect: (key: string) => void; items: typeof baseMenuItems }) {
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
      {items.map((item: any) => {
        const active = selectedKey === item.key;
        return (
          <div
            key={item.key}
            role="tab"
            tabIndex={active ? 0 : -1}
            aria-selected={active}
            onClick={() => onSelect(item.key)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onSelect(item.key);
              } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                const idx = items.findIndex((m: any) => m.key === item.key);
                const next = e.key === 'ArrowRight'
                  ? (idx + 1) % items.length
                  : (idx - 1 + items.length) % items.length;
                const nextKey = items[next].key;
                onSelect(nextKey);
              }
            }}
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
  const { isDark, toggle: onToggleTheme } = useThemeContext();
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const { token } = theme.useToken();
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const logout = useAuthStore((s) => s.logout);
  const user = useAuthStore((s) => s.user);
  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const isAdmin = user?.role_id === 'admin';
  const menuItems = getMenuItems(isAdmin);
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
            paddingTop: 'max(0px, env(safe-area-inset-top))',
            background: token.colorBgContainer,
          }}
        >
          <span style={{ fontSize: 15, fontWeight: token.fontWeightStrong, color: token.colorText }}>精算助手</span>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 4 }}>
            <Button
              type="text"
              icon={<KeyOutlined />}
              onClick={() => navigate('/change-password')}
              aria-label="修改密码"
              style={{ minWidth: 44, minHeight: 44, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            />
            <Button
              type="text"
              icon={<LogoutOutlined />}
              onClick={handleLogout}
              aria-label="退出登录"
              style={{ minWidth: 44, minHeight: 44, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            />
            <Button
              type="text"
              icon={isDark ? <SunOutlined /> : <MoonOutlined />}
              onClick={onToggleTheme}
              aria-label={isDark ? '切换到浅色模式' : '切换到深色模式'}
              style={{ minWidth: 44, minHeight: 44, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            />
          </div>
        </Header>
        <Content
          style={{
            margin: 'var(--content-padding)',
            marginBottom: `calc(var(--content-padding) + var(--mobile-nav-height))`,
            overflow: 'auto',
          }}
        >
          <main id="main-content">
            <Outlet />
          </main>
        </Content>
        <nav aria-label="主导航">
          <MobileTabBar selectedKey={selectedKey} onSelect={(key) => navigate(key)} items={menuItems as any} />
        </nav>
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
          <nav aria-label="主导航">
          <SidebarLogo collapsed={collapsed} />
          <Menu
            mode="inline"
            selectedKeys={[selectedKey]}
            items={menuItems}
            onClick={({ key }) => navigate(key)}
            style={{ borderRight: 0 }}
          />
          </nav>
        </Sider>
      </ConfigProvider>
      <Layout>
        <Header
          style={{
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            background: token.colorBgContainer,
          }}
        >
          <span style={{ fontSize: 16, fontWeight: token.fontWeightStrong, color: token.colorText }}>精算法规知识平台</span>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Button
              type="text"
              icon={<KeyOutlined />}
              onClick={() => navigate('/change-password')}
              aria-label="修改密码"
            />
            <Button
              type="text"
              icon={<LogoutOutlined />}
              onClick={handleLogout}
              aria-label="退出登录"
            />
            <Button
              type="text"
              icon={isDark ? <SunOutlined /> : <MoonOutlined />}
              onClick={onToggleTheme}
              aria-label={isDark ? '切换到浅色模式' : '切换到深色模式'}
            />
          </div>
        </Header>
        <Content style={{ margin: 'var(--content-padding)', overflow: 'auto' }}>
          <main id="main-content">
            <Outlet />
          </main>
        </Content>
      </Layout>
    </Layout>
  );
}
