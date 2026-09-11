// R12：全局模型模式三档即时切换（⚡快 light / 自动 smart / 🧠深度 deep）
// 也导出策略档标签（fast→⚡快 / think→🧠深度），供评分卡/讲解/答疑标注。

export type ModelMode = "smart" | "light" | "deep";

export const MODE_OPTIONS: { value: ModelMode; label: string; title: string }[] = [
  { value: "light", label: "⚡ 快", title: "一直用快模型：更省时间，难题也不换" },
  { value: "smart", label: "自动", title: "默认：一般用快模型，遇到难题和纠错自动换更强的" },
  { value: "deep", label: "🧠 深度", title: "一直用最强的模型：更慢，但更稳" },
];

export function modeLabel(mode: ModelMode): string {
  return MODE_OPTIONS.find((m) => m.value === mode)?.label ?? mode;
}

export function tierLabel(strategy?: string | null): string {
  if (strategy === "think") return "🧠 深度";
  if (strategy === "fast") return "⚡ 快";
  return strategy ? `档位 ${strategy}` : "";
}
