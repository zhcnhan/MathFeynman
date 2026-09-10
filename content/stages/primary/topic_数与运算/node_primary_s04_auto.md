---
id: primary.s04
title: 除法意义与有余数除法
level: primary
topic: 数与运算
prereqs: [primary.s03]
objectives:
  - 理解除法与乘法互逆
  - 会做有余数除法并处理余数
core_concepts: [平均分, 除法与乘法互逆, 余数, 余数小于除数]
explanation:
  role: 教师讲解稿
  body: |
    同学们，我们已经学过乘法，今天来认识它的“好朋友”——除法。

    把 12 个苹果平均放进 3 个盘子，每盘放几个？我们可以想：3 乘几等于 12？因为 $3 \times 4 = 12$，所以每盘放 4 个。
    写成除法就是：

    $$12 \div 3 = 4$$

    这里 12 叫被除数，3 叫除数，4 叫商。除法就是在问“乘几能得到它”，所以除法和乘法是互逆的：

    $$12 \div 3 = 4 \quad\Longleftrightarrow\quad 3 \times 4 = 12$$

    但是，苹果不一定能正好分完。比如 13 个苹果平均放进 3 个盘子：每盘放 4 个，一共放掉 12 个，还剩 1 个不够再分一盘了。这时写成：

    $$13 \div 3 = 4 \cdots\cdots 1$$

    商是 4，余数是 1。余数就是“分到最后剩下的、不够再分一份”的数。

    要记住两条规矩：
    1. 余数一定比除数小，否则说明还能再分一份；
    2. 验算用乘法：$3 \times 4 + 1 = 13$，也就是“除数 × 商 + 余数 = 被除数”。

    所以做有余数除法，只要找到“除数乘几最接近被除数、又不超过它”，那个几就是商，差就是余数。
worked_examples:
  - prompt: 有 17 颗糖，平均分给 5 个小朋友，每人分到几颗？还剩几颗？
    solution_steps:
      - 想 5 乘几最接近 17 又不超过 17：$5 \times 3 = 15$，$5 \times 4 = 20$ 超过了，所以商是 3。
      - 用 17 减去分掉的 15：$17 - 15 = 2$，余数是 2。
      - 检查余数：$2 < 5$，比除数小，符合要求。
      - 验算：$5 \times 3 + 2 = 17$，正确。
  - prompt: 判断 $20 \div 6 = 2 \cdots\cdots 8$ 对不对？
    solution_steps:
      - 看余数 8 和除数 6 的大小：$8 > 6$，余数比除数大了。
      - 说明还能再分一份：$8 - 6 = 2$，商应该再加 1。
      - 正确结果是 $20 \div 6 = 3 \cdots\cdots 2$，验算 $6 \times 3 + 2 = 20$。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "把 {a} 个苹果平均放进 {b} 个盘子，每个盘子最多放几个完整的苹果？"
      params:
        a: {range: [10, 60], exclude: [0]}
        b: {range: [2, 9], exclude: [0]}
      constraint: "b <= a"
      answer_expr: "(a - (a % b)) / b"
      semantics:
        expect: "floor(a / b)"
        requires: ["b <= a"]
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
  - id: ex2
    kind: template
    difficulty: 1
    template:
      prompt: "{a} 除以 {b}，余数是几？"
      params:
        a: {range: [10, 60], exclude: [0]}
        b: {range: [2, 9], exclude: [0]}
      constraint: "b <= a"
      answer_expr: "a % b"
      semantics:
        expect: "a - b * floor(a / b)"
        requires: ["b <= a"]
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
feynman:
  task_prompt: 用自己的话给同学讲一讲：为什么除法可以用乘法来验算？余数为什么一定要比除数小？
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 如果除完以后余数比除数还大，说明什么？
    - 13 除以 4 的商和余数分别是多少？用乘法怎么验算？
    - 除法里的商，和乘法里的哪个数有关系？
---