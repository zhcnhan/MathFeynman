// 轻量 Markdown + LaTeX 渲染（docs/07 §3；R8 容忍式重写）
// 目标：对 LLM 输出的"脏 LaTeX"尽量正确渲染而不是显示源码——
//   - $$...$$ 显示公式：容忍跨行、出现在行中，非贪婪配对
//   - $...$ 行内公式：容忍内容含换行；含中文/过长的片段不视为数学
//   - 孤立杂散 $$ 自动清理；KaTeX 失败才降级为 <code> 原文
import katex from "katex";
import "katex/dist/katex.min.css";

const esc = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** 去杂散 $$、压缩空白后交给 KaTeX。 */
const cleanTex = (s: string) => s.replace(/\$\$/g, "").replace(/\s+/g, " ").trim();

function renderTex(tex: string, display: boolean): string {
  const cleaned = cleanTex(tex);
  if (!cleaned) return "";
  try {
    return katex.renderToString(cleaned, { throwOnError: false, displayMode: display, strict: false });
  } catch {
    return `<code>${esc(cleaned)}</code>`;
  }
}

const hasCjk = (s: string) => /[\u4e00-\u9fff]/.test(s);

const BLOCK = "\u0000"; // 显示公式占位
const INLINE = "\u0001"; // 行内公式占位

/**
 * 把行内占位（行内公式 / 行中出现的显示公式）渲染为 KaTeX HTML；文本部分转义 + 支持 **bold**。
 */
function mdText(line: string, inlineHtml: string[], blockInline: string[]): string {
  const escBold = (t: string) => esc(t).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  let html = escBold(line);
  html = html.replace(new RegExp(`${INLINE}(\\d+)${INLINE}`, "g"), (_m, d: string) => inlineHtml[Number(d)] ?? "");
  html = html.replace(new RegExp(`${BLOCK}(\\d+)${BLOCK}`, "g"), (_m, d: string) => blockInline[Number(d)] ?? "");
  return html;
}

/** 主渲染：整段 → HTML 行序列。 */
function render(src: string): string {
  const blocks: string[] = [];
  // 1) 显示公式 $$...$$：先于行内提取（非贪婪、容忍跨行/行中）
  const noBlocks = src.replace(/\$\$([\s\S]*?)\$\$/g, (_m, inner: string) => {
    blocks.push(inner);
    return `${BLOCK}${blocks.length - 1}${BLOCK}`;
  });
  // 2) 清理残余孤立 $$
  const noStray = noBlocks.replace(/\$\$/g, "");
  // 3) 行内 $...$：允许内容含换行；中文/超长不当作数学
  const inlineHtml: string[] = [];
  const noInline = noStray.replace(/\$([^$]*?)\$/g, (_m, inner: string) => {
    const t = inner.replace(/\s+/g, " ");
    if (!t || t.length > 160 || hasCjk(t)) {
      return _m; // 保持原样（可能只是文本里的 $）
    }
    inlineHtml.push(renderTex(t, false));
    return `${INLINE}${inlineHtml.length - 1}${INLINE}`;
  });
  // 4) 行内出现的显示公式占位（$$ 与文字同行）→ 段落内以行内模式渲染，避免漏显示
  const blockInline: string[] = blocks.map((inner) => renderTex(inner, false));

  const out: string[] = [];
  const lines = noInline.split(/\n/);
  let i = 0;
  while (i < lines.length) {
    const raw = lines[i];
    const t = raw.trim();
    if (!t) { i += 1; continue; }
    // 显示公式占位独占一行 → 独立块
    const bm = t.match(new RegExp(`^${BLOCK}(\\d+)${BLOCK}$`));
    if (bm) {
      out.push(`<div class="math-block">${renderTex(blocks[Number(bm[1])], true)}</div>`);
      i += 1;
      continue;
    }
    const listBuf: string[] = [];
    const flushList = () => {
      if (listBuf.length) out.push(`<ul>${listBuf.join("")}</ul>`);
      listBuf.length = 0;
    };
    if (t.startsWith("### ")) out.push(`<h3>${mdText(t.slice(4), inlineHtml, blockInline)}</h3>`);
    else if (t.startsWith("## ")) out.push(`<h2>${mdText(t.slice(3), inlineHtml, blockInline)}</h2>`);
    else if (t.startsWith("# ")) out.push(`<h1>${mdText(t.slice(2), inlineHtml, blockInline)}</h1>`);
    else if (t.startsWith("- ") || /^\d+[.、] /.test(t)) {
      while (i < lines.length) {
        const tt = lines[i].trim();
        if (!tt) { i += 1; break; }
        if (tt.startsWith("- ")) { listBuf.push(`<li>${mdText(tt.replace(/^- /, ""), inlineHtml, blockInline)}</li>`); i += 1; continue; }
        if (/^\d+[.、] /.test(tt)) { listBuf.push(`<li>${mdText(tt.replace(/^\d+[.、] /, ""), inlineHtml, blockInline)}</li>`); i += 1; continue; }
        break;
      }
      flushList();
      continue;
    } else {
      out.push(`<p>${mdText(raw, inlineHtml, blockInline)}</p>`);
    }
    i += 1;
  }
  return out.join("");
}

export default function MdMath({ text, className }: { text: string; className?: string }) {
  return <div className={className} dangerouslySetInnerHTML={{ __html: render(String(text ?? "")) }} />;
}
