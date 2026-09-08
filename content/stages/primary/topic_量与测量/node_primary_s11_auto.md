---
id: primary.s11
source: auto
title: 长度·质量·时间单位与换算
level: primary
topic: 量与测量
prereqs: [primary.s02]
objectives:
  - 认识长度、质量、时间的常用单位及其进率
  - 能进行简单的单位换算，并应用于实际测量
core_concepts: [长度单位, 质量单位, 时间单位, 单位换算]
explanation:
  role: 教师讲解稿
  body: |
    同学们，我们在生活中经常需要测量物体的长度、质量和时间。测量时需要使用统一的单位，今天我们来认识这些常用的单位，并学习它们之间的换算。

    长度单位：我们最常用的长度单位有毫米（mm）、厘米（cm）、分米（dm）、米（m）和千米（km）。它们之间的进率是：1厘米=10毫米，1分米=10厘米，1米=10分米，1千米=1000米。例如，一支铅笔大约长18厘米，也就是180毫米。

    质量单位：常用的质量单位有克（g）、千克（kg）和吨（t）。1千克=1000克，1吨=1000千克。例如，一个苹果大约重200克，一袋大米重5千克。

    时间单位：时间单位有时（h）、分（min）、秒（s）。1小时=60分钟，1分钟=60秒。例如，一节课是40分钟，也就是2400秒。

    单位换算的方法：把高级单位换算成低级单位时，要乘以进率；把低级单位换算成高级单位时，要除以进率。例如，3米=300厘米，因为1米=100厘米，3×100=300。

    在测量时，我们要选择合适的单位。比如测量教室的长度用米，测量硬币的厚度用毫米，测量大象的质量用吨，测量短跑时间用秒。希望大家记住这些单位，并能灵活运用。
worked_examples:
  - prompt: 将5米换算成厘米。
    solution_steps:
      - 明确进率：1米=100厘米。
      - 因为米是高级单位，换算成低级单位厘米，要乘以进率。
      - 计算：5×100=500。
      - 所以5米=500厘米。
  - prompt: 将3千克换算成克。
    solution_steps:
      - 明确进率：1千克=1000克。
      - 高级单位换算成低级单位，乘以进率。
      - 计算：3×1000=3000。
      - 所以3千克=3000克。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "将{a}米换算成厘米。"
      params:
        a: {range: [1, 9], exclude: [0]}
      answer_expr: "a*100"
    check:
      mode: numeric_value
  - id: ex2
    kind: template
    difficulty: 1
    template:
      prompt: "将{a}千克换算成克。"
      params:
        a: {range: [1, 9], exclude: [0]}
      answer_expr: "a*1000"
    check:
      mode: numeric_value
feynman:
  task_prompt: 请用自己的话说一说：长度、质量、时间各有哪些常用单位？它们之间的进率是多少？并举例说明如何进行单位换算。
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 如果要把厘米换算成米，应该怎么做？
    - 测量从家到学校的距离，用什么单位合适？为什么？
    - 你能举一个生活中用到吨这个单位的例子吗？
---
