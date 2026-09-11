// 费曼复盘（docs/07 §2.3）：回看历史口述与评分（"我当时哪里讲岔了"）。
// R9：顶部"← 返回 / 回仪表盘"导航；维度 key 中文标签；comment 走 MdMath 渲染。
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, FeynmanHistoryItem } from "../api";
import { dimLabel } from "../components/feynmanLabels";
import MdMath from "../components/MdMath";

const VERDICT_TEXT: Record<string, string> = {
  pass: "通过（完整稿）",
  fail: "完整稿未过",
  gap_filled: "补答：缺口已补上",
  gap_open: "补答：缺口未补上",
  deferred: "待复核",
};

export default function FeynmanHistoryPage() {
  const nav = useNavigate();
  const [items, setItems] = useState<FeynmanHistoryItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api
      .get<{ items: FeynmanHistoryItem[] }>("/history/feynman")
      .then((r) => setItems(r.items))
      .catch((e) => setErr((e as Error).message));
  }, []);
  if (err) return <div className="card error">{err}</div>;
  if (!items) return <div className="card">加载中…</div>;
  if (items.length === 0) {
    return (
      <div className="card">
        <NavBar nav={nav} />
        <div className="crumbs"><Link to="/feedback">内容纠错记录（内容反馈）→</Link></div>
        <h1>费曼复盘</h1>
        <p className="empty">还没有费曼口述记录 —— 学完一个知识点（讲一遍并通过）后，这里会回放你的每一次口述。</p>
      </div>
    );
  }
  return (
    <div className="history-page">
      <NavBar nav={nav} />
      <div className="crumbs"><Link to="/feedback">内容纠错记录（内容反馈）→</Link></div>
      <h1>费曼复盘记录</h1>
      {items.map((it) => {
        const dims = (it.meta?.dims as Array<{ key: string; score: number; evidence_quote: string; comment: string }>) ?? [];
        return (
          <div key={it.id} className="card history-item">
            <div className="history-head">
              <strong>{it.node_title}</strong>
              <span className={`badge ${it.verdict}`}>{VERDICT_TEXT[it.verdict] ?? it.verdict}{it.score != null ? ` · ${Math.round(it.score * 100)} 分` : ""}</span>
              <span className="dim">{it.created_at ? new Date(it.created_at).toLocaleString("zh-CN") : ""}</span>
            </div>
            <blockquote>“{it.transcript}”</blockquote>
            {dims.length > 0 && (
              <ul className="history-dims">
                {dims.map((d, i) => (
                  <li key={i}>
                    <strong>{dimLabel(d.key)}</strong> {Math.round(d.score * 100)}/100 —— “{d.evidence_quote}”{" "}
                    <span className="dim"><MdMath text={d.comment} /></span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

function NavBar({ nav }: { nav: ReturnType<typeof useNavigate> }) {
  return (
    <div className="input-row" style={{ margin: "0 0 12px" }}>
      <button className="ghost" onClick={() => nav(-1)}>← 返回</button>
      <button className="ghost" onClick={() => nav("/")}>回仪表盘</button>
    </div>
  );
}
