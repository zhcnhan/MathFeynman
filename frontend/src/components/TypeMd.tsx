// R12-b：轻量打字机渲染 —— 文本到达后逐段揭示（讲解/答疑/追问的长文本适用）。
// key = 文本内容本身：同一文本再次渲染不重播；新 AI 回复（新文本）自动打字。
import { useEffect, useState } from "react";
import MdMath from "./MdMath";

export default function TypeMd({ text, maxDurationMs = 1100 }: { text: string; maxDurationMs?: number }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const total = text.length;
    setN(0);
    if (total <= 24) {
      setN(total);
      return;
    }
    const dur = Math.min(maxDurationMs, 260 + total * 1.6);
    const step = Math.max(2, Math.ceil(total / (dur / 16)));
    const t = setInterval(() => setN((x) => Math.min(total, x + step)), 16);
    return () => clearInterval(t);
  }, [text, maxDurationMs]);
  return <MdMath text={text.slice(0, n)} />;
}
