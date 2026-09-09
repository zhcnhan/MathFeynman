// 学习会话页（docs/07 §2.2 Session）：按后端状态机响应渲染（前端无判断逻辑）。
// R9: AI 等待可感知 —— 首次讲解/提问/提示/费曼评分/重新生成期间显示计时横幅。
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ExerciseView, NodeMeta, StepResponse, postStepStream } from "../api";
import ExercisePanel, { Feedback } from "../components/ExercisePanel";
import { dimLabel } from "../components/feynmanLabels";
import MdMath from "../components/MdMath";
import ModelModeSwitch from "../components/ModelModeSwitch";
import { ModelMode, tierLabel } from "../components/ModelMode";
import TypeMd from "../components/TypeMd";

/** 可能触发 LLM 的动作（等待横幅适用；其余动作仍禁用提交但通常瞬时） */
const AI_ACTIONS = new Set(["ask_question", "regen_explain", "request_hint", "feynman_submit", "feynman_answer"]);

const EVENT_TEXT: Record<string, string> = {
  exercise_correct: "✓ 答对了！继续",
  exercise_wrong: "✗ 答错了，看看提示再试一次",
  practice_passed: "🎉 练习达标（连续 3 对）！进入费曼口述",
  practice_cap_reached: "本轮 5 题未达成 3 连对，请重读讲解后再试",
  relearn_notice: "📖 回炉提示：请重读讲解稿",
  feynman_passed: "🎉 费曼口述通过！",
  feynman_failed: "费曼未达标，回答追问再讲一次",
  feynman_too_short: "口述太短，请完整讲一遍（≥20 字）",
  feynman_deferred: "评分暂不可用，已记录（可稍后人工复核）",
  feynman_relearn: "费曼 3 轮未通过 → 回炉重学",
  node_mastered: "🏆 节点已掌握，进入复习队列",
  hint_given: "💡 已给出提示",
  notation_error: "输入无法解析——请按提示改法（不计错）",
};

export default function SessionPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const [resp, setResp] = useState<StepResponse | null>(null);
  const [nodeMeta, setNodeMeta] = useState<NodeMeta | null>(null);
  const [loading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<StepResponse["events"]>([]);
  const [question, setQuestion] = useState("");
  const [feynmanText, setFeynmanText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [thinkingSince, setThinkingSince] = useState<number | null>(null); // R9 计时
  const [thinkingSecs, setThinkingSecs] = useState(0);
  const [modelMode, setModelMode] = useState<ModelMode>("smart"); // R12
  const [canReissue, setCanReissue] = useState(false); // R25：内容纠错替换成功后允许一键换题
  const [notice, setNotice] = useState<string | null>(null);
  const didInit = useRef(false);
  const didHydrateDraft = useRef(false); // R25：每会话只恢复一次草稿

  // R9：思考计时器（挂起期间每 250ms 刷新秒数）
  useEffect(() => {
    if (thinkingSince === null) return;
    setThinkingSecs(0);
    const t = setInterval(() => setThinkingSecs(Math.floor((Date.now() - thinkingSince) / 1000)), 250);
    return () => clearInterval(t);
  }, [thinkingSince]);

  const withThinking = async <T,>(fn: () => Promise<T>): Promise<T> => {
    setThinkingSince(Date.now());
    try {
      return await fn();
    } finally {
      setThinkingSince(null);
    }
  };

  const refresh = useCallback(async () => {
    try {
      // 首次打开可能触发讲解生成（长等待）→ 计入计时横幅
      const r = await api.get<StepResponse>(`/session/${id}`);
      setResp(r);
      setEvents((prev) => [...prev.slice(-6), ...r.events]);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    void (async () => {
      // 仅首次加载（可能无缓存讲解 → 服务端调用 LLM）开启计时
      await withThinking(() => refresh());
    })();
  }, [refresh]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!resp) return;
    const nid = resp.payload?.node
      ? (resp.payload.node as { id: string }).id
      : resp.session.node_id;
    if (!nid) return;
    api
      .get<NodeMeta>(`/nodes/${nid}`)
      .then(setNodeMeta)
      .catch(() => setNodeMeta(null));
  }, [resp?.session.node_id]); // eslint-disable-line react-hooks/exhaustive-deps

  // R12：读取并维护全局模型模式（⚡快/自动/🧠深度），切换即时持久化
  useEffect(() => {
    api
      .get<{ model_mode?: ModelMode }>("/profile")
      .then((p) => p.model_mode && setModelMode(p.model_mode))
      .catch(() => setModelMode("smart"));
  }, []);

  const changeModelMode = async (mode: ModelMode) => {
    setModelMode(mode);
    try {
      await api.patch("/profile", { model_mode: mode });
    } catch {
      // 失败不回滚 UI（下次请求仍生效前以服务端为准），可重试
    }
  };

  // docs/10 §3 + 工单 B 段：内容纠错反馈 → 复核/自动重生成（auto 节点后台替换后可见处理结果）
  const reportContentIssue = async () => {
    if (!resp) return;
    const kind = step === "explain" ? "lecture" : step === "practice" ? "exercise" : "content";
    const exId = step === "practice" ? String((payload.exercise as ExerciseView | undefined)?.exercise_id ?? "") : undefined;
    const msg = window.prompt(
      "反馈内容问题（讲解错误/题目错误/表述不清等）：",
      exId ? `练习 ${exId}：` : ""
    );
    if (msg === null) return;
    try {
      const posted = await api.post<{ item?: { source?: string }; regen?: { action?: string } }>("/feedback", {
        node_id: session.node_id,
        kind,
        message: msg,
        exercise_id: exId || null,
      });
      // auto 节点 → 后台自动重生成替换：轮询复核队列看处理结果（最多 ~45s）
      if (posted.regen?.action === "regenerating") {
        setNotice("已提交复核，正在自动重生成替换…（可能需 1 分钟，内容较复杂时请耐心）");
        const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
        let final = false;
        for (let i = 0; i < 30 && !final; i++) {
          await sleep(1500);
          try {
            const list = await api.get<{ items: Array<{ status: string; result?: string }> }>(
              `/feedback?node_id=${encodeURIComponent(session.node_id)}`
            );
            const latest = list.items[0];
            if (!latest) continue;
            if (latest.status === "regenerated") {
              final = true;
              // 内容已替换：同步一次会话视图，让用户看到最新内容/题目
              await refresh();
              setCanReissue(true);
              setNotice("✅ 内容已自动重生成替换。若正在做的是旧题，可点下方「🔄 换新题」。");
              return;
            }
            if (latest.status === "failed") {
              final = true;
              setNotice(`❌ 自动重生成失败（原内容保留，待人工）：${(latest.result ?? "").slice(0, 120)}`);
              return;
            }
            if (latest.status === "reviewed") {
              final = true;
              setNotice("已标记复核（人工节点）。");
              return;
            }
            // pending / regenerating：继续等
          } catch {
            break; // 轮询失败不再打扰用户
          }
        }
        if (!final) {
          await refresh();
          setNotice("仍在后台处理（预计 1–2 分钟内完成）。完成后重新进入本节点即可看到新题；结果也可在「费曼复盘/内容反馈」处查看。");
        }
        return;
      }
      if (posted.item?.source === "human") {
        setNotice("已提交复核（本内容为人工精写：仅记录，待人工修订；不会自动修改）。");
      } else {
        setNotice("已提交复核，谢谢反馈！");
      }
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (loading && !resp) return <div className="card">加载会话…</div>;
  if (error) return <div className="card error">会话不可用：{error} <button onClick={() => nav("/")}>回仪表盘</button></div>;
  if (!resp) return null;
  const { step, payload, session } = resp;
  const sidNow = session.id;

  // ---- R25：草稿持久化（离开页面回来不丢输入） ----
  const dkey = (suf: string) => `yanhui:draft:${sidNow}:${suf}`;
  const saveDraft = (suf: string, v: string) => {
    try {
      if (v) localStorage.setItem(dkey(suf), v);
      else localStorage.removeItem(dkey(suf));
    } catch {
      /* 忽略 */
    }
  };
  const setAskDraft = (v: string) => {
    setQuestion(v);
    saveDraft("ask", v);
  };
  const setFeynDraft = (v: string) => {
    setFeynmanText(v);
    saveDraft("feyn", v);
  };

  useEffect(() => {
    if (!didHydrateDraft.current) {
      didHydrateDraft.current = true;
      try {
        const ask = localStorage.getItem(dkey("ask"));
        const fe = localStorage.getItem(dkey("feyn"));
        if (ask) setQuestion(ask);
        if (fe) setFeynmanText(fe);
        // 记录"上次学习"，供仪表盘一键续学
        const nodeLabel =
          (payload?.node as { title?: string } | undefined)?.title ?? session.node_id;
        localStorage.setItem(
          "yanhui:last_session",
          JSON.stringify({ id: sidNow, node: nodeLabel, at: Date.now() })
        );
      } catch {
        /* 忽略 */
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sidNow]);

  const act = async (action: string, body: Record<string, unknown> = {}) => {
    setSubmitting(true);
    setError(null);
    const apply = (r: StepResponse) => {
      setResp(r);
      if (action === "reissue_after_regen") setCanReissue(false);
      setEvents((prev) => [...prev.slice(-6), ...r.events]);
      // 阶段推进时清空交互区；对应草稿一并清除
      if (action !== "feynman_submit" && action !== "feynman_answer") {
        setQuestion("");
        setFeynmanText("");
        try {
          localStorage.removeItem(dkey("ask"));
          localStorage.removeItem(dkey("feyn"));
        } catch {
          /* 忽略 */
        }
      } else {
        try {
          localStorage.removeItem(dkey("feyn")); // 提交即清草稿，下次口述从空开始
        } catch {
          /* 忽略 */
        }
      }
    };
    const run = async () => {
      const r = await api.post<StepResponse>("/session/step", {
        session_id: session.id,
        action,
        payload: body,
      });
      apply(r);
    };
    try {
      if (AI_ACTIONS.has(action)) {
        // R12-b：AI 动作走 SSE 流式；失败自动回退普通 POST（契约=最终仍完整 JSON）
        await withThinking(async () => {
          try {
            const r = await postStepStream(session.id, action, body);
            apply(r);
          } catch {
            await run();
          }
        });
      } else {
        await run();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const feedback: Feedback | null =
    payload.verdict === "correct"
      ? { verdict: "correct", hint: "答对了！" }
      : payload.verdict === "notation"
        ? { verdict: "notation", message: (payload.message as string) ?? "", hint: null }
        : payload.verdict === "wrong"
          ? { verdict: "wrong", hint: (payload.hint_md as string) ?? null, message: (payload.attempts_left as number) !== undefined ? `还可重试 ${payload.attempts_left} 次` : undefined }
          : null;

  const submitAnswer = async (answer: string) => {
    const ex = payload.exercise as ExerciseView;
    await act("submit_exercise", { exercise_id: ex.exercise_id, params_seed: ex.seed, user_answer: answer });
  };

  const exercise = (payload.exercise as ExerciseView) ?? null;
  const progress = (payload.progress as { consecutive_correct?: number; target?: number; issued?: number; cap?: number }) ?? null;

  return (
    <div className="session-page">
      <header className="session-head">
        <button className="ghost" onClick={() => nav("/")} disabled={submitting}>← 退出学习（进度保留）</button>
        <div className="crumbs">
          {nodeMeta ? `${stageLabel(levelName(nodeMeta.level))} → ${nodeMeta.topic} → ${nodeMeta.title}` : session.node_id}
        </div>
        <span className="badge">{STEP_LABEL[step]}</span>
        <ModelModeSwitch value={modelMode} onChange={(m) => void changeModelMode(m)} disabled={submitting} />
        <button className="ghost" disabled={submitting} onClick={() => void reportContentIssue()} title="内容有误？提交纠错反馈（auto 内容会自动重生成替换）">
          内容纠错
        </button>
      </header>

      {notice && <div className="banner ok">{notice}</div>}

      {error && <div className="banner error">{error}</div>}
      {thinkingSince !== null && (
        <div className="banner thinking" role="status">
          ⏳ AI 正在思考… 已用时 {thinkingSecs}s{thinkingSecs >= 10 && "（首次生成讲解/评分可能较慢，请耐心等待）"}
        </div>
      )}
      <div className="event-feed">
        {events.slice(-4).map((e, i) => (
          <div key={i} className={`event ${e.type}`}>{EVENT_TEXT[e.type] ?? e.type}</div>
        ))}
      </div>

      <div className="session-body">
        <main className="session-main">
          {step === "explain" && (
            <ExplainView payload={payload} submitting={submitting} question={question} setQuestion={setAskDraft}
              onAsk={() => act("ask_question", { question })}
              onNext={() => act("next")}
              onRegen={() => act("regen_explain")} />
          )}
          {step === "example" && <ExampleView payload={payload} onNext={() => act("next")} />}
          {step === "practice" && exercise && (
            <div>
              <div className="progress-bar">
                连续答对 {progress?.consecutive_correct ?? 0} / {progress?.target ?? 3} · 本轮已出 {progress?.issued ?? 0} 题
              </div>
              <ExercisePanel exercise={exercise} disabled={submitting} feedback={feedback} onSubmit={submitAnswer} draftPrefix={sidNow} />
            </div>
          )}
          {step === "feynman" && (
            <FeynmanView payload={payload} submitting={submitting} text={feynmanText} setText={setFeynDraft}
              onSubmit={() => act("feynman_submit", { transcript: feynmanText })}
              onAnswerFollowup={() => act("feynman_answer", { answer: feynmanText })} />
          )}
          {step === "done" && <DoneView payload={payload} onHome={() => nav("/")} onHistory={() => nav("/feynman-history")} />}

          <div className="action-row">
            {step === "practice" && canReissue && !submitting && (
              <button className="ghost" disabled={submitting} onClick={async () => { await act("reissue_after_regen"); }}>
                🔄 换新题（已纠错替换）
              </button>
            )}
            {step === "practice" && payload.verdict === "wrong" && !exercise?.interactive.includes("guided") && (
              <button className="ghost" disabled={submitting} onClick={() => act("request_hint", { exercise_id: exercise?.exercise_id, user_answer: "" })}>
                要提示
              </button>
            )}
            {(step === "explain" || step === "practice" || step === "feynman") && (
              <button className="ghost" disabled={submitting} onClick={async () => { await act("finish"); }}>
                结束并查看达标情况
              </button>
            )}
          </div>
        </main>
        <aside className="session-side">
          <div className="card">
            <h2>本节点核心概念</h2>
            {nodeMeta?.core_concepts?.map((c) => <span key={c} className="chip">{c}</span>)}
            {nodeMeta?.objectives && (
              <>
                <h2>学习目标</h2>
                <ul className="objectives">{nodeMeta.objectives.map((o, i) => <li key={i}><MdMath text={o} /></li>)}</ul>
              </>
            )}
            <h2>掌握进度</h2>
            <p>完成「练习 3 连对 + 费曼通过」即掌握本节点并进入复习队列。</p>
          </div>
        </aside>
      </div>
    </div>
  );
}

// ---------- 子视图 ----------
function ExplainView({ payload, submitting, question, setQuestion, onAsk, onNext, onRegen }: any) {
  return (
    <div className="card">
      <h1>{payload?.node?.title}</h1>
      {payload?.strategy && <span className="badge">讲解档位：{tierLabel(payload.strategy as string)}</span>}
      {payload?.degraded && <div className="banner warn">离线模式：展示官方讲解稿原文（联网后获得演绎讲解）</div>}
      <div className="lecture"><TypeMd text={payload?.lecture_md ?? ""} /></div>
      {payload?.asks?.map((a: string, i: number) => (
        <div key={i} className="ask">🤔 <MdMath text={a} /></div>
      ))}
      <div className="ask-box">
        <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={2} placeholder="我没懂，问老师…（白名单内概念）" />
        <button className="primary" disabled={submitting || !question.trim()} onClick={onAsk}>提问</button>
      </div>
      {payload?.answer?.reply_md && <TypeMd text={payload.answer.reply_md} />}
      <div className="input-row">
        <button className="primary" disabled={submitting} onClick={onNext}>明白了，看例题 →</button>
        <button className="ghost" disabled={submitting} onClick={onRegen} title="讲解显示异常（如残留 LaTeX 源码）时，重新生成讲解">
          🔄 重新生成讲解
        </button>
      </div>
    </div>
  );
}

function ExampleView({ payload, onNext }: any) {
  const [open, setOpen] = useState<Record<number, boolean>>({});
  return (
    <div className="card">
      <h1>例题（先自己想，再点开逐步看）</h1>
      {payload?.worked_examples?.map((w: any, i: number) => (
        <div key={i} className="example">
          <MdMath text={w.prompt} />
          <button className="ghost" onClick={() => setOpen((o) => ({ ...o, [i]: !o[i] }))}>
            {open[i] ? "收起步骤" : "展开分步讲解"}
          </button>
          {open[i] && (
            <ol className="steps">
              {w.solution_steps.map((s: string, j: number) => <li key={j}><MdMath text={s} /></li>)}
            </ol>
          )}
        </div>
      ))}
      <button className="primary" onClick={onNext}>开始练习 →</button>
    </div>
  );
}

function FeynmanView({ payload, submitting, text, setText, onSubmit, onAnswerFollowup }: any) {
  const card = payload?.dimension_scores;
  const isFollowup = Boolean(payload?.followup_question && payload?.verdict === "fail");
  return (
    <div className="card feynman">
      <h1>费曼口述环节</h1>
      {payload?.task_prompt && (
        <div className="task-pinned">
          <MdMath text={`**本环节任务（一直有效）**：${payload.task_prompt}`} />
        </div>
      )}
      {payload?.verdict === "deferred" && <div className="banner warn">{payload.message ?? "评分暂不可用，已记录待人工复核。"}</div>}
      {isFollowup && (
        <div className="banner info">💡 你的补充回答会与最初的讲解合并后一起重新评分——请针对追问修正/补全你最初没讲清的地方，而不是另起炉灶。</div>
      )}

      {card ? (
        <div className="score-card">
          <h2>
            综合分 {payload.combined} / 及格 {payload.threshold} · 第 {payload.rounds_done ?? 1} 轮
            {payload.strategy ? <span className="badge tier-badge">本次档位：{tierLabel(payload.strategy as string)}</span> : null}
          </h2>
          {card.map((d: any, i: number) => (
            <div key={i} className="dim">
              <div className="dim-head">
                <strong>{dimLabel(d.key)}</strong> {Math.round(d.score * 100)} 分 · 权重 {d.weight}
              </div>
              <div className="quote">“{d.evidence_quote}”</div>
              <div className="comment"><MdMath text={d.comment} /></div>
            </div>
          ))}
          {isFollowup && (
            <div className="followup">
              <h3>Socratic 追问（回答后进入下一轮评分）</h3>
              <TypeMd text={payload.followup_question} />
            </div>
          )}
        </div>
      ) : null}

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={5}
        placeholder={isFollowup ? "回答上面的追问，尽量用自己的话讲完整（≥20 字）…" : "现在，请你像老师一样把这个概念讲给我听（打字 ≥20 字）…"}
      />
      <div className="input-row">
        {isFollowup ? (
          <button className="primary" disabled={submitting || text.trim().length < 20} onClick={onAnswerFollowup}>
            提交追问回答
          </button>
        ) : (
          <button className="primary" disabled={submitting || text.trim().length < 20} onClick={onSubmit}>
            提交口述
          </button>
        )}
        <span className="hint">口述需 ≥20 字；短于 20 字会被判为敷衍。</span>
      </div>
    </div>
  );
}

function DoneView({ payload, onHome, onHistory }: any) {
  return (
    <div className="card done">
      <h1>🏆 掌握达标</h1>
      <p>本节点已标记 mastered，并已排入 FSRS 复习队列（约 {payload?.mastery?.next_review_due_at ?? "近期"} 到期）。</p>
      <p>费曼综合分：{payload?.mastery?.feynman_score} · 连续答对：{payload?.mastery?.consecutive_correct}</p>
      <div className="input-row">
        <button className="primary" onClick={onHome}>回仪表盘（看看复习与下一步）</button>
        <button className="ghost" onClick={onHistory}>查看费曼复盘记录</button>
      </div>
    </div>
  );
}

const STEP_LABEL: Record<string, string> = {
  explain: "讲解",
  example: "例题",
  practice: "练习",
  feynman: "费曼口述",
  done: "达标",
};

function stageLabel(level: string): string {
  const m: Record<string, string> = { primary: "小学", middle: "初中", high: "高中", college: "大学", ai: "AI 进阶" };
  return m[level] ?? level;
}
function levelName(level: string): string {
  return level;
}
