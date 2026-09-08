# ROADMAP_AUDIT.md — 课程蓝图自动自查报告

> 生成时间：2026-09-08；内容库节点数：13（stages 13，未变）。
> 依据：docs/11 + content/roadmap/REVIEW-blueprint.md（A/B 落实、C 增强）+ docs/12 P1（high 草案）+ P2（college 草案）。
> 用途：供人工精核参考；机械检查（前置存在/锚点存在/无环/主题连续/covered 明细），质量判断仍需人工。
> 条目规模口径：primary 26 / middle 4（首批，REVIEW D 待扩段）/ high 80（P1）/ college 56（P2）；
> docs/12 §5 的 200+/300+ 为含未来细拆的全内容口径，两者口径差异见 IMPLEMENTATION_NOTES 疑点）。

## middle（4 条）

- 自审结论：✅ 通过
- 前置缺失 0 / 锚点缺失 0 / 自指 0 / 环 0 / 正向引用 0

主题分组（按顺序）：
- 代数·数轴与整式初步 ×4（middle.m01 … middle.m04）

covered（锚点已覆盖 2）：
- middle.m01（负数与数轴）-> anchors ['middle.0201']
- middle.m02（有理数的加法）-> anchors ['middle.0202']
待生成 2：
  middle.m03、middle.m04

## primary（26 条）

- 自审结论：✅ 通过
- 前置缺失 0 / 锚点缺失 0 / 自指 0 / 环 0 / 正向引用 0

主题分组（按顺序）：
- 数与运算 ×12（primary.s01 … primary.s23）
- 量与测量 ×3（primary.s11 … primary.s13）
- 图形与几何 ×6（primary.s14 … primary.s25）
- 代数思维 ×1（primary.s18） ⚠️ 孤立单条
- 应用题建模 ×3（primary.s19 … primary.s20）
- 统计与概率 ×1（primary.s21） ⚠️ 孤立单条

covered（锚点已覆盖 4）：
- primary.s05（四则混合运算与运算顺序）-> anchors ['primary.0101']
- primary.s06（分数初步与同分母分数加减）-> anchors ['primary.0102']
- primary.s07（异分母分数加减与约分）-> anchors ['primary.0103']
- primary.s08（分数乘法与倒数初步）-> anchors ['primary.0104']
待生成 22：
  primary.s01、primary.s02、primary.s03、primary.s04、primary.s22、primary.s09、primary.s10、primary.s23、primary.s11、primary.s12、primary.s13、primary.s14、primary.s15、primary.s16、primary.s17、primary.s24、primary.s25、primary.s18、primary.s19、primary.s26、primary.s20、primary.s21

## high（80 条）

- 自审结论：✅ 通过
- 前置缺失 0 / 锚点缺失 0 / 自指 0 / 环 0 / 正向引用 0

主题分组（按顺序）：
- 集合与常用逻辑 ×6（high.h01 … high.h06）
- 等式与不等式 ×7（high.h07 … high.h13）
- 函数 ×17（high.h14 … high.h30）
- 数列 ×6（high.h31 … high.h36）
- 平面向量 ×4（high.h37 … high.h40）
- 立体几何初步 ×7（high.h41 … high.h47）
- 解析几何 ×12（high.h48 … high.h59）
- 导数及其应用 ×9（high.h60 … high.h68）
- 统计与概率 ×12（high.h69 … high.h80）

covered（锚点已覆盖 0）：
- （无：本学段暂无锚点占位条目）
待生成 80：
  high.h01、high.h02、high.h03、high.h04、high.h05、high.h06、high.h07、high.h08、high.h09、high.h10、high.h11、high.h12、high.h13、high.h14、high.h15、high.h16、high.h17、high.h18、high.h19、high.h20、high.h21、high.h22、high.h23、high.h24、high.h25、high.h26、high.h27、high.h28、high.h29、high.h30、high.h31、high.h32、high.h33、high.h34、high.h35、high.h36、high.h37、high.h38、high.h39、high.h40、high.h41、high.h42、high.h43、high.h44、high.h45、high.h46、high.h47、high.h48、high.h49、high.h50、high.h51、high.h52、high.h53、high.h54、high.h55、high.h56、high.h57、high.h58、high.h59、high.h60、high.h61、high.h62、high.h63、high.h64、high.h65、high.h66、high.h67、high.h68、high.h69、high.h70、high.h71、high.h72、high.h73、high.h74、high.h75、high.h76、high.h77、high.h78、high.h79、high.h80

## college（56 条）

- 自审结论：✅ 通过
- 前置缺失 0 / 锚点缺失 0 / 自指 0 / 环 0 / 正向引用 0

主题分组（按顺序）：
- 一元微积分 ×15（college.c01 … college.c15）
- 多元函数微积分 ×9（college.c16 … college.c24）
- 线性代数 ×10（college.c25 … college.c34）
- 概率论与数理统计 ×9（college.c35 … college.c43）
- 离散数学初步 ×7（college.c44 … college.c50）
- 数值计算初步 ×6（college.c51 … college.c56）

covered（锚点已覆盖 0）：
- （无：本学段暂无锚点占位条目）
待生成 56：
  college.c01、college.c02、college.c03、college.c04、college.c05、college.c06、college.c07、college.c08、college.c09、college.c10、college.c11、college.c12、college.c13、college.c14、college.c15、college.c16、college.c17、college.c18、college.c19、college.c20、college.c21、college.c22、college.c23、college.c24、college.c25、college.c26、college.c27、college.c28、college.c29、college.c30、college.c31、college.c32、college.c33、college.c34、college.c35、college.c36、college.c37、college.c38、college.c39、college.c40、college.c41、college.c42、college.c43、college.c44、college.c45、college.c46、college.c47、college.c48、college.c49、college.c50、college.c51、college.c52、college.c53、college.c54、college.c55、college.c56
