import type { ThemeConfig } from 'antd';
import { theme } from 'antd';

const DARK_MENU_TOKENS = {
  darkItemBg: '#0f172a',
  darkSubMenuItemBg: '#0f172a',
  darkItemSelectedBg: 'rgba(255,255,255,0.08)',
  darkItemHoverBg: 'rgba(255,255,255,0.06)',
};

export const appTheme: ThemeConfig = {
  cssVar: true,
  token: {
    colorPrimary: '#1e40af',
    colorSuccess: '#059669',
    colorWarning: '#d97706',
    colorError: '#dc2626',
    colorInfo: '#3b82f6',

    colorText: '#1e293b',
    colorTextSecondary: '#64748b',
    colorTextTertiary: '#94a3b8',
    colorTextDisabled: '#cbd5e1',

    colorBgContainer: '#ffffff',
    colorBgLayout: '#f8fafc',
    colorBgElevated: '#ffffff',

    colorBorder: '#e2e8f0',
    colorBorderSecondary: '#f1f5f9',

    borderRadius: 6,
    borderRadiusSM: 4,
    borderRadiusLG: 8,

    fontSize: 14,
    fontSizeSM: 12,
    fontSizeLG: 16,
  },
  components: {
    Layout: {
      siderBg: '#0f172a',
      headerBg: '#ffffff',
      bodyBg: '#f8fafc',
    },
    Menu: {
      ...DARK_MENU_TOKENS,
      itemSelectedColor: '#3b82f6',
    },
    Table: {
      headerBg: '#f8fafc',
      rowHoverBg: '#f1f5f9',
      cellPaddingBlock: 12,
      cellPaddingInline: 16,
    },
    Card: {
      paddingLG: 20,
    },
    Tag: {
      borderRadiusSM: 4,
    },
    Tabs: {
      inkBarColor: '#1e40af',
      itemActiveColor: '#1e40af',
      itemSelectedColor: '#1e40af',
    },
    Drawer: {
      paddingLG: 24,
    },
    Tree: {
      directoryNodeSelectedBg: '#e0e7ff',
      directoryNodeSelectedColor: '#1e40af',
    },
  },
};

export const sidebarDarkTheme: ThemeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorBgContainer: '#0f172a',
    colorText: 'rgba(255,255,255,0.85)',
    colorTextSecondary: 'rgba(255,255,255,0.65)',
    colorBorder: 'rgba(255,255,255,0.12)',
  },
  components: {
    Menu: {
      ...DARK_MENU_TOKENS,
      itemSelectedColor: '#60a5fa',
    },
  },
};
