---
id: primary.s02
source: auto
title: 百以内加减（进位与退位）
level: primary
topic: 数与运算
prereqs: [primary.s01]
objectives:
  - 掌握竖式进位/退位加减
  - 能用口算与估算
core_concepts: [进位加法, 退位减法, 竖式计算, 估算]
explanation:
  role: 教师讲解稿
  body: |
    小朋友们，我们已经学会了100以内的加减法，今天我们要学习更厉害的进位加法和退位减法。

    首先，我们来看进位加法。比如 $23+18$。我们可以用竖式来算：

    $$
    \begin{array}{r}
      23 \\
    + 18 \\
    \hline
    \end{array}
    $$

    先算个位：$3+8=11$，个位写1，向十位进1。再算十位：$2+1+1=4$，所以结果是41。

    再来看退位减法。比如 $52-27$。竖式：

    $$
    \begin{array}{r}
      52 \\
    - 27 \\
    \hline
    \end{array}
    $$

    个位 $2-7$ 不够减，就从十位借1当10，$12-7=5$，十位变成 $4-2=2$，所以结果是25。

    口算时，可以把数拆开算。比如 $36+47$，先算 $36+40=76$，再算 $76+7=83$。估算时，可以把数看成整十数，比如 $43+28$ 可以看成 $40+30=70$，所以结果大约是70。

    记住：进位加法要记得加上进位的1，退位减法要记得十位少1。多练习，你就能算得又快又对！
worked_examples:
  - prompt: 计算 37+25。
    solution_steps:
      - 列竖式，个位7加5等于12，写2进1。
      - 十位3加2再加进位的1等于6。
      - 结果是62。
  - prompt: 计算 61-38。
    solution_steps:
      - 列竖式，个位1减8不够，从十位借1，11减8等于3。
      - 十位6借走1变成5，5减3等于2。
      - 结果是23。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "计算 {a}+{b}。"
      params:
        a: {range: [11, 89], exclude: [0]}
        b: {range: [11, 89], exclude: [0]}
      answer_expr: "a+b"
    check:
      mode: numeric_value
  - id: ex2
    kind: template
    difficulty: 1
    template:
      prompt: "计算 {a}-{b}。"
      params:
        a: {range: [21, 99], exclude: [0]}
        b: {range: [11, 89], exclude: [0]}
      answer_expr: "a-b"
    check:
      mode: numeric_value
feynman:
  task_prompt: 用自己的话向同学讲解：怎样做进位加法和退位减法？并举一个例子说明。
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 如果个位相加满20，进位时应该进几？
    - 退位减法中，十位借走1后，原来十位上的数要怎样变化？
    - 你能举一个估算的例子吗？
---
