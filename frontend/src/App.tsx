import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import DashboardPage from "./pages/DashboardPage";
import FeynmanHistoryPage from "./pages/FeynmanHistoryPage";
import OutlinePage from "./pages/OutlinePage";
import ReviewPage from "./pages/ReviewPage";
import SessionPage from "./pages/SessionPage";
import SettingsPage from "./pages/SettingsPage";
import SubjectsPage from "./pages/SubjectsPage";
import SubjectSwitcher from "./components/SubjectSwitcher";

export default function App() {
  return (
    <div className="layout">
      <nav>
        <span className="brand">MathFeynman</span>
        <NavLink to="/" end>仪表盘</NavLink>
        <SubjectSwitcher />
        <NavLink to="/subjects" end>学科列表</NavLink>
        <NavLink to="/review">复习</NavLink>
        <NavLink to="/feynman-history">费曼复盘</NavLink>
        <NavLink to="/settings">设置</NavLink>
      </nav>
      <main>
        {/* R9 #6：渲染异常可见横幅 + 未知路径兜底回仪表盘 */}
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/subjects" element={<SubjectsPage />} />
            <Route path="/subjects/:id" element={<OutlinePage />} />
            <Route path="/session/:id" element={<SessionPage />} />
            <Route path="/review" element={<ReviewPage />} />
            <Route path="/feynman-history" element={<FeynmanHistoryPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}
