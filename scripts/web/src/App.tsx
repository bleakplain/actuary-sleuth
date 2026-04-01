import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import AppLayout from './components/AppLayout';
import AskPage from './pages/AskPage';
import KnowledgePage from './pages/KnowledgePage';
import EvalDatasetPage from './pages/EvalDatasetPage';
import EvalRunPage from './pages/EvalRunPage';
import CompliancePage from './pages/CompliancePage';
import FeedbackPage from './pages/FeedbackPage';

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<AskPage />} />
            <Route path="/ask" element={<AskPage />} />
            <Route path="/knowledge" element={<KnowledgePage />} />
            <Route path="/eval/dataset" element={<EvalDatasetPage />} />
            <Route path="/eval/runs" element={<EvalRunPage />} />
            <Route path="/compliance" element={<CompliancePage />} />
            <Route path="/feedback" element={<FeedbackPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}
