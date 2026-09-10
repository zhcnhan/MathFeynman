---
id: primary.s23
title: 比的意义·化简比与按比例分配
level: primary
topic: 数与运算
prereqs: [primary.0102, primary.0104, primary.s10]
objectives:
  - 理解比的意义，知道比各部分名称
  - 掌握化简比的方法
  - 能解决按比例分配的实际问题
core_concepts: [比的意义, 前项与后项, 比值, 最简整数比, 按比例分配]
explanation:
  role: 教师讲解稿
  body: |
    两个数相除，又叫做这两个数的比。例如 3 比 2 写作 $3:2$，读作“3 比 2”。
    其中 3 是比的前项，2 是比的后项，中间的“:”是比号。比的前项除以后项所得的商，叫做比值。

    $$3:2 = 3 \div 2 = \frac{3}{2}$$

    所以 $3:2$ 的比值是 $\frac{3}{2}$。注意：比表示两个数之间的关系，比值是一个数。

    比的前项和后项同时乘或除以相同的数（0 除外），比值不变。利用这条性质可以把比化成最简整数比，
    也就是前项和后项只有公因数 1 的整数比。例如：

    $$12:18 = (12 \div 6):(18 \div 6) = 2:3$$

    化简比的结果要写成比的形式（如 $2:3$），而求比值的结果是一个数（如 $\frac{2}{3}$），两者不要混淆。

    按比例分配：把总量按照一定的比分成几部分，先求出总份数，再求每份是多少。
    例如把 60 个苹果按 $2:3$ 分给两个班，总份数是 $2+3=5$，每份是 $60 \div 5 = 12$（个），
    两班分别得到 $12 \times 2 = 24$（个）和 $12 \times 3 = 36$（个）。
worked_examples:
  - prompt: 化简比 $24:36$，并说出它的比值。
    solution_steps:
      - 24 和 36 的最大公因数是 12。
      - 前项和后项同时除以 12：$24 \div 12 = 2$，$36 \div 12 = 3$。
      - 所以最简整数比是 $2:3$。
      - 比值是前项除以后项：$2 \div 3 = \frac{2}{3}$。
  - prompt: 把 45 颗糖按 $4:5$ 分给甲、乙两人，两人各得多少颗？
    solution_steps:
      - 总份数：$4+5=9$。
      - 每份：$45 \div 9 = 5$（颗）。
      - 甲：$5 \times 4 = 20$（颗）。
      - 乙：$5 \times 5 = 25$（颗）。
      - 检验：$20+25=45$，且 $20:25=4:5$。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "把 {total} 个苹果按 {a}:{b} 分给两个班，较多的那个班分到多少个苹果？"
      params:
        a: {range: [1, 4], exclude: [0]}
        b: {range: [5, 9], exclude: [0]}
        total: {range: [20, 90], exclude: [0]}
      constraint: "total % (a + b) == 0"
      answer_expr: "total * b / (a + b)"
      semantics:
        expect: "total * b / (a + b)"
        requires: ["total % (a + b) == 0"]
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
  - id: ex2
    kind: template
    difficulty: 1
    template:
      prompt: "化简比 {m}:{n} 后，前项与后项的和是多少？"
      params:
        m: {range: [2, 30], exclude: [0]}
        n: {range: [2, 30], exclude: [0]}
      constraint: "m != n"
      answer_expr: "m / gcd(m, n) + n / gcd(m, n)"
      semantics:
        expect: "m / gcd(m, n) + n / gcd(m, n)"
        requires: ["m != n"]
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
feynman:
  task_prompt: 请用自己的话讲一讲：什么叫做比？化简比和求比值有什么不同？再举一个按比例分配的例子说明怎样先求总份数。
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 比的前项和后项同时乘或除以一个数，比值会变吗？为什么 0 要除外？
    - 化简比的结果 $2:3$ 和比值 $\frac{2}{3}$ 表示的意思一样吗？
    - 按比例分配时，如果总量不能被总份数整除，还能用“先求每份”的方法吗？
---
