import { lazy, Suspense, type ComponentType } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ConfigProvider, Skeleton } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { appTheme, darkTheme } from './theme';
import { useTheme } from './hooks/useTheme';
import PageErrorBoundary from './components/PageErrorBoundary';
import SkipLink from './components/SkipLink';
import AppLayout from './components/AppLayout';

const AskPage = lazy(() => import('./pages/AskPage'));
const KnowledgePage = lazy(() => import('./pages/KnowledgePage'));
const EvalPage = lazy(() => import('./pages/EvalPage'));
const CompliancePage = lazy(() => import('./pages/CompliancePage'));
const FeedbackPage = lazy(() => import('./pages/FeedbackPage'));
const ObservabilityPage = lazy(() => import('./pages/ObservabilityPage'));

function withErrorBoundary(Page: ComponentType) {
  function Wrapped() {
    return (
      <PageErrorBoundary>
        <Page />
      </PageErrorBoundary>
    );
  }
  Wrapped.displayName = `WithErrorBoundary(${Page.displayName || 'Page'})`;
  return Wrapped;
}

const SafeAsk = withErrorBoundary(AskPage);
const SafeKnowledge = withErrorBoundary(KnowledgePage);
const SafeEval = withErrorBoundary(EvalPage);
const SafeCompliance = withErrorBoundary(CompliancePage);
const SafeFeedback = withErrorBoundary(FeedbackPage);
const SafeObservability = withErrorBoundary(ObservabilityPage);

function PageSkeleton() {
  return <Skeleton active paragraph={{ rows: 6 }} style={{ padding: 24 }} />;
}

export default function App() {
  const { isDark } = useTheme();

  return (
    <>
      <SkipLink />
      <ConfigProvider locale={zhCN} theme={isDark ? darkTheme : appTheme}>
        <BrowserRouter>
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="/" element={<Suspense fallback={<PageSkeleton />}><SafeAsk /></Suspense>} />
              <Route path="/ask" element={<Suspense fallback={<PageSkeleton />}><SafeAsk /></Suspense>} />
              <Route path="/knowledge" element={<Suspense fallback={<PageSkeleton />}><SafeKnowledge /></Suspense>} />
              <Route path="/eval" element={<Suspense fallback={<PageSkeleton />}><SafeEval /></Suspense>} />
              <Route path="/compliance" element={<Suspense fallback={<PageSkeleton />}><SafeCompliance /></Suspense>} />
              <Route path="/feedback" element={<Suspense fallback={<PageSkeleton />}><SafeFeedback /></Suspense>} />
              <Route path="/observability" element={<Suspense fallback={<PageSkeleton />}><SafeObservability /></Suspense>} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ConfigProvider>
    </>
  );
}