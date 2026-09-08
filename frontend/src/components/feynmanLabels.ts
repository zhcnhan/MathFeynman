// 费曼评分维度 key → 中文标签（docs/09 R9 #5）。未知 key 显示原名。
export const DIMENSION_LABELS: Record<string, string> = {
  correctness: "概念正确性",
  own_words: "用自己的话",
  example_and_edge: "例子与反例",
  self_correction: "自纠能力",
};

export function dimLabel(key: string): string {
  return DIMENSION_LABELS[key] ?? key;
}
