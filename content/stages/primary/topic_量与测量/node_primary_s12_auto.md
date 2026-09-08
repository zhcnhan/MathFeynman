---
id: primary.s12
source: auto
title: 人民币与货币计算
level: primary
topic: 量与测量
prereqs: [primary.s02]
objectives:
  - 掌握元、角、分之间的换算关系
  - 能在购物找零情境中进行简单的货币计算
core_concepts: [元角分, 换算, 购物计算]
explanation:
  role: 教师讲解稿
  body: |
    同学们，今天我们来认识人民币的单位：元、角、分。

    1元 = 10角，1角 = 10分，所以1元 = 100分。

    换算的时候，从大单位到小单位要乘以10，从小单位到大单位要除以10。例如：
    $$3元 = 30角 = 300分$$
    $$50角 = 5元$$

    购物时，我们常常需要计算总价和找零。比如买一个笔记本2元5角，付5元，应该找回多少？
    先把5元换成50角，2元5角换成25角，50角 - 25角 = 25角 = 2元5角。

    记住：计算时要把单位统一，再相加减。
worked_examples:
  - prompt: 小明买一支铅笔花了1元5角，付给售货员5元，应找回多少钱？
    solution_steps:
      - 统一单位：5元 = 50角，1元5角 = 15角
      - 计算差：50角 - 15角 = 35角
      - 换算回元角：35角 = 3元5角
  - prompt: 一个练习本3元，一支笔2元，买这两样一共多少钱？
    solution_steps:
      - 加法：3元 + 2元 = 5元
      - 答：一共5元
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "小明有{a}元，买一个{b}元的文具，还剩多少元？"
      params:
        a: {range: [1, 9], exclude: [0]}
        b: {range: [1, 9], exclude: [0]}
      answer_expr: "a-b"
    check:
      mode: numeric_value
feynman:
  task_prompt: 请用自己的话向同学解释：如何将元换算成角？购物时如何计算找零？请举例说明。
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 如果付的钱不够，应该怎么办？
    - 1元5角和10角哪个多？为什么？
---
