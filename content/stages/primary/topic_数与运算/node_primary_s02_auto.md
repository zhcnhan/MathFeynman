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
    今天我们学习百以内的加法和减法，重点是“进位”和“退位”。

    先看加法。计算 $28 + 47$ 时，把两个数上下对齐写成竖式，个位对个位，十位对十位。

    $$28 + 47 = 75$$

    个位 $8 + 7 = 15$，满十了，就在个位写 $5$，向十位进 $1$；十位 $2 + 4 + 1 = 7$。这个“进 $1$”就是进位。

    再看减法。计算 $52 - 27$ 时，个位 $2$ 不够减 $7$，就从十位借 $1$ 当十，$12 - 7 = 5$；十位被借走 $1$ 后变成 $4$，$4 - 2 = 2$。

    $$52 - 27 = 25$$

    这个“借 $1$ 当十”就是退位。记住：减法里被减数要比减数大，结果才不会变成负数。

    最后学估算。$28 + 47$ 可以看成 $30 + 50 = 80$，实际结果 $75$ 和 $80$ 很接近，说明算得合理。估算能帮我们检查答案。
worked_examples:
  - prompt: 用竖式计算 $36 + 58$。
    solution_steps:
      - 个位 $6 + 8 = 14$，写 $4$ 向十位进 $1$。
      - 十位 $3 + 5 + 1 = 9$。
      - 所以 $36 + 58 = 94$。
  - prompt: 用竖式计算 $63 - 28$。
    solution_steps:
      - 个位 $3$ 不够减 $8$，从十位借 $1$，$13 - 8 = 5$。
      - 十位 $6$ 被借走 $1$ 变成 $5$，$5 - 2 = 3$。
      - 所以 $63 - 28 = 35$。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "计算 {a} + {b}（{a}、{b} 均为两位数，且个位相加需要进位）。"
      params:
        a: {range: [15, 89], exclude: [0]}
        b: {range: [15, 89], exclude: [0]}
      constraint: "a % 10 + b % 10 >= 10 and a + b <= 99"
      answer_expr: "a + b"
      semantics:
        expect: "a + b"
        requires: ["a % 10 + b % 10 >= 10", "a + b <= 99"]
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
  - id: ex2
    kind: template
    difficulty: 2
    template:
      prompt: "计算 {a} - {b}（{a} 大于 {b}，且个位不够减需要退位）。"
      params:
        a: {range: [21, 99], exclude: [0]}
        b: {range: [11, 89], exclude: [0]}
      constraint: "a >= b and a % 10 < b % 10"
      answer_expr: "a - b"
      semantics:
        expect: "a - b"
        requires: ["a >= b", "a % 10 < b % 10"]
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
feynman:
  task_prompt: 请用自己的话讲一讲：做进位加法和退位减法时，竖式里那“进 1”和“借 1”到底是什么意思？再举一个例子说明。
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 为什么个位相加满十就要向十位进 1？
    - 如果减法里个位不够减，不借位直接减会得到什么？为什么不行？
    - 你能用估算先猜一猜 48 + 37 大约是多少吗？
---
