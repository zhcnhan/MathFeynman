// 答题工作台输入（docs/07 §1a MathInput/FeedbackLine）：类 LaTeX 简写 + 实时预览 + 符号面板。
import katex from "katex";
import { useEffect, useState } from "react";
import { ExerciseView } from "../api";
import MdMath from "./MdMath";

const SYMBOLS = ["x", "=", "+", "-", "*", "/", "^2", "sqrt()", "()", "pi"];

interface Props {
  exercise: ExerciseView;
  disabled?: boolean;
  onSubmit: (answer: string) => void;
  hint?: string | null;
  placeholder?: string;
  /** 草稿键：非空时输入内容会存 localStorage 并在回到同一题时恢复（离开页面不丢答案）。 */
  draftKey?: string;
}

function readDraft(key?: string): string {
  if (!key) return "";
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

export default function MathInput({ exercise, disabled, onSubmit, hint, placeholder, draftKey }: Props) {
  const [value, setValue] = useState(() => readDraft(draftKey));
  const [previewErr, setPreviewErr] = useState<string | null>(null);

  useEffect(() => {
    // 换题/换种子时重置为（若有）该题草稿
    setValue(readDraft(draftKey));
    setPreviewErr(null);
  }, [exercise.exercise_id, exercise.seed, draftKey]);

  const onInput = (v: string) => {
    setValue(v);
    if (draftKey) {
      try {
        if (v) localStorage.setItem(draftKey, v);
        else localStorage.removeItem(draftKey);
      } catch {
        /* 忽略 */
      }
    }
  };

  const previewHtml = () => {
    const text = value.trim();
    if (!text) return "";
    const tex = `\\text{${text.replace(/\*/g, "\\times ").replace(/\^2/g, "^{2}")}}`;
    try {
      return katex.renderToString(tex, { throwOnError: true, displayMode: false, strict: false });
    } catch {
      setPreviewErr("输入无法预览——提交后后端会校验；答错记 notation 提示改法，不判错。");
      return "";
    }
  };

  const submit = () => {
    if (!value.trim() || disabled) return;
    onSubmit(value.trim());
  };

  const isBoolean = exercise.mode === "boolean_judgment";
  return (
    <div className="math-input">
      <div className="symbols">
        {SYMBOLS.map((s) => (
          <button key={s} type="button" disabled={disabled} onClick={() => setValue((v) => v + s.replace("()", "(") + (s.endsWith("()") ? ")" : ""))}>
            {s}
          </button>
        ))}
        {isBoolean && (
          <>
            <button type="button" disabled={disabled} onClick={() => setValue("对")}>对</button>
            <button type="button" disabled={disabled} onClick={() => setValue("错")}>错</button>
          </>
        )}
      </div>
      {!isBoolean && (
        <div className="preview" dangerouslySetInnerHTML={{ __html: previewHtml() || '<span class="preview-empty">（实时预览）</span>' }} />
      )}
      {previewErr && <div className="error-text">{previewErr}</div>}
      <textarea
        value={value}
        disabled={disabled}
        onChange={(e) => {
          onInput(e.target.value);
          setPreviewErr(null);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        placeholder={placeholder ?? (isBoolean ? "输入 对 或 错" : "输入答案，如 x=5 或 5")}
        rows={2}
      />
      <div className="input-row">
        <button type="button" className="primary" disabled={disabled || !value.trim()} onClick={submit}>
          提交
        </button>
        {hint && (
          <span className="hint">
            💡 <MdMath text={hint} />
          </span>
        )}
      </div>
    </div>
  );
}
