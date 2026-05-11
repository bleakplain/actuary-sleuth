import { Component, type ReactNode } from 'react';
import { Button, Result } from 'antd';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class PageErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('[PageErrorBoundary]', error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  handleRefresh = () => {
    window.location.reload();
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <Result
        status="error"
        role="alert"
        title="页面出现错误"
        subTitle={this.state.error?.message || '请尝试刷新页面或稍后重试'}
        extra={[
          <Button key="retry" type="primary" onClick={this.handleRetry}>
            重试
          </Button>,
          <Button key="refresh" onClick={this.handleRefresh}>
            刷新页面
          </Button>,
        ]}
      />
    );
  }
}