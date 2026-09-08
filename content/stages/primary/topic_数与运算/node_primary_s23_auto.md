---
id: primary.s23
source: auto
title: 比的意义·化简比与按比例分配
level: primary
topic: 数与运算
prereqs: [primary.0102, primary.0104, primary.s10]
objectives:
  - 理解比的意义，知道比各部分名称
  - 掌握化简比的方法
  - 能解决按比例分配的实际问题
core_concepts: [比, 前项, 后项, 比值, 化简比, 按比例分配]
explanation:
  role: 教师讲解稿
  body: |
    同学们，今天我们来学习“比”。

    首先，什么是比？两个数相除又叫两个数的比。比如，一个长方形长是6厘米，宽是4厘米，长和宽的比就是6比4，记作 $6:4$，读作“6比4”。比号前面的数叫前项，比号后面的数叫后项。前项除以后项所得的商叫做比值。例如 $6:4 = 6 \div 4 = 1.5$，比值是1.5。

    比和除法、分数有密切的联系：比的前项相当于除法中的被除数、分数中的分子；比的后项相当于除法中的除数、分数中的分母；比号相当于除号或分数线。但要注意，比表示一种关系，除法是一种运算，分数是一个数。

    接下来我们学习化简比。化简比就是把比化成最简单的整数比，也就是前项和后项都是整数，并且互质。例如，$12:16$，前项和后项同时除以它们的最大公因数4，得到 $12 \div 4 = 3$，$16 \div 4 = 4$，所以 $12:16 = 3:4$。

    如果比的前项或后项是分数或小数，可以先把它们化成整数，再化简。比如 $0.5:2$，可以同时乘2，变成 $1:4$。

    最后学习按比例分配。按比例分配就是把一个数量按照一定的比进行分配。例如，把20个苹果按 $2:3$ 分给甲和乙，那么甲分得 $20 \times \frac{2}{2+3} = 20 \times \frac{2}{5} = 8$ 个，乙分得 $20 \times \frac{3}{2+3} = 20 \times \frac{3}{5} = 12$ 个。

    总结一下：比的意义、化简比、按比例分配，这些知识在生活中很有用。
worked_examples:
  - prompt: 化简比：$18:24$
    solution_steps:
      - 找出18和24的最大公因数，最大公因数是6。
      - 前项和后项同时除以6，得到 $18 \div 6 = 3$，$24 \div 6 = 4$。
      - 所以 $18:24 = 3:4$。
  - prompt: 学校把300本图书按 $2:3$ 分给五年级和六年级，五年级和六年级各分得多少本？
    solution_steps:
      - 总份数：$2+3=5$。
      - 五年级分得：$300 \times \frac{2}{5} = 120$ 本。
      - 六年级分得：$300 \times \frac{3}{5} = 180$ 本。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "化简比：{a}:{b}"
      params:
        a: {range: [2, 20], exclude: [0]}
        b: {range: [2, 20], exclude: [0]}
      answer_expr: "a/b"
    check:
      mode: numeric_value
  - id: ex2
    kind: template
    difficulty: 1
    template:
      prompt: "把 {total} 个苹果按 {x}:{y} 分给小明和小红，小明分得多少个？"
      params:
        total: {range: [10, 100], exclude: [0]}
        x: {range: [1, 9], exclude: [0]}
        y: {range: [1, 9], exclude: [0]}
      answer_expr: "total*x/(x+y)"
    check:
      mode: numeric_value
feynman:
  task_prompt: 请用自己的话向一位同学解释“比”是什么，如何化简比，以及如何按比例分配。举一个生活中的例子。
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 如果比的后项是0，这个比有意义吗？为什么？
    - 化简比和求比值有什么区别？
    - 按比例分配时，如果总数量不能被总份数整除，怎么办？
---
