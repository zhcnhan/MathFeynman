// 仪表盘（docs/07 §2.1 + 阶段 2 关卡地图）：统计条 / 推荐 / 今日复习 / 学段关卡地图。
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, CampaignData, DashboardData, SelfExtendStatus, SessionMeta } from "../api";

const STATE_COLOR: Record<string, string> = {
  locked: "#c3c9d1",
  available: "#42a5f5",
  learning: "#ffb300",
  mastered: "#43a047",
  reviewing: "#fb8c00",
};
const STAGE_NAME: Record<string, string> = {
  primary: "小学",
  middle: "初中",
  high: "高中",
  college: "大学",
  ai: "AI 进阶",
};

export default function Dashboard() {
  const nav = useNavigate();
  const [dash, setDash] = useState<DashboardData | null>(null);
  const [campaign, setCampaign] = useState<CampaignData | null>(null);
  const [sx, setSx] = useState<SelfExtendStatus | null>(null);
  const [mathEnabled, setMathEnabled] = useState<boolean | null>(null);
  const [sxBusy, setSxBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<{ id: string; node: string } | null>(() => {
    try {
      const s = localStorage.getItem("yanhui:last_session");
      return s ? (JSON.parse(s) as { id: string; node: string }) : null;
    } catch {
      return null;
    }
  });

  useEffect(() => {
    Promise.all([
      api.get<DashboardData>("/dashboard"),
      api.get<CampaignData>("/campaign"),
      api.get<SelfExtendStatus>("/selfextend/status"),
      api.get<{ subjects: { id: string; enabled: boolean }[] }>("/subjects"),
    ])
      .then(([d, c, s, subs]) => {
        setDash(d);
        setCampaign(c);
        setSx(s);
        const math = subs.subjects.find((x) => x.id === "math");
        setMathEnabled(math ? math.enabled : true);
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  const runSelfExtend = async () => {
    setSxBusy(true);
    setError(null);
    try {
      const r = await api.post<{ started: boolean; status?: string; summary?: string }>("/selfextend/run", {});
      setSx((prev) => (prev ? { ...prev, running: false, last_status: r.status ?? "done", last_summary: r.summary ?? "" } : prev));
      // 等片刻（后台任务完成写盘/DB）后刷新地图与状态
      await new Promise((res) => setTimeout(res, 900));
      const [c2, s2] = await Promise.all([
        api.get<CampaignData>("/campaign"),
        api.get<SelfExtendStatus>("/selfextend/status"),
      ]);
      setCampaign(c2);
      setSx(s2);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSxBusy(false);
    }
  };

  const startNode = async (nodeId: string) => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<SessionMeta & { session: SessionMeta }>("/session/start", { node_id: nodeId });
      nav(`/session/${r.session.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  if (error) return <div className="card error">无法连接后端：{error}</div>;
  if (!dash || !campaign) return <div className="card">加载中…</div>;
  const s = dash.stats;
  return (
    <div className="dashboard">
      <h1>仪表盘</h1>
      {mathEnabled === false && (
        <div className="banner warn">
          预置学科（数学）已停用：其学习内容与进度暂不可见（关卡地图同步隐藏，引擎仍拒绝越级学习）。
          请前往「学科列表 → 已移除」重新启用后继续；其它学科不受影响。
        </div>
      )}
      <div className="stats-bar">
        <Stat n={s.mastered} label="已掌握" />
        <Stat n={s.available} label="可学" />
        <Stat n={s.learning} label="学习中" />
        <Stat n={s.locked} label="锁定" />
        <Stat n={s.consecutive_days} label="连续天数" />
        <Stat n={s.today_done} label="今日完成" />
      </div>

      {last && (
        <div className="card">
          <h2>继续上次学习</h2>
          <div className="recommend">
            <div className="recommend-title">{last.node}</div>
            <button className="primary" onClick={() => nav(`/session/${encodeURIComponent(last.id)}`)}>
              回到上次会话 →
            </button>
            <button className="ghost" style={{ marginLeft: 8 }} onClick={() => { localStorage.removeItem("yanhui:last_session"); setLast(null); }}>不再显示</button>
          </div>
        </div>
      )}

      <div className="grid">
        <section className="card">
          <h2>推荐学习</h2>
          {dash.recommended_node ? (
            <div className="recommend">
              <div className="recommend-title">{dash.recommended_node.title}</div>
              <div className="dim">
                {STAGE_NAME[dash.recommended_node.level] ?? dash.recommended_node.level} · {dash.recommended_node.topic} · 前置完成 {dash.recommended_node.prereqs_met}/{dash.recommended_node.prereqs_total}
              </div>
              <button className="primary" disabled={busy} onClick={() => void startNode(dash.recommended_node!.id)}>
                {dash.recommended_node.prereqs_met === dash.recommended_node.prereqs_total ? "开始学习 →" : "补前置 →"}
              </button>
            </div>
          ) : (
            <p className="empty">全部掌握或暂无内容。{dash.stats.mastered === 0 && "请先为库添加内容节点。"}</p>
          )}
          <h2>今日复习</h2>
          {dash.due_reviews.length === 0 ? (
            <p className="empty">今日无到期复习。</p>
          ) : (
            <ul className="mini-list">
              {dash.due_reviews.slice(0, 5).map((r) => (
                <li key={r.node_id} className={r.stacked ? "stacked-text" : ""}>
                  <Link to="/review">{r.title}{r.stacked ? "（堆积！）" : ""}</Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card map-card">
          <h2>关卡地图</h2>
          {campaign.levels.map((lv) => (
            <div key={lv.level} className={`stage ${lv.unlocked ? "" : "stage-locked"}`}>
              <h3>{STAGE_NAME[lv.level] ?? lv.level} {!lv.unlocked && <span className="badge">待解锁</span>}</h3>
              {lv.groups.length === 0 ? (
                <p className="empty dim">（内容生成中…）</p>
              ) : (
                lv.groups.map((g) => (
                  <div key={g.topic} className={`topic-group ${g.completed ? "completed" : ""}`}>
                    <div className="topic-head">
                      <strong>{g.topic}</strong>
                      <span className="dim">{(g.boss ? "👑 首领 · " : "")}{g.progress.mastered}/{g.progress.total}</span>
                      {g.completed && <span className="badge pass">通关 ✓</span>}
                    </div>
                    <div className="map-nodes">
                      {g.nodes.map((n) => (
                        <button
                          key={n.id}
                          type="button"
                          className="map-node"
                          disabled={busy || (n.state !== "available" && n.state !== "learning")}
                          title={`${n.title}（${n.state}${n.kind === "boss" ? " · 首领" : ""}）`}
                          onClick={() => void startNode(n.id)}
                        >
                          <i style={{ background: STATE_COLOR[n.state] ?? "#ccc" }} />
                          {n.kind === "boss" ? "👑" : "◎"}
                        </button>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          ))}
          {sx && sx.active_level && (
            <div className="selfextend-panel">
              <h3>🚀 内容自续</h3>
              <p className="dim">
                {STAGE_NAME[sx.active_level] ?? sx.active_level} 蓝图目标掌握 {Math.round((sx.ratio ?? 0) * 100)}%
                {sx.pending_topics.length > 0 && <> · 待生成：{sx.pending_topics.slice(0, 3).join(" / ")}</>}
              </p>
              {sx.running && <div className="banner thinking static">⏳ 正在后台生成新关卡…（不阻塞学习）</div>}
              {!sx.running && sx.last_summary && <div className="dim">上次：{sx.last_summary}</div>}
              {sx.pending_topics.length > 0 && (
                <button className="primary" disabled={sxBusy || sx.running} onClick={() => void runSelfExtend()}>
                  {sxBusy ? "生成中…" : `继续下一关：生成「${sx.pending_topics[0]}」→`}
                </button>
              )}
            </div>
          )}
          {campaign.next_generating && (
            <div className="banner thinking static">🚧 关卡已全部通关，下一关生成中…（学段内容自续流水线）</div>
          )}
          <Legend />
        </section>
      </div>
      <div className="actions">
        <Link className="button-link" to="/review">去复习页</Link>
        <Link className="button-link" to="/feynman-history">费曼复盘</Link>
        <Link className="button-link" to="/settings">设置</Link>
      </div>
    </div>
  );
}

function Stat({ n, label }: { n: number; label: string }) {
  return <div className="stat"><strong>{n}</strong><span>{label}</span></div>;
}

function Legend() {
  return (
    <div className="legend">
      {Object.entries(STATE_COLOR).map(([k, c]) => (
        <span key={k}><i style={{ background: c }} /> {k}</span>
      ))}
      <span>👑 = 主题首领（综合+综述）</span>
    </div>
  );
}
