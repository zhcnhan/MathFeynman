---
id: primary.s10
source: auto
title: 百分数的认识与应用
level: primary
topic: 数与运算
prereqs: [primary.s09]
objectives:
  - 理解百分数的意义，能正确读写百分数
  - 能求一个数的百分之几是多少
core_concepts:
  - 百分数
  - 百分率
  - 求一个数的百分之几
explanation:
  role: 教师讲解稿
  body: |
    同学们，今天我们来认识一种特殊的分数——百分数。百分数表示一个数是另一个数的百分之几，也叫百分率或百分比。百分数通常不写成分数形式，而是在原来的分子后面加上百分号“%”来表示。例如，$\frac{1}{100}$ 可以写成 $1\%$，读作“百分之一”。

    百分数在生活中非常常见。比如，一件衣服的棉含量是 $80\%$，意思是棉占整件衣服的 $\frac{80}{100}$。再比如，某次考试及格率是 $95\%$，表示及格人数占总人数的 $\frac{95}{100}$。

    那么，怎么求一个数的百分之几呢？其实和求一个数的几分之几是一样的，用乘法计算。例如，求 $200$ 的 $15\%$，就是 $200 \times 15\% = 200 \times \frac{15}{100} = 30$。

    我们来总结一下：百分数就是分母为 $100$ 的分数，求一个数的百分之几，就用这个数乘以对应的百分数。
worked_examples:
  - prompt: 某班有50名学生，其中60%是男生。这个班有多少名男生？
    solution_steps:
      - 理解题意：求50的60%是多少。
      - 列出算式：$50 \times 60\%$。
      - 将百分数化为分数：$60\% = \frac{60}{100}$。
      - 计算：$50 \times \frac{60}{100} = 30$。
      - 答：这个班有30名男生。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "求{a}的{b}%是多少？"
      params:
        a: {range: [10, 100], exclude: [0]}
        b: {range: [1, 99], exclude: [0]}
      answer_expr: "a*b/100"
      basis: {quote: "同学们，今天我们来认识一种特殊的分数——百分数"}
      semantics:
        expect: "Rational(a*b, 100)"
        requires: []
        domain: {nonneg: true}
    check:
      mode: numeric_value
feynman:
  task_prompt: 请用自己的话向一位同学解释：什么是百分数？如何求一个数的百分之几？并举一个生活中的例子。
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 如果求一个数的120%，结果会比原数大还是小？为什么？
    - 百分数和分数有什么相同和不同？
    - 你能举一个生活中用到百分数的例子吗？
---