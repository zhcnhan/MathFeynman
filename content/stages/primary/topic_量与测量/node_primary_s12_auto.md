---
id: primary.s12
title: 人民币与货币计算
level: primary
topic: 量与测量
prereqs: [primary.s02]
objectives:
  - 掌握元、角、分之间的换算关系
  - 能在购物找零情境中进行简单的货币计算
core_concepts: [元角分, 1元=10角, 1角=10分, 找零]
explanation:
  role: 教师讲解稿
  body: |
    同学们，我们每天买东西都要用到钱。我们国家的钱叫人民币，单位有元、角、分。

    它们之间怎么换算呢？记住两句话：

    $$1\text{元} = 10\text{角}$$

    $$1\text{角} = 10\text{分}$$

    所以 1 元也等于 100 分。比如 3 元 5 角，就是 3 元加上 5 角；5 角可以写成 0.5 元，也可以写成 50 分。

    买东西时常常要算找回多少钱。方法很简单：付出的钱减去商品的价格，就是找回的钱。

    例如：拿 10 元买一本 6 元的本子，找回 $10 - 6 = 4$ 元。

    注意：只有付出的钱不少于商品价格时，才够买，找回的钱才不会变成负数。

worked_examples:
  - prompt: 小丽有 8 元，买一支 3 元的铅笔，还剩多少元？
    solution_steps:
      - 付出的钱是 8 元，商品价格是 3 元。
      - 找回（剩下）的钱 = 8 - 3 = 5 元。
      - 因为 8 ≥ 3，钱够用，结果是 5 元。
  - prompt: 1 元 2 角等于多少角？
    solution_steps:
      - 1 元 = 10 角。
      - 10 角 + 2 角 = 12 角。
      - 所以 1 元 2 角 = 12 角。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "小明带了 {a} 元去买文具，文具价格是 {b} 元，钱够用。请问买完后还剩多少元？"
      params:
        a: {range: [5, 20], exclude: [0]}
        b: {range: [1, 4], exclude: [0]}
      constraint: "a >= b"
      answer_expr: "a-b"
      semantics:
        expect: "a + (-b)"
        requires: ["a >= b"]
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
feynman:
  task_prompt: 请用自己的话给同学讲一讲：元、角、分之间怎么换算？买东西时怎么算找回的钱？
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 如果 1 元 = 10 角，那么 1 元等于多少分呢？
    - 如果付出的钱比商品价格少，还能找回钱吗？为什么？
    - 你能举一个买东西找零的例子，并算一算吗？
---