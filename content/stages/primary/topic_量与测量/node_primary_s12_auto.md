---
id: primary.s12
title: 人民币与货币计算
level: primary
topic: 量与测量
prereqs: [primary.s02]
objectives:
  - 掌握元、角、分之间的换算关系
  - 能在购物找零情境中进行简单的货币计算
core_concepts: [元, 角, 分, 1元=10角, 1角=10分, 找零]
explanation:
  role: 教师讲解稿
  body: |
    我们平时买东西用的钱叫人民币，它的单位有元、角、分。

    它们之间的关系是：

    $$1\text{元} = 10\text{角}, \quad 1\text{角} = 10\text{分}$$

    所以 $1\text{元} = 100\text{分}$。

    换算时记住：把元换成角，就乘 10；把角换成分，也乘 10。反过来，把分换成角，就除以 10；把角换成元，也除以 10。

    买东西时常常要算找零。比如拿 10 元买 6 元 5 角的东西，可以先算 10 元 = 100 角，6 元 5 角 = 65 角，找零就是 $100 - 65 = 35$ 角，也就是 3 元 5 角。

    计算钱的时候，先把单位统一，再加减，这样不容易出错。
worked_examples:
  - prompt: 小丽有 5 元，买一支 2 元 5 角的笔，应找回多少钱？
    solution_steps:
      - 把 5 元换成 50 角，2 元 5 角换成 25 角。
      - 计算找零：$50 - 25 = 25$（角）。
      - 25 角 = 2 元 5 角，所以应找回 2 元 5 角。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "小明带了 {a} 元去文具店，买了一个 {b} 元的笔记本，还剩多少元？（{a} 元够买）"
      params:
        a: {range: [5, 20], exclude: [0]}
        b: {range: [1, 9], exclude: [0]}
      constraint: "a >= b"
      answer_expr: "a - b"
      semantics:
        expect: "a - b"
        requires: ["a >= b"]
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
feynman:
  task_prompt: 请用自己的话讲解元、角、分之间的换算关系，并编一道买东西找零的小题目讲给大家听。
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 1 元等于多少分？你是怎么想的？
    - 如果找回的钱不够 1 元，应该用什么单位表示？
    - 买东西时如果钱不够，还能找回钱吗？
---
