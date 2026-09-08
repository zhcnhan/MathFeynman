---
id: primary.s04
title: 除法意义与有余数除法
level: primary
topic: 数与运算
prereqs: [primary.s03]
objectives:
  - 理解除法与乘法互逆
  - 会做有余数除法并处理余数
core_concepts: [除法, 乘法互逆, 有余数除法, 余数]
explanation:
  role: 教师讲解稿
  body: |
    小朋友们，我们已经学了乘法和除法。今天我们来更深入地理解除法，还要学习有余数的除法。

    首先，除法是乘法的“好朋友”。比如，我们知道 $3 \times 4 = 12$，那么反过来，$12 \div 3 = 4$，$12 \div 4 = 3$。所以，除法就是已知两个数的乘积和其中一个因数，求另一个因数。

    现在看一个例子：把 10 个苹果平均分给 2 个小朋友，每人分几个？我们用除法：$10 \div 2 = 5$，因为 $2 \times 5 = 10$。

    但是，如果要把 10 个苹果平均分给 3 个小朋友，每人分几个？我们发现，$3 \times 3 = 9$，$3 \times 4 = 12$，所以不能正好分完。每人分 3 个，还剩 1 个。写成算式就是：$10 \div 3 = 3 \cdots \cdots 1$，这里的 1 就是余数。余数一定要比除数小，因为如果余数比除数大，就还能再分。

    我们来总结一下：
    - 除法是乘法的逆运算。
    - 有余数除法：被除数 = 除数 × 商 + 余数。
    - 余数必须小于除数。

    现在，我们来做几个练习吧！
worked_examples:
  - prompt: "把 14 个橘子平均分给 4 个小朋友，每人分几个？还剩几个？"
    solution_steps:
      - "想乘法口诀：4 几接近 14？4×3=12，4×4=16，所以商是 3。"
      - "计算余数：14 - 4×3 = 14 - 12 = 2。"
      - "因为余数 2 小于除数 4，所以答案：每人 3 个，还剩 2 个。"
      - "写成算式：14 ÷ 4 = 3……2。"
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "计算 {a} ÷ {b}，写出商和余数（商和余数用空格隔开，例如：3 1）。"
      params:
        a: {range: [10, 30], exclude: [0]}
        b: {range: [2, 9], exclude: [0]}
      answer_expr: "a//b"
    check:
      mode: numeric_value
feynman:
  task_prompt: "请用自己的话解释：什么是除法？什么是有余数的除法？余数有什么特点？并举一个生活中的例子。"
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - "如果余数比除数大，说明什么？"
    - "你能写出一个有余数除法的算式，并验证它吗？"
    - "在平均分东西时，什么时候会出现余数？"
---