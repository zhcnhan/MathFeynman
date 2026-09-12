import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
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
        <span className="brand">颜回<small>YANHUI</small></span>
        <NavLink to="/" end>主页</NavLink>
        <SubjectSwitcher />
        <NavLink to="/subjects" end>学科列表</NavLink>
        <NavLink to="/review">复习</NavLink>
        <NavLink to="/feedback">内容反馈</NavLink>
        <NavLink to="/feynman-history">费曼复盘</NavLink>
        {/* R61：记录 / 提示词 / AI 对话记录**默认从主导航收起**，在「设置 · 高级」里打开；
            打开后入口明显（就在下面这一串）。功能一个不少、两次点击内可达。 */}
        {devMode && (
          <>
            <NavLink to="/ledger">记录</NavLink>
            <NavLink to="/prompts">提示词</NavLink>
            <NavLink to="/ai-traces">AI 对话记录</NavLink>
          </>
        )}
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
            {/* R65 任务 A：以前这里静默 `Navigate to="/"` —— 用户会以为"程序坏了"。
                现在给一句中文说明 + 两个能点回去的入口（不新造页面，就用现有卡片样式）。 */}
            <Route path="*" element={<UnknownPath />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}

/** 打不开的地址：说清最可能的原因（学科停用/链接过期），并给出口。 */
function UnknownPath() {
  return (
    <div className="card">
      <h2>这个页面打不开</h2>
      <p className="muted">
        多半是这个学科已经停用了（停用的学科不再显示内容），也可能是链接过期了。
        停用的学科可以在「学科列表」里重新启用，启用后内容与进度都还在。
      </p>
      <div className="actions">
        <Link className="button-link primary" to="/subjects">去学科列表（可重新启用）</Link>
        <Link className="button-link" to="/">回主页</Link>
      </div>
    </div>
  );
}
