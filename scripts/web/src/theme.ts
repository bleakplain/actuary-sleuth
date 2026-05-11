import { theme } from 'antd';

const sharedComponents = {
  Menu: {
    itemBorderRadius: 6,
    subMenuItemBorderRadius: 6,
  },
  Button: {
    borderRadius: 6,
  },
};

const sharedToken = {
  borderRadius: 6,
  colorPrimary: '#1677ff',
  fontSize: 14,
};

export const appTheme = {
  token: sharedToken,
  components: sharedComponents,
};

export const darkTheme = {
  algorithm: theme.darkAlgorithm,
  token: sharedToken,
  components: sharedComponents,
};

export const sidebarDarkTheme = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorBgContainer: '#001529',
  },
  components: {
    Menu: {
      darkItemBg: '#001529',
      darkSubMenuItemBg: '#000c17',
      darkItemSelectedBg: '#1677ff',
    },
  },
};