---
id: primary.s02
title: 百以内加减（进位与退位）
level: primary
topic: 数与运算
prereqs: [primary.s01]
objectives:
  - 掌握竖式进位加法与退位减法的写法
  - 能用口算与估算快速判断结果是否合理
core_concepts: [进位, 退位, 竖式, 估算]
explanation:
  role: 教师讲解稿
  body: |
    今天我们来学习一百以内的加法和减法，重点是**进位加法**和**退位减法**。

    先看加法。比如 $28 + 35$。把两个数上下对齐写成竖式，个位对个位，十位对十位：

    $$
    \begin{array}{r} 28 \\ +35 \\ \hline \end{array}
    $$

    先算个位：$8 + 5 = 13$。个位写 3，向十位**进 1**。再算十位：$2 + 3 + 1 = 6$。所以 $28 + 35 = 63$。

    再看减法。比如 $52 - 27$。个位 $2$ 不够减 $7$，就要从十位**退 1**：把 $52$ 看成 $40 + 12$。个位 $12 - 7 = 5$，十位 $4 - 2 = 2$，所以 $52 - 27 = 25$。

    怎样检查结果合不合理呢？可以用估算：$52 - 27$ 大约就是 $50 - 30 = 20$，答案 $25$ 和 $20$ 很接近，说明结果合理。

    记住两条口诀：加法个位满十就进位，减法个位不够减就退位。
worked_examples:
  - prompt: 计算 $47 + 38$。
    solution_steps:
      - 列竖式，个位对齐：$47$ 与 $38$ 上下对齐。
      - 个位相加：$7 + 8 = 15$，写 5 向十位进 1。
      - 十位相加：$4 + 3 + 1 = 8$。
      - 所以 $47 + 38 = 85$。估算 $50 + 40 = 90$，结果 85 合理。
  - prompt: 计算 $63 - 28$。
    solution_steps:
      - 列竖式，个位对齐。
      - 个位 $3$ 不够减 $8$，从十位退 1，个位变成 $13$：$13 - 8 = 5$。
      - 十位退 1 后剩 $5$：$5 - 2 = 3$。
      - 所以 $63 - 28 = 35$。估算 $60 - 30 = 30$，结果 35 合理。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "计算 {a} + {b} 的结果（{a} 与 {b} 均为两位数，个位相加会进位）。"
      params:
        a: {range: [10, 49], exclude: [0]}
        b: {range: [10, 49], exclude: [0]}
      constraint: "(a % 10) + (b % 10) >= 10"
      answer_expr: "a + b"
      semantics:
        expect: "b + a"
        requires: ["(a % 10) + (b % 10) >= 10"]
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
  - id: ex2
    kind: template
    difficulty: 2
    template:
      prompt: "计算 {a} - {b} 的结果（{a} 大于 {b}，个位不够减需要退位）。"
      params:
        a: {range: [30, 99], exclude: [0]}
        b: {range: [10, 89], exclude: [0]}
      constraint: "a > b and (a % 10) < (b % 10)"
      answer_expr: "a - b"
      semantics:
        expect: "-(b - a)"
        requires: ["a > b", "(a % 10) < (b % 10)"]
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
feynman:
  task_prompt: 用自己的话讲一讲：为什么做退位减法时，个位不够减就要向十位借 1？借来的 1 在个位上表示多少？
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 借 1 之后，被减数的十位发生了什么变化？
    - 如果个位够减，还需要退位吗？请举一个不用退位的例子。
    - 你能用估算判断 63 - 28 的结果大概是多少吗？
---
