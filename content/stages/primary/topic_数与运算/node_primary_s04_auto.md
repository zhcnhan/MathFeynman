---
id: primary.s04
title: 除法意义与有余数除法
level: primary
topic: 数与运算
prereqs: [primary.s03]
objectives:
  - 理解除法与乘法互逆
  - 会做有余数除法并处理余数
core_concepts: [平均分, 除法与乘法互逆, 被除数, 除数, 商, 余数]
explanation:
  role: 教师讲解稿
  body: |
    同学们，我们已经学过乘法，今天来认识它的“好兄弟”——除法。

    把 12 个苹果平均放到 3 个盘子里，每盘放几个？这就是“平均分”。
    用除法表示：$$12 \div 3 = 4$$
    每盘放 4 个。这里的 12 叫被除数，3 叫除数，4 叫商。

    除法和乘法是互逆的：因为 $3 \times 4 = 12$，所以 $12 \div 3 = 4$。
    想知道除法算得对不对，用乘法验算一下就好。

    可是，如果 13 个苹果平均放到 3 个盘子里呢？
    $$13 \div 3 = 4 \cdots\cdots 1$$
    每盘放 4 个，还剩下 1 个放不下，这个剩下的 1 就叫余数。
    写成竖式要记住：余数一定要比除数小，否则说明还能再分。
    验算方法：$3 \times 4 + 1 = 13$，也就是“除数 × 商 + 余数 = 被除数”。
worked_examples:
  - prompt: 把 17 颗糖平均分给 5 个小朋友，每人分几颗？还剩几颗？
    solution_steps:
      - 想 5 乘几最接近 17 又不超过 17：$5 \times 3 = 15$，$5 \times 4 = 20$ 超了。
      - 所以商是 3，每人分 3 颗。
      - 用 17 减去分掉的 15：$17 - 15 = 2$，还剩 2 颗，余数是 2。
      - 检查余数：$2 < 5$，比除数小，正确。验算：$5 \times 3 + 2 = 17$。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "把 {a} 个苹果平均放到 {b} 个盘子里，每盘放几个？（用除法求商）"
      params:
        a: {range: [6, 60], exclude: [0]}
        b: {range: [2, 9], exclude: [0]}
      constraint: "a % b == 0"
      answer_expr: "a/b"
      semantics:
        expect: "a/b"
        requires: ["a % b == 0"]
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
feynman:
  task_prompt: 请用自己的话给同学讲一讲：为什么“除数 × 商 + 余数 = 被除数”？余数为什么一定要比除数小？
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 如果余数等于除数，比如 14 除以 7 说成商 1 余 7，这样对吗？为什么？
    - 你能举一个没有余数的例子，再用乘法验算给大家看吗？
---