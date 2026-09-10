---
id: primary.s03
source: auto
title: 乘法口诀与乘法意义
level: primary
topic: 数与运算
prereqs: [primary.s02]  # R18 阶段2#5：回填乘法口诀前置（蓝图 primary.s03 prereq s02；生成期曾静默剔除）
objectives:
  - 理解乘法是相同加数的简便
  - 熟练 1–9 乘法口诀
core_concepts:
  - 乘法
  - 乘法口诀
explanation:
  role: 教师讲解稿
  body: |
    同学们，今天我们学习乘法。

    我们先看一个例子：每排有 3 个苹果，有 4 排，一共有多少个苹果？我们可以用加法算：3 + 3 + 3 + 3 = 12。

    但是，如果有很多排，比如 100 排，写加法就很麻烦。于是，数学家想了一个简便的方法，用乘法来表示“几个相同加数的和”。

    像“4 个 3 相加”可以写成 $3 \times 4 = 12$，读作“三乘四等于十二”。中间的符号“×”叫乘号。

    乘法中，乘号前后的数都叫因数，结果叫积。例如在 $3 \times 4 = 12$ 中，3 和 4 是因数，12 是积。

    为了更快地计算乘法，我们背乘法口诀。比如“三四十二”就是 $3 \times 4 = 12$。

    我们来看口诀表：

    $$\begin{array}{c|ccccccccc}
    \times & 1 & 2 & 3 & 4 & 5 & 6 & 7 & 8 & 9 \\ \hline
    1 & 1 & 2 & 3 & 4 & 5 & 6 & 7 & 8 & 9 \\
    2 & 2 & 4 & 6 & 8 & 10 & 12 & 14 & 16 & 18 \\
    3 & 3 & 6 & 9 & 12 & 15 & 18 & 21 & 24 & 27 \\
    4 & 4 & 8 & 12 & 16 & 20 & 24 & 28 & 32 & 36 \\
    5 & 5 & 10 & 15 & 20 & 25 & 30 & 35 & 40 & 45 \\
    6 & 6 & 12 & 18 & 24 & 30 & 36 & 42 & 48 & 54 \\
    7 & 7 & 14 & 21 & 28 & 35 & 42 & 49 & 56 & 63 \\
    8 & 8 & 16 & 24 & 32 & 40 & 48 & 56 & 64 & 72 \\
    9 & 9 & 18 & 27 & 36 & 45 & 54 & 63 & 72 & 81
    \end{array}$$

    口诀要熟记，比如“三七二十一”表示 $3 \times 7 = 21$ 或 $7 \times 3 = 21$。

    现在，我们来做几个练习。
worked_examples:
  - prompt: 每盒铅笔有 6 支，买 4 盒，一共有多少支铅笔？
    solution_steps:
      - 理解：有 4 个 6 相加。
      - 写成乘法：6 × 4。
      - 用口诀“四六二十四”算出积是 24。
      - 答：一共有 24 支铅笔。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "计算 {a} × {b} = ?"
      params:
        a: {range: [2, 9], exclude: [0]}
        b: {range: [2, 9], exclude: [0]}
      answer_expr: "a*b"
      basis: {quote: "同学们，今天我们学习乘法"}
      semantics:
        expect: "b * a"
        requires: []
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
feynman:
  task_prompt: 请用自己的话向同学解释什么是乘法，并举一个生活中的例子。
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 如果加数不相同，能用乘法吗？为什么？
    - 0 乘以任何数等于多少？你能解释吗？
    - 乘法口诀中，哪一句最容易记错？
---
