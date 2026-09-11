import { useCallback, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import DashboardPage from "./pages/DashboardPage";
import FeedbackPage from "./pages/FeedbackPage";
import FeynmanHistoryPage from "./pages/FeynmanHistoryPage";
import LedgerPage from "./pages/LedgerPage";
import AiTracePage from "./pages/AiTracePage";
import OutlinePage from "./pages/OutlinePage";
import PromptsPage from "./pages/PromptsPage";
import ReviewPage from "./pages/ReviewPage";
import SessionPage from "./pages/SessionPage";
import SettingsPage from "./pages/SettingsPage";
import SubjectsPage from "./pages/SubjectsPage";
import SubjectSwitcher from "./components/SubjectSwitcher";
import { api } from "./api";

export default function App() {
  // R39 §3：**开发者 / 调试**模式（设置里开）→ 侧栏出现「AI 对话记录」入口。
  // ⚠️ 审计本身**默认记录**，与本开关无关（铁则：不靠开关决定"要不要留证据"）。
  const [devMode, setDevMode] = useState(false);

  const loadDev = useCallback(async () => {
    try {
      const s = await api.get<{ developer_mode: boolean }>("/settings");
      setDevMode(!!s.developer_mode);
    } catch {
      setDevMode(false);
    }
  }, []);

  useEffect(() => {
    void loadDev();
    const onChange = () => void loadDev();
    window.addEventListener("yanhui:settings-changed", onChange);
    return () => window.removeEventListener("yanhui:settings-changed", onChange);
  }, [loadDev]);

  return (
    <div className="layout">
      <nav>
        <span className="brand">颜回（YanHui）</span>
        <NavLink to="/" end>仪表盘</NavLink>
        <SubjectSwitcher />
        <NavLink to="/subjects" end>学科列表</NavLink>
        <NavLink to="/review">复习</NavLink>
        <NavLink to="/feedback">内容反馈</NavLink>
        <NavLink to="/feynman-history">费曼复盘</NavLink>
        {/* R39 §1：总账页（一切显性的"一处看全部"入口）——R52：界面一律说人话 */}
        <NavLink to="/ledger">记录</NavLink>
        {devMode && <NavLink to="/ai-traces">AI 对话记录</NavLink>}
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
            <Route path="/feedback" element={<FeedbackPage />} />
            <Route path="/feynman-history" element={<FeynmanHistoryPage />} />
            <Route path="/ledger" element={<LedgerPage />} />
            <Route path="/prompts" element={<PromptsPage />} />
            <Route path="/ai-traces" element={<AiTracePage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}
