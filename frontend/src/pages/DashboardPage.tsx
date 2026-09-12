// 主页（R61 任务 0）：**以学科为主语**——先问"学哪个学科"，每个学科一张卡（状态 + 下一步），
// 下面用**学习地图**（不是一列行）把它学到哪了画出来；数学只是其中一个学科。
//
// 数据全部来自既有接口（不改后端契约）：
//   /dashboard          统计、推荐、今日复习、预置学科状态
//   /subjects           启用中的学科（含大纲：单元数、章数）
//   /subjects/{id}/progress  单元进度（章 → 单元 + 状态色 + 有没有内容）← 地图的数据源
//   /campaign           关卡地图（预置学科用；学段 → 主题 → 关卡）
//   /graph              知识点状态（用来给学科卡算"学过几个"）
//   /selfextend/status  内容自续状态（预置学科）
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  api, CampaignData, DashboardData, GraphData, SelfExtendStatus, SessionMeta,
} from "../api";
import {
  Card, Collapsible, EmptyState, Legend, Loading, PageHead, Progress,
  STATE_ZH, stateColor,
} from "../components/ui";

const STAGE_NAME: Record<string, string> = {
  primary: "小学",
  middle: "初中",
  high: "高中",
  college: "大学",
  ai: "AI 进阶",
};

interface SubjectUnit {
  id: string;
  title: string;
  group: string;
  status: string;
  open: boolean;
  content_ids: string[];
}
interface SubjectProgress {
  subject: string;
  outline_revision: number | null;
  concepts_mastered: number;
  units: SubjectUnit[];
  note?: string;
}
interface SubjectRow {
  id: string;
  label: string;
  kind: string;
  enabled: boolean;
  outline?: { exists: boolean; units: number; groups: string[] } | null;
}

interface MapNode {
  id: string;
  title: string;
  state: string;
  kind?: string;
  hasContent: boolean;
}
interface MapChapter {
  title: string;
  nodes: MapNode[];
  subtitle?: string;
}

// 单元状态 → 地图上的状态色（单元状态：mastered / equivalent / learning / todo + 是否开放）
function unitState(u: SubjectUnit): string {
  if (!u.content_ids || u.content_ids.length === 0) return "todo";
  if (u.status === "mastered" || u.status === "equivalent") return "mastered";
  if (u.status === "learning") return "learning";
  return u.open ? "available" : "locked";
}

export default function Dashboard() {
  const nav = useNavigate();
  const [dash, setDash] = useState<DashboardData | null>(null);
  const [subjects, setSubjects] = useState<SubjectRow[]>([]);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [campaign, setCampaign] = useState<CampaignData | null>(null);
  const [sx, setSx] = useState<SelfExtendStatus | null>(null);
  const [progress, setProgress] = useState<Record<string, SubjectProgress>>({});
  const [pick, setPick] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sxBusy, setSxBusy] = useState(false);
  const [last, setLast] = useState<{ id: string; node: string } | null>(() => {
    try {
      const s = localStorage.getItem("yanhui:last_session");
      return s ? (JSON.parse(s) as { id: string; node: string }) : null;
    } catch {
      return null;
    }
  });

  const loadAll = useCallback(async () => {
    const [d, subs, g, c, s] = await Promise.all([
      api.get<DashboardData>("/dashboard"),
      api.get<{ subjects: SubjectRow[] }>("/subjects").catch(() => ({ subjects: [] })),
      api.get<GraphData>("/graph").catch(() => ({ nodes: [], edges: [] })),
      api.get<CampaignData>("/campaign").catch(() => ({ levels: [], next: null, next_generating: false })),
      api.get<SelfExtendStatus>("/selfextend/status").catch(() => null),
    ]);
    setDash(d);
    setGraph(g);
    setCampaign(c);
    setSx(s);
    const enabled = (subs.subjects || []).filter((x) => x.enabled);
    setSubjects(enabled);
    // 每个学科各取一份"单元进度"：学科卡与地图都用它（既有接口，不加新字段）
    const pairs = await Promise.all(
      enabled.map(async (x) => {
        try {
          return [x.id, await api.get<SubjectProgress>(`/subjects/${x.id}/progress`)] as const;
        } catch {
          return [x.id, null] as const;
        }
      })
    );
    const map: Record<string, SubjectProgress> = {};
    for (const [id, p] of pairs) if (p) map[id] = p;
    setProgress(map);
    setPick((prev) => prev || enabled[0]?.id || "");
  }, []);

  useEffect(() => {
    loadAll().catch((e) => setError((e as Error).message));
  }, [loadAll]);

  const runSelfExtend = async () => {
    setSxBusy(true);
    setError(null);
    try {
      const r = await api.post<{ started: boolean; status?: string; summary?: string }>("/selfextend/run", {});
      setSx((prev) => (prev
        ? { ...prev, running: false, last_status: r.status ?? "done", last_summary: r.summary ?? "" }
        : prev));
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

  /** 进入某个单元（＝开始/继续学习这个知识点）。 */
  const startUnit = async (unitId: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const r = await api.post<SessionMeta & { session: SessionMeta }>("/session/start", { node_id: unitId });
      nav(`/session/${r.session.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  // ---- 学科卡上的"学过几个/下一步"（用图谱状态 + 单元进度算，不改后端） ----
  const perSubject = useMemo(() => {
    const out: Record<string, {
      total: number; mastered: number; learning: number; withContent: number;
      next: SubjectUnit | null; chapters: number;
    }> = {};
    for (const s of subjects) {
      const p = progress[s.id];
      const units = p?.units ?? [];
      const mastered = units.filter((u) => u.status === "mastered" || u.status === "equivalent").length;
      const learning = units.filter((u) => u.status === "learning").length;
      const withContent = units.filter((u) => (u.content_ids || []).length > 0).length;
      const next = units.find((u) => u.open && (u.content_ids || []).length > 0)
        ?? units.find((u) => u.open)
        ?? null;
      const chapters = new Set(units.map((u) => u.group)).size;
      out[s.id] = { total: units.length, mastered, learning, withContent, next, chapters };
    }
    return out;
  }, [subjects, progress]);

  const active = subjects.find((s) => s.id === pick) ?? subjects[0] ?? null;

  /** 地图数据：预置学科用关卡地图；其它学科用"章 → 单元"的同一套地图形态。 */
  const chapters: MapChapter[] = useMemo(() => {
    if (!active) return [];
    const presetId = dash?.preset_subject?.id;
    const campaignHasNodes = (campaign?.levels ?? []).some((lv) => lv.groups.some((g) => g.nodes.length > 0));
    if (active.id === presetId && campaign && campaignHasNodes) {
      return campaign.levels
        .filter((lv) => lv.groups.length > 0)
        .flatMap((lv) => lv.groups.map((g) => ({
          title: g.topic,
          subtitle: `${STAGE_NAME[lv.level] ?? lv.level} · 已掌握 ${g.progress.mastered}/${g.progress.total}${g.completed ? " · 已通关" : ""}`,
          nodes: g.nodes.map((n) => ({
            id: n.id, title: n.title, state: n.state, kind: n.kind, hasContent: true,
          })),
        })));
    }
    const p = progress[active.id];
    if (!p) return [];
    const byGroup = new Map<string, SubjectUnit[]>();
    for (const u of p.units) {
      const key = u.group || "未分章";
      if (!byGroup.has(key)) byGroup.set(key, []);
      byGroup.get(key)!.push(u);
    }
    return Array.from(byGroup.entries()).map(([group, units]) => ({
      title: group,
      subtitle: `共 ${units.length} 个单元 · 已掌握 ${units.filter((u) => u.status === "mastered" || u.status === "equivalent").length}`,
      nodes: units.map((u) => ({
        id: u.id,
        title: u.title,
        state: unitState(u),
        hasContent: (u.content_ids || []).length > 0,
      })),
    }));
  }, [active, campaign, dash, progress]);

  const mapNodes = useMemo(() => chapters.flatMap((c) => c.nodes), [chapters]);
  const mapDone = mapNodes.filter((n) => n.state === "mastered").length;
  const mapNoContent = mapNodes.filter((n) => !n.hasContent).length;
  /** 有内容的章放在外面；整章都还没出内容的收进折叠区（默认收起，只给一行摘要）。 */
  const [shownChapters, quietChapters] = useMemo(() => {
    const has = (c: MapChapter) => c.nodes.some((n) => n.hasContent);
    return [chapters.filter(has), chapters.filter((c) => !has(c))];
  }, [chapters]);
  const quietNodes = quietChapters.reduce((n, c) => n + c.nodes.length, 0);

  const graphCounts = useMemo(() => {
    const out: Record<string, { total: number; done: number; doing: number }> = {};
    for (const n of graph?.nodes ?? []) {
      const key = n.id.includes(".") ? n.id.slice(0, n.id.indexOf(".")) : n.id;
      if (!out[key]) out[key] = { total: 0, done: 0, doing: 0 };
      out[key].total += 1;
      if (n.state === "mastered") out[key].done += 1;
      if (n.state === "learning") out[key].doing += 1;
    }
    return out;
  }, [graph]);

  if (error && !dash) return <div className="card error">连不上后端：{error}</div>;
  if (!dash) return <Loading what="正在读取你的学习情况…" />;

  const s = dash.stats;
  const presetOff = Boolean(dash.preset_subject && !dash.preset_subject.enabled);

  return (
    <div>
      <PageHead
        title="今天学什么"
        sub={
          s.today_done > 0
            ? `今天已经完成 ${s.today_done} 个单元；连续学习 ${s.consecutive_days} 天。`
            : `还没有开始今天的单元；连续学习 ${s.consecutive_days} 天。`
        }
        actions={<Link className="button-link" to="/subjects">管理学科</Link>}
      />

      {error && <div className="banner error">{error}</div>}
      {notice && <div className="banner ok">{notice}</div>}

      <div className="stats-bar">
        <Stat n={s.mastered} label="已掌握" />
        <Stat n={s.learning} label="正在学" />
        <Stat n={s.available} label="可以学" />
        <Stat n={s.locked} label="还不到时候" />
        <Stat n={s.today_done} label="今日完成" />
      </div>

      {presetOff && (
        <div className="note warn">
          预置学科（{dash.preset_subject?.label ?? ""}）现在是移除了的状态：它的内容与进度暂时不显示，
          学习顺序也不会被它挡住；想接着用就去「学科列表 → 已移除」重新启用。其它学科不受影响。
        </div>
      )}

      {/* ---------------- 学科（主页的主语） ---------------- */}
      <section className="section-title">你的学科</section>
      {subjects.length === 0 ? (
        <EmptyState
          title="还没有学科"
          hint="先新建一个学科，再导入教材，就可以开始学了。"
          action={<Link className="button-link" to="/subjects">去学科列表</Link>}
        />
      ) : (
        <div className="subject-cards">
          {subjects.map((sub) => {
            const info = perSubject[sub.id];
            const gc = graphCounts[sub.id];
            const done = Math.max(info?.mastered ?? 0, gc?.done ?? 0);
            const total = info?.total ?? sub.outline?.units ?? 0;
            const unitsWithContent = info?.withContent ?? gc?.total ?? 0;
            const nextUnit = info?.next ?? null;
            return (
              <Card
                key={sub.id}
                className={"subject-card" + (active?.id === sub.id ? " active" : "")}
              >
                <div className="subject-top">
                  <span className="subject-name">{sub.label}</span>
                  <span className="badge">{sub.kind === "preset" ? "预置" : "自己建的"}</span>
                  {active?.id === sub.id && <span className="badge accent">正在看</span>}
                </div>
                <div className="subject-status">
                  {total === 0
                    ? "还没有课程安排（先去这个学科页导入教材、生成大纲）"
                    : `${info?.chapters || sub.outline?.groups?.length || 0} 章 · ${total} 个单元 · 学过 ${done} 个`}
                </div>
                {total > 0 && <Progress done={done} total={total} label={done === 0 ? "还没开始" : "进度"} />}
                <div className="subject-next">
                  <div className="kicker">下一步</div>
                  {nextUnit ? (
                    <>
                      <div className="title">{nextUnit.title}</div>
                      <div className="muted">
                        {nextUnit.group}
                        {(nextUnit.content_ids || []).length === 0 ? " · 还没出内容" : ""}
                      </div>
                    </>
                  ) : (
                    <div className="muted">
                      {unitsWithContent === 0
                        ? "这个学科还没有可学的内容"
                        : "这一轮都学完了，去复习或看大纲"}
                    </div>
                  )}
                </div>
                <div className="subject-actions">
                  {nextUnit && (nextUnit.content_ids || []).length > 0 ? (
                    <button className="primary" disabled={busy} onClick={() => void startUnit(nextUnit.id)}>
                      开始学这个单元 →
                    </button>
                  ) : (
                    <Link className="button-link" to={`/subjects/${sub.id}`}>去准备内容 →</Link>
                  )}
                  <button className="ghost" onClick={() => setPick(sub.id)}>看它的地图</button>
                  <Link className="button-link" to={`/subjects/${sub.id}`}>大纲与材料</Link>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* ---------------- 学习地图 ---------------- */}
      {active && (
        <section className="section-title">学习地图</section>
      )}
      {active && (
        <Card
          title={`${active.label} · 学到哪了`}
          sub={
            mapNodes.length === 0
              ? "这个学科还没有可画进地图的内容"
              : `这张地图上 ${mapNodes.length} 个单元：已掌握 ${mapDone} 个${mapNoContent > 0 ? `，其中 ${mapNoContent} 个还没出内容` : ""}。点一个就能进那个单元。`
          }
          actions={
            <>
              <Link className="button-link" to={`/subjects/${active.id}`}>看大纲与材料</Link>
            </>
          }
        >
          {subjects.length > 1 && (
            <div className="map-subjects">
              {subjects.map((sub) => (
                <button
                  key={sub.id}
                  className={"map-subject" + (sub.id === active.id ? " active" : "")}
                  onClick={() => setPick(sub.id)}
                >
                  {sub.label}
                </button>
              ))}
            </div>
          )}

          {chapters.length === 0 ? (
            <EmptyState
              title="这个学科还没有内容可以画成地图"
              hint="导入教材并生成大纲后，这里会按章显示每个单元的状态。"
              action={<Link className="button-link" to={`/subjects/${active.id}`}>去导入教材</Link>}
            />
          ) : (
            <>
              {shownChapters.map((ch) => (
                <Chapter key={ch.title} ch={ch} busy={busy} onStart={startUnit} onGoOutline={() => nav(`/subjects/${active.id}`)} />
              ))}
              {quietChapters.length > 0 && (
                <Collapsible
                  id={`home-quiet-${active.id}`}
                  title={`还有 ${quietChapters.length} 章还没出内容`}
                  summary={`${quietNodes} 个单元在排队（点开可以看到是哪些章）`}
                >
                  {quietChapters.map((ch) => (
                    <Chapter key={ch.title} ch={ch} busy={busy} onStart={startUnit} onGoOutline={() => nav(`/subjects/${active.id}`)} />
                  ))}
                </Collapsible>
              )}
              <Legend />
            </>
          )}

          {sx && sx.active_level && (
            <Collapsible
              id="home-selfextend"
              title="自动接着生成下一个主题"
              summary={`${STAGE_NAME[sx.active_level] ?? sx.active_level} · 目标掌握 ${Math.round((sx.ratio ?? 0) * 100)}%${sx.pending_topics.length ? ` · 排在最前面的：${sx.pending_topics[0]}` : ""}`}
            >
              <p className="muted">
                {STAGE_NAME[sx.active_level] ?? sx.active_level} 的目标是掌握 {(sx.ratio ?? 0) * 100 > 0 ? `${Math.round((sx.ratio ?? 0) * 100)}%` : "一定比例"}
                {sx.pending_topics.length > 0 && <> · 还没生成的主题：{sx.pending_topics.slice(0, 3).join(" / ")}</>}
              </p>
              {sx.running && <div className="banner thinking static">⏳ 正在后台生成新的内容…（不影响你现在的学习）</div>}
              {!sx.running && sx.last_summary && <div className="muted">上次：{sx.last_summary}</div>}
              {sx.pending_topics.length > 0 && (
                <button className="primary" disabled={sxBusy || sx.running} onClick={() => void runSelfExtend()}>
                  {sxBusy ? "生成中…" : `生成「${sx.pending_topics[0]}」→`}
                </button>
              )}
            </Collapsible>
          )}
          {campaign?.next_generating && (
            <div className="banner thinking static">🚧 关卡都通关了，正在生成下一关…</div>
          )}
        </Card>
      )}

      {/* ---------------- 今天还要做的事 ---------------- */}
      <div className="grid">
        <Card title="今天要复习的">
          {dash.due_reviews.length === 0 ? (
            <p className="empty">今天没有到期的复习。</p>
          ) : (
            <ul className="mini-list">
              {dash.due_reviews.slice(0, 6).map((r) => (
                <li key={r.node_id} className={r.stacked ? "stacked-text" : ""}>
                  <Link to="/review">{r.title}{r.stacked ? "（堆积了！）" : ""}</Link>
                </li>
              ))}
            </ul>
          )}
          {dash.due_reviews.length > 0 && (
            <div className="actions"><Link className="button-link primary" to="/review">去复习 →</Link></div>
          )}
        </Card>

        <Card title="接着上次">
          {last ? (
            <>
              <div className="subject-status">{last.node}</div>
              <div className="actions">
                <button className="primary" onClick={() => nav(`/session/${encodeURIComponent(last!.id)}`)}>
                  回到上次的会话 →
                </button>
                <button
                  className="ghost"
                  onClick={() => { localStorage.removeItem("yanhui:last_session"); setLast(null); }}
                >
                  不再显示
                </button>
              </div>
            </>
          ) : (
            <p className="empty">还没有打开过任何单元。从上面的地图点一个开始吧。</p>
          )}
          {dash.breakpoints.length > 0 && (
            <p className="muted">还有 {dash.breakpoints.length} 处上次没走完的地方。</p>
          )}
        </Card>
      </div>
    </div>
  );
}

function Stat({ n, label }: { n: number; label: string }) {
  return <div className="stat"><strong>{n}</strong><span>{label}</span></div>;
}

/** 地图上的一章：标题 + 状态说明 + 一排单元（点一下进那个单元）。 */
function Chapter({
  ch, busy, onStart, onGoOutline,
}: {
  ch: MapChapter;
  busy: boolean;
  onStart: (unitId: string) => void;
  onGoOutline: () => void;
}) {
  const allDone = ch.nodes.length > 0 && ch.nodes.every((n) => n.state === "mastered");
  return (
    <div className={"map-chapter" + (allDone ? " done" : "")}>
      <div className="map-chapter-head">
        <strong>{ch.title}</strong>
        {ch.subtitle && <span className="muted">{ch.subtitle}</span>}
      </div>
      <div className="map-nodes">
        {ch.nodes.map((n) => {
          const clickable = n.hasContent && (n.state === "available" || n.state === "learning"
            || n.state === "mastered" || n.state === "reviewing");
          return (
            <button
              key={n.id}
              type="button"
              className={"map-node" + (n.kind === "boss" ? " boss" : "") + (n.hasContent ? "" : " nocontent")}
              disabled={busy || !clickable}
              title={
                !n.hasContent
                  ? `${n.title}（还没出内容——去大纲页生成）`
                  : clickable
                    ? `${n.title}（${STATE_ZH[n.state] ?? n.state}）——点一下开始`
                    : `${n.title}（${STATE_ZH[n.state] ?? n.state}）——先把前面的单元学完`
              }
              onClick={() => {
                if (n.hasContent) onStart(n.id);
                else onGoOutline();
              }}
            >
              <i style={{ background: stateColor(n.state) }} />
              {n.kind === "boss" && <span aria-hidden="true">👑</span>}
              <span className="label">{n.title}</span>
              {!n.hasContent && <span className="faint">· 没内容</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}
