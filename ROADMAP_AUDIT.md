# ROADMAP_AUDIT.md — 课程蓝图自动自查报告

> 生成时间：2026-09-08（C 段 middle 全段扩段后再生）；内容库节点数：13（stages 13，未变）。
> 依据：docs/11 + content/roadmap/REVIEW-blueprint.md + REVIEW2-master.md（R15 精核补丁批）+ docs/12 P1–P3 + R14 后续#1（跨学段 prereq）+ 工单 C 段（middle 全段）。
> 用途：供人工精核参考；机械检查（前置存在/锚点存在/跨学段方向/无环/主题连续/covered 明细），质量判断仍需人工。
> 条目规模口径：primary 27（R18 阶段2 +s27 因数倍数线）/ middle 31（C 段全段扩段）/ high 81（R15 +h40b 复数）/ college 59（R15 +c34b/c43b + D 段 c15b）/ ai 60（R15 +a04b/a17b/a25b）；
> docs/12 §5 的 200+/300+/150+ 为含未来细拆的全内容口径，两者口径差异见 IMPLEMENTATION_NOTES 疑点）。

## middle（31 条）

- 自审结论：✅ 通过
- 前置缺失 0 / 锚点缺失 0 / 自指 0 / 环 0 / 正向引用 0
- 跨学段引用 1（前序学段）/ 反向 0 / 未落地缺口提示 1（提示不阻塞，学段顺序兜底）

主题分组（按顺序）：
- 代数·数轴与整式初步 ×4（middle.m01 … middle.m04）
- 代数·有理数与实数 ×6（middle.m05 … middle.m10）
- 代数·方程不等式与方程组 ×9（middle.m11 … middle.m19）
- 图形与几何·平面初步 ×5（middle.m20 … middle.m24）
- 代数·函数初步 ×4（middle.m25 … middle.m28）
- 统计与概率初步 ×3（middle.m29 … middle.m31）

covered（锚点已覆盖 6）：
- middle.m01（负数与数轴）-> anchors ['middle.0201']
- middle.m02（有理数的加法）-> anchors ['middle.0202']
- middle.m11（一元一次方程的概念）-> anchors ['middle.0101']
- middle.m12（等式的性质）-> anchors ['middle.0104']
- middle.m13（解一元一次方程（移项·去括号去分母））-> anchors ['middle.0102']
- middle.m14（一元一次方程的应用）-> anchors ['middle.0103']
待生成 25：
  middle.m03、middle.m04、middle.m05、middle.m06、middle.m07、middle.m08、middle.m09、middle.m10、middle.m15、middle.m16、middle.m17、middle.m18、middle.m19、middle.m20、middle.m21、middle.m22、middle.m23、middle.m24、middle.m25、middle.m26、middle.m27、middle.m28、middle.m29、middle.m30、middle.m31

## primary（27 条）

- 自审结论：✅ 通过
- 前置缺失 0 / 锚点缺失 0 / 自指 0 / 环 0 / 正向引用 0
- 跨学段引用 0（前序学段）/ 反向 0 / 未落地缺口提示 0（提示不阻塞，学段顺序兜底）

主题分组（按顺序）：
- 数与运算 ×13（primary.s01 … primary.s23）
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
待生成 23：
  primary.s01、primary.s02、primary.s03、primary.s04、primary.s22、primary.s27、primary.s09、primary.s10、primary.s23、primary.s11、primary.s12、primary.s13、primary.s14、primary.s15、primary.s16、primary.s17、primary.s24、primary.s25、primary.s18、primary.s19、primary.s26、primary.s20、primary.s21

## high（81 条）

- 自审结论：✅ 通过
- 前置缺失 0 / 锚点缺失 0 / 自指 0 / 环 0 / 正向引用 0
- 跨学段引用 0（前序学段）/ 反向 0 / 未落地缺口提示 0（提示不阻塞，学段顺序兜底）

主题分组（按顺序）：
- 集合与常用逻辑 ×6（high.h01 … high.h06）
- 等式与不等式 ×7（high.h07 … high.h13）
- 函数 ×17（high.h14 … high.h30）
- 数列 ×6（high.h31 … high.h36）
- 平面向量 ×4（high.h37 … high.h40）
- 复数 ×1（high.h40b） ⚠️ 孤立单条
- 立体几何初步 ×6（high.h41 … high.h46）
- 空间向量与立体几何 ×1（high.h47） ⚠️ 孤立单条
- 解析几何 ×12（high.h48 … high.h59）
- 导数及其应用 ×9（high.h60 … high.h68）
- 统计与概率 ×12（high.h69 … high.h80）

covered（锚点已覆盖 0）：
- （无：本学段暂无锚点占位条目）
待生成 81：
  high.h01、high.h02、high.h03、high.h04、high.h05、high.h06、high.h07、high.h08、high.h09、high.h10、high.h11、high.h12、high.h13、high.h14、high.h15、high.h16、high.h17、high.h18、high.h19、high.h20、high.h21、high.h22、high.h23、high.h24、high.h25、high.h26、high.h27、high.h28、high.h29、high.h30、high.h31、high.h32、high.h33、high.h34、high.h35、high.h36、high.h37、high.h38、high.h39、high.h40、high.h40b、high.h41、high.h42、high.h43、high.h44、high.h45、high.h46、high.h47、high.h48、high.h49、high.h50、high.h51、high.h52、high.h53、high.h54、high.h55、high.h56、high.h57、high.h58、high.h59、high.h60、high.h61、high.h62、high.h63、high.h64、high.h65、high.h66、high.h67、high.h68、high.h69、high.h70、high.h71、high.h72、high.h79、high.h73、high.h74、high.h75、high.h76、high.h77、high.h78、high.h80

## college（59 条）

- 自审结论：✅ 通过
- 前置缺失 0 / 锚点缺失 0 / 自指 0 / 环 0 / 正向引用 0
- 跨学段引用 5（前序学段）/ 反向 0 / 未落地缺口提示 5（提示不阻塞，学段顺序兜底）

主题分组（按顺序）：
- 一元微积分 ×16（college.c01 … college.c15b）
- 多元函数微积分 ×9（college.c16 … college.c24）
- 线性代数 ×11（college.c25 … college.c34b）
- 概率论与数理统计 ×10（college.c35 … college.c43b）
- 离散数学初步 ×7（college.c44 … college.c50）
- 数值计算初步 ×6（college.c51 … college.c56）

covered（锚点已覆盖 0）：
- （无：本学段暂无锚点占位条目）
待生成 59：
  college.c01、college.c02、college.c03、college.c04、college.c05、college.c06、college.c07、college.c08、college.c09、college.c10、college.c11、college.c12、college.c13、college.c14、college.c15、college.c15b、college.c16、college.c17、college.c18、college.c19、college.c20、college.c21、college.c22、college.c23、college.c24、college.c25、college.c26、college.c27、college.c28、college.c29、college.c30、college.c31、college.c32、college.c33、college.c34、college.c34b、college.c35、college.c36、college.c37、college.c38、college.c39、college.c40、college.c41、college.c42、college.c43、college.c43b、college.c44、college.c45、college.c46、college.c47、college.c48、college.c49、college.c50、college.c51、college.c52、college.c53、college.c54、college.c55、college.c56

## ai（60 条）

- 自审结论：✅ 通过
- 前置缺失 0 / 锚点缺失 0 / 自指 0 / 环 0 / 正向引用 0
- 跨学段引用 6（前序学段）/ 反向 0 / 未落地缺口提示 6（提示不阻塞，学段顺序兜底）

主题分组（按顺序）：
- 机器学习数学基础 ×11（ai.a01 … ai.a10）
- 凸优化与数值优化 ×10（ai.a11 … ai.a19）
- 信息论与熵 ×6（ai.a20 … ai.a25）
- 矩阵分析与正则化 ×8（ai.a26 … ai.a33）
- 高维概率与统计学习理论 ×9（ai.a34 … ai.a25b）
- 时间序列与随机过程 ×8（ai.a42 … ai.a49）
- 量化应用 ×8（ai.a50 … ai.a57）

covered（锚点已覆盖 0）：
- （无：本学段暂无锚点占位条目）
待生成 60：
  ai.a01、ai.a02、ai.a03、ai.a04、ai.a04b、ai.a05、ai.a06、ai.a07、ai.a08、ai.a09、ai.a10、ai.a11、ai.a12、ai.a13、ai.a14、ai.a15、ai.a16、ai.a17、ai.a17b、ai.a18、ai.a19、ai.a20、ai.a21、ai.a22、ai.a23、ai.a24、ai.a25、ai.a26、ai.a27、ai.a28、ai.a29、ai.a30、ai.a31、ai.a32、ai.a33、ai.a34、ai.a35、ai.a36、ai.a37、ai.a38、ai.a39、ai.a40、ai.a41、ai.a25b、ai.a42、ai.a43、ai.a45、ai.a44、ai.a46、ai.a47、ai.a48、ai.a49、ai.a50、ai.a51、ai.a52、ai.a53、ai.a54、ai.a55、ai.a56、ai.a57
