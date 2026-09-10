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
core_concepts: [比的意义, 比的前项与后项, 化简比, 按比例分配]
explanation:
  role: 教师讲解稿
  body: |
    同学们，我们已经学过除法和分数，今天要认识一个新朋友——比。

    什么是比呢？两个数相除，又叫做这两个数的比。比如 3 除以 2，可以写成 $3:2$，读作"3 比 2"。中间的"∶"叫做比号，比号前面的数叫前项，比号后面的数叫后项。

    比和除法、分数有什么关系呢？

    $$3:2 = 3 \div 2 = \frac{3}{2}$$

    比的前项相当于被除数（分子），后项相当于除数（分母）。比的后项不能是 0，因为除数不能为 0。

    比还有一个重要的性质：比的前项和后项同时乘或除以相同的数（0 除外），比值不变。利用这个性质，我们可以把比化简。

    什么叫化简比？就是把一个比化成前项和后项只有公因数 1 的比，也就是最简整数比。例如 $12:18$，前项和后项同时除以 6，得到 $2:3$，这就是最简整数比。

    化简比和求比值不一样：化简比的结果还是一个比，写成 $2:3$ 的样子；求比值的结果是一个数，可以写成分数或小数。

    最后我们学按比例分配。比如把 60 个苹果按 $2:3$ 分给两个小组，先求总份数 $2+3=5$，每份是 $60 \div 5=12$ 个，第一组得 $12 \times 2=24$ 个，第二组得 $12 \times 3=36$ 个。

    按比例分配的关键是：先求总份数，再求一份是多少，最后求各部分是多少。
worked_examples:
  - prompt: 把比 $24:36$ 化成最简整数比。
    solution_steps:
      - 找出 24 和 36 的最大公因数是 12。
      - 前项和后项同时除以 12。
      - $24 \div 12 = 2$，$36 \div 12 = 3$。
      - 所以最简整数比是 $2:3$。
  - prompt: 把 90 颗糖按 $4:5$ 分给甲、乙两人，甲分得多少颗？
    solution_steps:
      - 总份数：$4+5=9$。
      - 每份：$90 \div 9 = 10$（颗）。
      - 甲分得：$10 \times 4 = 40$（颗）。
      - 答：甲分得 40 颗。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "把 {a} 颗糖按 1:2 分给甲、乙两人，甲分得多少颗？"
      params:
        a: {range: [3, 90], exclude: [0]}
      constraint: "a % 3 == 0"
      answer_expr: "a / 3"
      semantics:
        expect: "a * 1 / (1 + 2)"
        requires: ["a % 3 == 0"]
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
  - id: ex2
    kind: template
    difficulty: 1
    template:
      prompt: "把 {a} 个苹果按 2:3 分给两个小组，第二组分得多少个？"
      params:
        a: {range: [5, 100], exclude: [0]}
      constraint: "a % 5 == 0"
      answer_expr: "a * 3 / 5"
      semantics:
        expect: "a * 3 / (2 + 3)"
        requires: ["a % 5 == 0"]
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
feynman:
  task_prompt: 请用自己的话给同学讲一讲：什么叫比？比和除法、分数有什么关系？怎样化简比？再举一个按比例分配的例子说明计算过程。
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 比的后项可以是 0 吗？为什么？
    - 化简比和求比值有什么不同？
    - 按比例分配时，如果总数不能整除总份数，该怎么办？
---
