// 三种交互模式的练习 UI（docs/07 §1）+ B2 题型控件（docs/14 §2.5）：
// workbench/guided/graph 沿用既有渲染；按 exercise.mode 提供基础控件——
// single_choice=点选、fill_text=填空输入、boolean_judgment=对/错按钮、numeric 等走 MathInput。
import { ReactNode, useState } from "react";
import { ExerciseView } from "../api";
import MathInput from "./MathInput";
import MdMath from "./MdMath";

export interface Feedback {
  verdict?: "correct" | "wrong" | "notation" | "deferred";
  hint?: string | null;
  message?: string;
}

interface Props {
  exercise: ExerciseView;
  disabled?: boolean;
  feedback?: Feedback | null;
  onSubmit: (answer: string) => void;
}

/** 按 interactive 字段取第一个支持的渲染模式（docs/07 §1 分配规则） */
export function renderModeOf(exercise: ExerciseView): "workbench" | "guided" | "graph" {
  const list = exercise.interactive;
  if (list.includes("workbench")) return "workbench";
  if (list.includes("guided")) return "guided";
  if (list.includes("graph")) return "graph";
  return "workbench";
}

const MODE_LABEL: Record<string, string> = {
  single_choice: "选择题",
  fill_text: "填空题",
  boolean_judgment: "判断题",
  numeric_value: "计算题",
  symbolic_equivalence: "表达式题",
  equation_solution: "解方程",
};

export default function ExercisePanel({ exercise, disabled, feedback, onSubmit }: Props) {
  // B2：按题型渲染基础控件（选择/填空/判断），其余题型沿用交互模式面板
  if (exercise.mode === "single_choice") {
    return <ChoiceUI exercise={exercise} disabled={disabled} feedback={feedback} onSubmit={onSubmit} />;
  }
  if (exercise.mode === "fill_text") {
    return <FillUI exercise={exercise} disabled={disabled} feedback={feedback} onSubmit={onSubmit} />;
  }
  if (exercise.mode === "boolean_judgment") {
    return <BooleanUI exercise={exercise} disabled={disabled} feedback={feedback} onSubmit={onSubmit} />;
  }
  const mode = renderModeOf(exercise);
  return (
    <div className="card exercise">
      <div className="exercise-head">
        <MdMath text={exercise.prompt} />
        <span className="badge">
          {MODE_LABEL[exercise.mode] ?? (mode === "graph" ? "图形工具" : mode === "guided" ? "分步引导" : "答题工作台")} · 难度 {exercise.difficulty}
        </span>
      </div>
      {mode === "workbench" && <WorkbenchUI exercise={exercise} disabled={disabled} feedback={feedback} onSubmit={onSubmit} />}
      {mode === "guided" && <GuidedDemo exercise={exercise} disabled={disabled} feedback={feedback} onSubmit={onSubmit} />}
      {mode === "graph" && <GraphDemo exercise={exercise} disabled={disabled} feedback={feedback} onSubmit={onSubmit} />}
    </div>
  );
}

function ShowPromptAndFeedback({
  exercise,
  feedback,
  children,
}: {
  exercise: ExerciseView;
  feedback?: Feedback | null;
  children: ReactNode;
}) {
  return (
    <div className="card exercise">
      <div className="exercise-head">
        <MdMath text={exercise.prompt} />
        <span className="badge">{MODE_LABEL[exercise.mode] ?? "题目"} · 难度 {exercise.difficulty}</span>
      </div>
      {children}
      {feedback?.verdict === "correct" && <div className="answer">✓ 答对啦，继续加油！</div>}
      {feedback?.hint && <div className="hint">💡 <MdMath text={feedback.hint} /></div>}
    </div>
  );
}

/** 选择题：点选选项（作答=编号文本，服务端判题，答案不泄） */
function ChoiceUI({ exercise, disabled, feedback, onSubmit }: Props) {
  const [chosen, setChosen] = useState<number | null>(null);
  const options = exercise.options ?? [];
  return (
    <ShowPromptAndFeedback exercise={exercise} feedback={feedback}>
      <div className="input-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 6 }}>
        {options.map((opt, i) => (
          <button
            key={i}
            type="button"
            disabled={disabled}
            style={{
              textAlign: "left",
              background: chosen === i ? "#bbdefb" : "#fff",
              border: "1px solid #c5cdd6",
            }}
            onClick={() => {
              setChosen(i);
              onSubmit(String(i + 1));
            }}
          >
            {i + 1}. {opt}
          </button>
        ))}
        {options.length === 0 && <div className="empty">题目缺少选项（请联系内容维护）</div>}
      </div>
    </ShowPromptAndFeedback>
  );
}

/** 填空题：单行输入 */
function FillUI({ exercise, disabled, feedback, onSubmit }: Props) {
  const [value, setValue] = useState("");
  return (
    <ShowPromptAndFeedback exercise={exercise} feedback={feedback}>
      <div className="ask-box">
        <textarea
          value={value}
          placeholder="请输入答案…"
          disabled={disabled}
          onChange={(e) => setValue(e.target.value)}
        />
        <button type="button" className="primary" disabled={disabled || !value.trim()} onClick={() => onSubmit(value)}>
          提交
        </button>
      </div>
    </ShowPromptAndFeedback>
  );
}

/** 判断题：对/错按钮（复用既有语义） */
function BooleanUI({ exercise, disabled, feedback, onSubmit }: Props) {
  return (
    <ShowPromptAndFeedback exercise={exercise} feedback={feedback}>
      <div className="input-row">
        <button type="button" className="primary" disabled={disabled} onClick={() => onSubmit("对")}>对</button>
        <button type="button" className="ghost" disabled={disabled} onClick={() => onSubmit("错")}>错</button>
      </div>
    </ShowPromptAndFeedback>
  );
}

function WorkbenchUI({ exercise, disabled, feedback, onSubmit }: Props) {
  return <MathInput exercise={exercise} disabled={disabled} hint={feedback?.hint} onSubmit={onSubmit} />;
}

const GUIDED_STEPS = [
  "① 理解题意：把已知量与所求量写出来。",
  "② 设未知数：问什么设什么为 x（并写明单位）。",
  "③ 找等量关系并列出方程。",
  "④ 求解、回代检验（结果必须符合题意）。",
];

function GuidedDemo({ exercise, disabled, feedback, onSubmit }: Props) {
  const [step, setStep] = useState(0);
  const steps = GUIDED_STEPS;
  const last = step >= steps.length - 1;
  return (
    <div className="guided">
      <div className="step-panel">
        {steps.slice(0, step + 1).map((s, i) => (
          <div key={i} className={i === step ? "step current" : "step done"}>
            {s}
          </div>
        ))}
      </div>
      {!last && (
        <button type="button" className="primary" onClick={() => setStep((s) => s + 1)}>
          下一步
        </button>
      )}
      {last && (
        <MathInput
          exercise={exercise}
          disabled={disabled}
          hint={feedback?.hint}
          placeholder={exercise.mode === "boolean_judgment" ? "输入 对 或 错" : "输入最终数字"}
          onSubmit={onSubmit}
        />
      )}
    </div>
  );
}

/** GraphDemo：SVG 直线 + 参数滑动条（docs/07 §1c 最小演示）。 */
function GraphDemo({ exercise, disabled, feedback, onSubmit }: Props) {
  const [k, setK] = useState(2);
  const [b, setB] = useState(1);
  const W = 420;
  const H = 260;
  const scale = 22; // px / 单位
  const cx = W / 2;
  const cy = H / 2;

  const toPx = (x: number) => cx + x * scale;
  const toPy = (y: number) => cy - y * scale;
  const x1 = -W / 2 / scale;
  const x2 = W / 2 / scale;
  const linePts = [
    [toPx(x1), toPy(k * x1 + b)],
    [toPx(x2), toPy(k * x2 + b)],
  ] as const;

  return (
    <div className="graph-demo">
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {/* 网格与坐标轴 */}
        {Array.from({ length: 11 }, (_, i) => i - 5).map((g) => (
          <line key={`v${g}`} x1={toPx(g)} y1={0} x2={toPx(g)} y2={H} className="grid" />
        ))}
        {Array.from({ length: 7 }, (_, i) => i - 3).map((g) => (
          <line key={`h${g}`} x1={0} y1={toPy(g)} x2={W} y2={toPy(g)} className="grid" />
        ))}
        <line x1={cx} y1={0} x2={cx} y2={H} stroke="#999" />
        <line x1={0} y1={cy} x2={W} y2={cy} stroke="#999" />
        <line x1={linePts[0][0]} y1={linePts[0][1]} x2={linePts[1][0]} y2={linePts[1][1]} stroke="#1565c0" strokeWidth={3} />
        <circle cx={toPx(0)} cy={toPy(b)} r={4} fill="#d32f2f">
          <title>与 y 轴交点 (0,{b})</title>
        </circle>
        <text x={8} y={18} fontSize={12} fill="#333">y = {k}x {b >= 0 ? `+ ${b}` : `- ${Math.abs(b)}`}</text>
      </svg>
      <div className="slider-rack">
        <label>斜率 k（正/负决定上升/下降）</label>
        <input type="range" min={-3} max={3} step={0.1} value={k} onChange={(e) => setK(Number(e.target.value))} />
        <span>{k.toFixed(1)}</span>
      </div>
      <div className="slider-rack">
        <label>截距 b</label>
        <input type="range" min={-4} max={4} step={0.5} value={b} onChange={(e) => setB(Number(e.target.value))} />
        <span>{b.toFixed(1)}</span>
      </div>
      <div className="observe-tip">观察结论：k&gt;0 上升、k&lt;0 下降、|k| 越大越陡、与 y 轴交于 (0,b)。</div>
      {feedback?.hint && (
        <div className="hint">💡 <MdMath text={feedback.hint} /></div>
      )}
      {exercise.mode === "boolean_judgment" ? (
        <div className="input-row">
          <button type="button" className="primary" disabled={disabled} onClick={() => onSubmit("对")}>
            提交：对
          </button>
          <button type="button" className="primary ghost" disabled={disabled} onClick={() => onSubmit("错")}>
            提交：错
          </button>
        </div>
      ) : (
        <MathInput
          exercise={exercise}
          disabled={disabled}
          hint={feedback?.hint}
          placeholder="输入观察到的数字结论"
          onSubmit={onSubmit}
        />
      )}
    </div>
  );
}
