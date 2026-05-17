import { lazy, Suspense, useEffect, type ComponentType } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, Skeleton } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { appTheme, darkTheme } from './theme';
import { useTheme } from './hooks/useTheme';
import PageErrorBoundary from './components/PageErrorBoundary';
import SkipLink from './components/SkipLink';
import AppLayout from './components/AppLayout';
import { createContext, useContext } from 'react';
import { useAuthStore } from './stores/authStore';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import ResetPasswordPage from './pages/ResetPasswordPage';
import VerifyEmailPage from './pages/VerifyEmailPage';

const AskPage = lazy(() => import('./pages/AskPage'));
const KnowledgePage = lazy(() => import('./pages/KnowledgePage'));
const EvalPage = lazy(() => import('./pages/EvalPage'));
const CompliancePage = lazy(() => import('./pages/CompliancePage'));
const FeedbackPage = lazy(() => import('./pages/FeedbackPage'));
const ObservabilityPage = lazy(() => import('./pages/ObservabilityPage'));
const AdminPage = lazy(() => import('./pages/AdminPage'));
const ChangePasswordPage = lazy(() => import('./pages/ChangePasswordPage'));

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
const SafeAdmin = withErrorBoundary(AdminPage);
const SafeChangePassword = withErrorBoundary(ChangePasswordPage);

function PageSkeleton() {
  return <Skeleton active paragraph={{ rows: 6 }} style={{ padding: 24 }} />;
}

const ThemeContext = createContext<{ isDark: boolean; toggle: () => void }>({ isDark: false, toggle: () => {} });

export function useThemeContext() {
  return useContext(ThemeContext);
}

function AuthGuard({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  const loadUser = useAuthStore((s) => s.loadUser);
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    if (token && !user) loadUser();
  }, [token, user, loadUser]);

  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  const { isDark, toggle } = useTheme();

  return (
    <>
      <SkipLink />
      <ConfigProvider locale={zhCN} theme={isDark ? darkTheme : appTheme}>
        <BrowserRouter>
          <ThemeContext.Provider value={{ isDark, toggle }}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
              <Route path="/reset-password" element={<ResetPasswordPage />} />
              <Route path="/verify-email" element={<VerifyEmailPage />} />
              <Route element={<AuthGuard><AppLayout /></AuthGuard>}>
              <Route path="/" element={<Suspense fallback={<PageSkeleton />}><SafeAsk /></Suspense>} />
              <Route path="/ask" element={<Suspense fallback={<PageSkeleton />}><SafeAsk /></Suspense>} />
              <Route path="/knowledge" element={<Suspense fallback={<PageSkeleton />}><SafeKnowledge /></Suspense>} />
              <Route path="/eval" element={<Suspense fallback={<PageSkeleton />}><SafeEval /></Suspense>} />
              <Route path="/compliance" element={<Suspense fallback={<PageSkeleton />}><SafeCompliance /></Suspense>} />
              <Route path="/feedback" element={<Suspense fallback={<PageSkeleton />}><SafeFeedback /></Suspense>} />
              <Route path="/observability" element={<Suspense fallback={<PageSkeleton />}><SafeObservability /></Suspense>} />
              <Route path="/admin" element={<Suspense fallback={<PageSkeleton />}><SafeAdmin /></Suspense>} />
              <Route path="/change-password" element={<Suspense fallback={<PageSkeleton />}><SafeChangePassword /></Suspense>} />
            </Route>
          </Routes>
          </ThemeContext.Provider>
        </BrowserRouter>
      </ConfigProvider>
    </>
  );
}