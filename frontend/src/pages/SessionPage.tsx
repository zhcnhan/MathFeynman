// 学习会话页（docs/07 §2.2 Session）：按后端状态机响应渲染（前端无判断逻辑）。
// R9: AI 等待可感知 —— 首次讲解/提问/提示/费曼评分/重新生成期间显示计时横幅。
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ChallengeView, ExerciseView, FeynmanGapUpdate, FeynmanLedger, NodeMeta, ReteachPayload, StepResponse, postStepStream } from "../api";
import ExercisePanel, { Feedback } from "../components/ExercisePanel";
import { dimLabel } from "../components/feynmanLabels";
import MdMath from "../components/MdMath";
import ModelModeSwitch from "../components/ModelModeSwitch";
import { ModelMode, tierLabel } from "../components/ModelMode";
import TypeMd from "../components/TypeMd";

/** 可能触发 LLM 的动作（等待横幅适用；其余动作仍禁用提交但通常瞬时） */
const AI_ACTIONS = new Set(["ask_question", "regen_explain", "request_hint", "feynman_submit", "feynman_answer", "challenge_start", "challenge_submit"]);

const EVENT_TEXT: Record<string, string> = {
  exercise_correct: "✓ 答对了！继续",
  exercise_wrong: "✗ 答错了，看看提示再试一次",
  practice_passed: "🎉 练习达标（连续 3 对）！进入费曼口述",
  practice_cap_reached: "本轮 5 题未达成 3 连对，请重读讲解后再试",
  relearn_notice: "📖 需要重学：请再读一遍讲解",
  feynman_passed: "🎉 费曼口述通过！",
  feynman_failed: "费曼未达标，按缺口提示补答或整合重讲",
  feynman_followup: "💡 已按你的最弱缺口给出定向追问",
  feynman_gap_filled: "✅ 补上了，分数已更新",
  feynman_gap_open: "还没补上：再完整讲一遍后，会针对这一点再问",
  feynman_evidence_flagged: "⚠️ 有的评分引用了你这次没说过的话，已按更稳妥的方式重新评（不给没依据的分）",
  feynman_too_short: "口述太短，请完整讲一遍（≥20 字）",
  feynman_deferred: "评分暂不可用，已记录（可稍后人工复核）",
  feynman_relearn: "费曼机会用完了还没通过，需要重新学一遍",
  feynman_edge_recheck: "⚖️ 本次接近及格线，已用更认真的档位复核一遍（取较高分）",
  feynman_answer_too_short: "补答太短，请具体回答追问里要你补讲的那一点",
  // R35 S4：无可引用内容 → 退回讲解补讲（不发无法回答的追问）
  feynman_reteach: "📖 这次没有可追问的实质内容 → 已退回讲解补讲（不扣分、不耗额度）",
  // R35 S3：挑战题池（完全不上算）
  challenge_offered: "🎲 挑战题已生成（需要讲解之外的知识；答不出不影响任何进度）",
  challenge_begin: "开始作答挑战题（不影响任何进度）",
  challenge_graded: "挑战题已判分（只记复盘，不影响任何进度）",
  challenge_cancelled: "已取消本次挑战（什么都没记）",
  challenge_abandoned: "已放弃这道挑战题（只记复盘）",
  node_mastered: "🏆 这个知识点学会了，已排进复习",
  hint_given: "💡 已给出提示",
  notation_error: "输入看不懂——照提示改一下写法就行（不算错）",
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
  // R35 S3：挑战题池（**与默认流程完全分离**：只在用户点「挑战一下」后才出现）
  const [challenge, setChallenge] = useState<ChallengeView | null>(null);
  const [challengeAnswer, setChallengeAnswer] = useState("");
  const [reteach, setReteach] = useState<ReteachPayload | null>(null); // R35 S4：退回讲解补讲
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

  // R25：草稿持久化——必须在所有提前 return 之前声明（Hooks 顺序恒定）。
  // resp 就绪后恢复上次输入 + 记录"上次学习"；每会话只恢复一次。
  useEffect(() => {
    if (!resp || didHydrateDraft.current) return;
    didHydrateDraft.current = true;
    try {
      const session = resp.session;
      const dkey = (suf: string) => `yanhui:draft:${session.id}:${suf}`;
      const ask = localStorage.getItem(dkey("ask"));
      const fe = localStorage.getItem(dkey("feyn"));
      if (ask) setQuestion(ask);
      if (fe) setFeynmanText(fe);
      const nodeTitle = (resp.payload?.node as { title?: string } | undefined)?.title;
      localStorage.setItem(
        "yanhui:last_session",
        JSON.stringify({ id: session.id, node: nodeTitle ?? session.node_id, at: Date.now() })
      );
    } catch {
      /* 忽略 */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resp]);

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

  // R54 A：内容不足时的一键生成（走既有的"单元出稿"入口；生成完就地重取会话继续）
  const generateContent = async () => {
    const info = (payload?.content_missing ?? {}) as { subject_id?: string; unit_id?: string };
    if (!info.subject_id || !info.unit_id) {
      setError("这个单元的内容由系统按课程安排生成，请稍后再试。");
      return;
    }
    setSubmitting(true);
    setError("");
    setNotice("");
    try {
      const r = await api.post<{ status: string; note?: string }>(
        `/subjects/${info.subject_id}/units/${info.unit_id}/content`, {}
      );
      setNotice(
        r.status === "created" || r.status === "exists"
          ? "内容已生成，正在回到学习…"
          : `生成结果：${r.status}${r.note ? ` · ${r.note}` : ""}`
      );
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
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
              setNotice("已标记为人工复核。");
              return;
            }
            // pending / regenerating：继续等
          } catch {
            break; // 轮询失败不再打扰用户
          }
        }
        if (!final) {
          await refresh();
          setNotice("还在后台处理，大约 1–2 分钟。完成后重新进入这里就能看到新题；也可以在「费曼复盘 / 内容反馈」里看结果。");
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

  const act = async (action: string, body: Record<string, unknown> = {}) => {
    setSubmitting(true);
    setError(null);
    const apply = (r: StepResponse) => {
      setResp(r);
      if (action === "reissue_after_regen") setCanReissue(false);
      setEvents((prev) => [...prev.slice(-6), ...r.events]);
      // R35 S3：挑战题视图**只随 challenge_* 动作下发**（默认流程 payload 里没有它）
      if (r.payload?.challenge) setChallenge(r.payload.challenge as ChallengeView);
      // R35 S4：reteach（退回讲解补讲）；换阶段/新提交时清掉
      if (r.payload?.reteach) setReteach(r.payload.reteach as ReteachPayload);
      else if (action === "feynman_submit" || action === "feynman_answer") setReteach(null);
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
        <button className="ghost" disabled={submitting} onClick={() => void reportContentIssue()} title="内容有问题？点这里反馈（AI 生成的内容会自动重做）">
          内容纠错
        </button>
      </header>

      {notice && <div className="banner ok">{notice}</div>}
      {/* R54 A：被守卫退回/需要先看讲解 → 中文说明（不是报错） */}
      {!!payload?.rewound_zh && <div className="banner warn">{String(payload.rewound_zh)}</div>}

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
            <FeynmanView
              payload={payload}
              submitting={submitting}
              text={feynmanText}
              setText={setFeynDraft}
              onSubmit={() => act("feynman_submit", { transcript: feynmanText })}
              onAnswerFollowup={() => act("feynman_answer", { answer: feynmanText })}
            />
          )}
          {step === "done" && <DoneView payload={payload} onHome={() => nav("/")} onHistory={() => nav("/feynman-history")} />}
          {/* R54 A：内容不足 → 不给学习步骤、不给作答入口，只说清缺什么 + 一键生成 */}
          {step === "content_missing" && (
            <ContentMissingView
              info={payload.content_missing}
              busy={submitting}
              onGenerate={() => void generateContent()}
              onRetry={() => void refresh()}
              onHome={() => nav("/")}
            />
          )}

          {/* R35 S4：追问无据/学生无可引用内容 → 退回讲解补讲（不发无法回答的追问） */}
          {reteach && (
            <div className="card reteach">
              <h2>返回讲解补讲</h2>
              <div className="banner warn"><TypeMd text={reteach.message_md} /></div>
              {reteach.missing_dimensions?.length > 0 && (
                <ul className="objectives">
                  {reteach.missing_dimensions.map((g) => (
                    <li key={g.key}>还差：<strong>{dimLabel(g.key)}</strong>——<MdMath text={g.description} /></li>
                  ))}
                </ul>
              )}
              {reteach.lecture_md && <div className="lecture"><TypeMd text={reteach.lecture_md} /></div>}
            </div>
          )}

          {/* R35 S3：挑战题池（用户主动触发；**永不出现在默认流程**） */}
          {challenge?.question && (
            <ChallengePanel
              view={challenge}
              answer={challengeAnswer}
              setAnswer={setChallengeAnswer}
              submitting={submitting}
              onBegin={() => act("challenge_begin")}
              onSubmit={() => act("challenge_submit", { answer: challengeAnswer })}
              onCancel={() => { setChallengeAnswer(""); void act("challenge_cancel"); }}
              onAbandon={() => { setChallengeAnswer(""); void act("challenge_abandon"); }}
            />
          )}

          <div className="action-row">
            {/* R35 S3：「挑战一下」——用户主动触发、单独调模型生成；默认流程里没有它 */}
            {challenge?.question ? (
              <button className="ghost" disabled={submitting} onClick={() => { setChallengeAnswer(""); void act("challenge_cancel"); }}>
                关闭挑战题
              </button>
            ) : (
              <button className="ghost" disabled={submitting} onClick={() => void act("challenge_start")}
                title="单独生成一道需要讲解之外知识的题；答不出不影响任何进度">
                {submitting ? "生成中…" : "🎲 挑战一下"}
              </button>
            )}
            {step === "practice" && canReissue && (
              <button className="ghost" disabled={submitting} onClick={async () => { await act("reissue_after_regen"); }}>
                {submitting ? "♻️ 换题中…" : "🔄 换新题（已纠错替换）"}
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
            <h2>这个知识点的核心概念</h2>
            {nodeMeta?.core_concepts?.map((c) => <span key={c} className="chip">{c}</span>)}
            {nodeMeta?.objectives && (
              <>
                <h2>学习目标</h2>
                <ul className="objectives">{nodeMeta.objectives.map((o, i) => <li key={i}><MdMath text={o} /></li>)}</ul>
              </>
            )}
            <h2>掌握进度</h2>
            <p>连续答对 3 题、再把费曼口述讲通过，就算学会了这个知识点，之后会定期提醒你复习。</p>
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

/** R54 A：内容不足卡片——说清缺什么，给一键生成；不给学习步骤、不给作答入口。 */
function ContentMissingView({ info, busy, onGenerate, onRetry, onHome }: any) {
  const title = info?.node_title || info?.node_id || "这个单元";
  const canGenerate = !!info?.can_generate;
  return (
    <div className="card" style={{ borderColor: "#e6a23c" }}>
      <h2 style={{ marginTop: 0 }}>先补上内容，再开始学</h2>
      <div className="banner warn">{info?.reason_zh || "这个单元还没有内容。"}</div>
      <ul className="objectives">
        <li>单元：<strong>{title}</strong></li>
        {typeof info?.content_status?.exercises === "number" && (
          <li>现有练习：{info.content_status.exercises} 道
            {info.content_status.dropped_exercises > 0
              ? `（另有 ${info.content_status.dropped_exercises} 道因找不到教材依据没有采用）` : ""}
          </li>
        )}
        <li>内容一律以你导入的教材为准；教材里找不到依据的，程序不会编造（所以可能用不上）。</li>
      </ul>
      <div className="input-row">
        {canGenerate ? (
          <button className="primary" disabled={busy} onClick={onGenerate}>
            {busy ? "正在生成…" : "生成这个单元的内容"}
          </button>
        ) : (
          <span className="dim">这个单元的内容由系统按课程安排生成，暂时不需要手动生成。</span>
        )}
        <button className="ghost" disabled={busy} onClick={onRetry}>重新检查</button>
        <button className="ghost" disabled={busy} onClick={onHome}>回仪表盘</button>
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

/**
 * 费曼视图（docs/07 + docs/09 R27 v3 混合制）。
 *
 * 双提交入口：
 *  - 有追问时：主按钮「回答追问」= feynman_answer（补答，只涨账本）；副按钮「整合后完整重讲」
 *    = feynman_submit（完整稿终验，唯一能过关的提交）；
 *  - 无追问时：「提交讲解」= feynman_submit。
 * 实时得分条：各维度账本分（历轮最高分）+ 缺口提示（还差什么）+ 综合分/门槛进度条；
 * 答追问后立即刷新（学生能看见涨分）。
 */
function FeynmanView({ payload, submitting, text, setText, onSubmit, onAnswerFollowup }: any) {
  const card = payload?.dimension_scores as Array<Record<string, any>> | undefined;
  const ledger = payload?.ledger as FeynmanLedger | undefined;
  const gaps = ledger?.gaps ?? [];
  const followup = payload?.followup_question as string | undefined;
  const hasFollowup = Boolean(followup);
  const evalsDone = Number(payload?.evals_done ?? payload?.rounds_done ?? 0);
  const evalBudget = Number(payload?.eval_budget ?? 3);
  const answersDone = Number(payload?.answers_done ?? 0);
  const answerBudget = Number(payload?.answer_budget ?? 2);
  const threshold = Number(payload?.threshold ?? payload?.pass_threshold ?? 0.7);
  const combined = Number(payload?.combined ?? ledger?.combined ?? 0);
  const gapUpdate = payload?.gap_update as FeynmanGapUpdate | null | undefined;
  const gapAnswered = payload?.verdict === "gap";
  const tooShort = text.trim().length < 20;

  return (
    <div className="card feynman">
      <h1>费曼口述环节</h1>
      {payload?.task_prompt && (
        <div className="task-pinned">
          <MdMath text={`**本环节任务（一直有效）**：${payload.task_prompt}`} />
        </div>
      )}
      {payload?.verdict === "deferred" && <div className="banner warn">{payload.message ?? "评分暂不可用，已记录待人工复核。"}</div>}

      {/* ---- R27：实时得分条（账本维度分 + 缺口提示 + 综合分/门槛进度条） ---- */}
      {ledger && (
        <div className="score-board">
          <div className="score-board-head">
            实时得分（各维度取历轮最好成绩）
            <span className="badge">整体稿（首讲+终验）：{evalsDone}/{evalBudget}</span>
            <span className="badge">补答：{answersDone}/{answerBudget}</span>
            {payload?.strategy ? <span className="badge tier-badge">本次档位：{tierLabel(payload.strategy as string)}</span> : null}
          </div>
          {ledger.dimensions.map((d) => (
            <div key={d.key} className="dim-bar">
              <span className="dim-bar-label">{dimLabel(d.key)}</span>
              <span className="dim-bar-track">
                <span
                  className={`dim-bar-fill ${d.score >= threshold ? "ok" : "low"}`}
                  style={{ width: `${Math.round(Math.min(1, Math.max(0, d.score)) * 100)}%` }}
                />
                <span className="dim-bar-threshold" style={{ left: `${Math.round(threshold * 100)}%` }} />
              </span>
              <span className="dim-bar-score">{Math.round(d.score * 100)}</span>
            </div>
          ))}
          <div className="dim-bar overall">
            <span className="dim-bar-label">综合分</span>
            <span className="dim-bar-track">
              <span
                className={`dim-bar-fill ${combined >= threshold ? "ok" : "low"}`}
                style={{ width: `${Math.round(Math.min(1, Math.max(0, combined)) * 100)}%` }}
              />
              <span className="dim-bar-threshold" style={{ left: `${Math.round(threshold * 100)}%` }} />
            </span>
            <span className="dim-bar-score">
              {Math.round(combined * 100)} / 门槛 {Math.round(threshold * 100)}
            </span>
          </div>
          {gaps.length > 0 ? (
            <div className="gap-list">
              {gaps.map((g) => (
                <div key={g.key} className="gap">
                  还差：<strong>{dimLabel(g.key)}</strong>——<MdMath text={g.description} />
                </div>
              ))}
            </div>
          ) : (
            <div className="gap-list all-clear">✅ 已无未达标维度：把整段讲解完整讲一遍即可终验。</div>
          )}
        </div>
      )}

      {/* ---- 补答结果（答追问后立刻可见涨分） ---- */}
      {gapAnswered && (
        <div className={`banner ${payload?.gap_filled ? "ok" : "warn"}`}>
          <div>{payload?.message}</div>
          {gapUpdate && (
            <div className="gap-delta">
              <strong>{dimLabel(gapUpdate.key)}</strong>：{Math.round(gapUpdate.score * 100)} 分
              {gapUpdate.evidence_valid ? (
                <span className="quote"> “{gapUpdate.evidence_quote}”</span>
              ) : (
                <span className="quote-warn"> 引文未通过本轮文本校验（已降级）：{gapUpdate.evidence_reason}</span>
              )}
            </div>
          )}
        </div>
      )}

      {card ? (
        <div className="score-card">
          <h2>
            本轮评分卡（整体稿）· 第 {evalsDone || 1} 轮
            {payload.strategy ? <span className="badge tier-badge">本次档位：{tierLabel(payload.strategy as string)}</span> : null}
          </h2>
          {payload?.evidence_penalty && (
            <div className="banner warn">
              ⚠️ 部分维度的引文不在本轮提交文本中，服务端已降级该维度分数（防"没读新内容还打分"）。
            </div>
          )}
          {card.map((d: any, i: number) => (
            <div key={i} className="dim">
              <div className="dim-head">
                <strong>{dimLabel(d.key)}</strong> {Math.round(d.score * 100)} 分 · 权重 {d.weight}
                {d.evidence_valid === false && <span className="badge warn-badge">引用的原话对不上</span>}
              </div>
              <div className="quote">“{d.evidence_quote}”</div>
              <div className="comment"><MdMath text={d.comment} /></div>
              {d.evidence_valid === false && d.evidence_reason && (
                <div className="comment warn-text">{d.evidence_reason}</div>
              )}
            </div>
          ))}
        </div>
      ) : null}

      {hasFollowup && (
        <div className="followup">
          <h3>定向追问（就这一个缺口，答完即可看到涨分）</h3>
          {/* R35 S4：追问必须**逐字引用学生刚说的话**，并指出"这句话缺了什么" */}
          {payload?.followup_quote ? (
            <div className="quote">你刚才说：「{payload.followup_quote as string}」</div>
          ) : null}
          {payload?.followup_missing ? (
            <div className="gap">这句话缺的是：<MdMath text={payload.followup_missing as string} /></div>
          ) : null}
          <TypeMd text={followup!} />
          {payload?.followup_gap?.description && (
            <div className="gap">缺口：<MdMath text={payload.followup_gap.description} /></div>
          )}
        </div>
      )}

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={5}
        placeholder={
          hasFollowup
            ? "回答上面的追问，只讲这一点也行（≥20 字）…"
            : "现在，请你像老师一样把这个概念**完整**讲给我听（打字 ≥20 字）…"
        }
      />
      <div className="input-row">
        {hasFollowup ? (
          <>
            <button className="primary" disabled={submitting || tooShort} onClick={onAnswerFollowup}>
              {submitting ? "提交中…" : "回答追问（补答）"}
            </button>
            <button className="ghost" disabled={submitting || tooShort} onClick={onSubmit}
              title="把已补上的内容整合进完整讲解，做整体终验（只有完整稿达标才算通过）">
              {submitting ? "提交中…" : "整合后完整重讲（终验）"}
            </button>
          </>
        ) : (
          <button className="primary" disabled={submitting || tooShort} onClick={onSubmit}>
            {submitting ? "提交中…" : "提交讲解"}
          </button>
        )}
        <span className="hint">
          口述需 ≥20 字。补答只涨账本可见分；**通过必须交完整稿**（≥{Math.round(threshold * 100)} 分）。
        </span>
      </div>
    </div>
  );
}

/**
 * R35 S3：挑战题面板（**完全不上算**）。
 *
 * - 单题三态**都要能点、都要无后果**：开始作答 / 取消 / 明确放弃；
 * - 顶部**显式标注**（后端直出 `notice`）："挑战题：需要讲解之外的知识，答不出不影响任何进度"；
 * - 不显示任何进度/额度/分数影响（`counts_nothing`），判分结果只作复盘展示。
 */
function ChallengePanel({ view, answer, setAnswer, submitting, onBegin, onSubmit, onCancel, onAbandon }: any) {
  const q = view?.question;
  const last = view?.last;
  const answering = view?.phase === "answering" || view?.phase === "graded";
  return (
    <div className="card challenge">
      <h2>🎲 挑战题</h2>
      <div className="banner warn">{view?.notice}</div>
      {q?.why_hard_md ? <div className="comment"><MdMath text={q.why_hard_md} /></div> : null}
      <div className="prompt"><MdMath text={q?.prompt_md ?? ""} /></div>
      {q?.answer_hint_md ? <div className="hint">作答提示：{q.answer_hint_md}</div> : null}

      {!answering ? (
        <div className="input-row">
          <button className="primary" disabled={submitting} onClick={onBegin}>开始作答</button>
          <button className="ghost" disabled={submitting} onClick={onCancel}>取消（放弃本次，无任何后果）</button>
          <button className="ghost" disabled={submitting} onClick={onAbandon}>明确放弃（我不会/我不感兴趣）</button>
        </div>
      ) : (
        <>
          <textarea value={answer} onChange={(e) => setAnswer(e.target.value)} rows={4}
            placeholder="说说你的判断与理由（挑战题没有标准答案；答不出也不影响进度）…" />
          <div className="input-row">
            <button className="primary" disabled={submitting || !answer.trim()}
              onClick={onSubmit}>{submitting ? "判分中…" : "提交挑战题作答"}</button>
            <button className="ghost" disabled={submitting} onClick={onCancel}>取消</button>
            <button className="ghost" disabled={submitting} onClick={onAbandon}>明确放弃</button>
          </div>
        </>
      )}

      {last && (
        <div className={`banner ${last.correct ? "ok" : "warn"}`}>
          <div><TypeMd text={last.feedback_md} /></div>
          {last.better_md ? <div className="comment">参考思路：<TypeMd text={last.better_md} /></div> : null}
          <div className="hint">这次只是练手：不计入掌握进度，也不占费曼机会。</div>
        </div>
      )}
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
