// 三种交互模式的练习 UI（docs/07 §1）：workbench 必做，guided/graph 一题演示。
import { useState } from "react";
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

export default function ExercisePanel({ exercise, disabled, feedback, onSubmit }: Props) {
  const mode = renderModeOf(exercise);
  return (
    <div className="card exercise">
      <div className="exercise-head">
        <MdMath text={exercise.prompt} />
        <span className="badge">
          {mode === "graph" ? "图形工具" : mode === "guided" ? "分步引导" : "答题工作台"} · 难度 {exercise.difficulty}
        </span>
      </div>
      {mode === "workbench" && <WorkbenchUI exercise={exercise} disabled={disabled} feedback={feedback} onSubmit={onSubmit} />}
      {mode === "guided" && <GuidedDemo exercise={exercise} disabled={disabled} feedback={feedback} onSubmit={onSubmit} />}
      {mode === "graph" && <GraphDemo exercise={exercise} disabled={disabled} feedback={feedback} onSubmit={onSubmit} />}
    </div>
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
