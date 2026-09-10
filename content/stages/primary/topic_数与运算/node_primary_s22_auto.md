---
id: primary.s22
source: auto
title: 运算律与简便运算
level: primary
topic: 数与运算
prereqs: [primary.0101]
objectives:
  - 理解加法交换律、结合律和乘法交换律、结合律、分配律
  - 能运用运算律进行简便计算
core_concepts: [加法交换律, 加法结合律, 乘法交换律, 乘法结合律, 乘法分配律]
explanation:
  role: 教师讲解稿
  body: |
    同学们，今天我们学习运算律。运算律是数学中的“小魔法”，能帮我们更快地计算。

    加法交换律：两个数相加，交换位置，和不变。例如：$3+5=5+3=8$。

    加法结合律：三个数相加，先把前两个数相加，或者先把后两个数相加，和不变。例如：$(2+3)+4=2+(3+4)=9$。

    乘法交换律：两个数相乘，交换位置，积不变。例如：$4\times5=5\times4=20$。

    乘法结合律：三个数相乘，先把前两个数相乘，或者先把后两个数相乘，积不变。例如：$(2\times3)\times4=2\times(3\times4)=24$。

    乘法分配律：两个数的和与一个数相乘，可以先把它们分别与这个数相乘，再相加。例如：$(2+3)\times4=2\times4+3\times4=20$。

    这些运算律可以帮助我们简便计算。比如计算 $25\times(4+8)$，直接用分配律：$25\times4+25\times8=100+200=300$，比先算括号再乘更简单。

    再如 $125\times7\times8$，利用乘法交换律和结合律，先算 $125\times8=1000$，再乘7得7000，非常快。

    记住：运算律是工具，要灵活运用哦！
worked_examples:
  - prompt: 计算：25×(4+8)，并用运算律说明简便之处。
    solution_steps:
      - 观察到25和4相乘得100，25和8相乘得200，因此用乘法分配律展开。
      - 计算 25×4=100，25×8=200。
      - 将结果相加：100+200=300。
      - 所以 25×(4+8)=300。
  - prompt: 计算：125×7×8。
    solution_steps:
      - 观察到125和8相乘得1000，因此利用乘法交换律和结合律，先算125×8。
      - 计算125×8=1000。
      - 再乘以7：1000×7=7000。
      - 所以125×7×8=7000。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "计算：{a}×( {b}+{c} )，并运用乘法分配律。"
      params:
        a: {range: [2, 9], exclude: [0]}
        b: {range: [2, 9], exclude: [0]}
        c: {range: [2, 9], exclude: [0]}
      answer_expr: "a*(b+c)"
      basis: {quote: "乘法分配律：两个数的和与一个数相乘，可以先把它们分别与这个数相乘，再相加。"}
      semantics:
        expect: "a*b + a*c"
        requires: []
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
feynman:
  task_prompt: 请用自己的话向同学解释：什么是乘法分配律？并举一个例子说明它如何让计算更简便。
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 如果计算 (a+b)×c 时，你能用分配律吗？
    - 为什么 25×(4+8) 用分配律比先算括号更简单？
    - 你能找到一个不能用分配律简便计算的例子吗？
---