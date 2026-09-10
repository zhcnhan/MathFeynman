---
id: primary.s27
title: 因数·倍数·质数与合数·公因数公倍数
level: primary
topic: 数与运算
prereqs: [primary.s04, primary.0101]
objectives:
  - 理解因数、倍数与整除的含义
  - 认识质数与合数，会判断一个数是质数还是合数
  - 会求两个数的公因数与最大公因数（GCD）
  - 会求两个数的公倍数与最小公倍数（LCM）
core_concepts: [整除, 因数, 倍数, 质数, 合数, 公因数, 最大公因数, 公倍数, 最小公倍数]
explanation:
  role: 教师讲解稿
  body: |
    我们先认识“整除”。如果整数 $a$ 除以整数 $b$（$b \ne 0$）除得的商正好是整数而没有余数，就说 $a$ 能被 $b$ 整除。

    例如 $12 \div 3 = 4$，没有余数，所以 12 能被 3 整除。

    这时我们给两个数起名字：
    - 3 是 12 的**因数**；
    - 12 是 3 的**倍数**。

    一个数的因数成对出现。比如 12 的因数有 1、2、3、4、6、12，一共 6 个。最小的因数是 1，最大的因数是它自己。

    一个数的倍数有无数个，最小的倍数是它自己。

    再看质数与合数。一个数如果只有 1 和它本身两个因数，就叫**质数**；如果除了 1 和它本身还有别的因数，就叫**合数**。

    例如 7 的因数只有 1 和 7，所以 7 是质数；9 的因数有 1、3、9，所以 9 是合数。注意：1 既不是质数也不是合数。

    两个数公有的因数叫**公因数**，其中最大的一个叫**最大公因数**（记作 GCD）。

    例如 12 和 18：12 的因数有 1、2、3、4、6、12；18 的因数有 1、2、3、6、9、18。公因数有 1、2、3、6，最大公因数是 6。

    两个数公有的倍数叫**公倍数**，其中最小的一个叫**最小公倍数**（记作 LCM）。

    例如 4 和 6：4 的倍数有 4、8、12、16、20、24……；6 的倍数有 6、12、18、24……。公倍数有 12、24……，最小公倍数是 12。

    求最大公因数可以列举因数，也可以短除；求最小公倍数可以列举倍数，也可以用短除。短除法把两个数同时除以公有的质因数，除到两个商只有公因数 1 为止。

    特别地，当 $b$ 是 $a$ 的倍数时，$a$ 和 $b$ 的最大公因数是 $a$，最小公倍数是 $b$。
worked_examples:
  - prompt: 求 18 和 24 的最大公因数和最小公倍数。
    solution_steps:
      - 列举 18 的因数：1、2、3、6、9、18。
      - 列举 24 的因数：1、2、3、4、6、8、12、24。
      - 公因数有 1、2、3、6，所以最大公因数是 6。
      - 列举 18 的倍数：18、36、54、72……；24 的倍数：24、48、72……。
      - 最小的公倍数是 72，所以最小公倍数是 72。
  - prompt: 判断 29 是质数还是合数。
    solution_steps:
      - 从小到大试除 29 的因数：2 不能整除，3 不能整除，5 不能整除。
      - 因为 5 × 5 = 25 < 29，下一个质数是 7，7 × 7 = 49 > 29，试除到 5 就够了。
      - 29 的因数只有 1 和 29，所以 29 是质数。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "已知 {b} 是 {a} 的倍数，且 {a}、{b} 都是正整数。求 {a} 和 {b} 的最小公倍数。"
      params:
        a: {range: [2, 9], exclude: [0]}
        b: {range: [2, 30], exclude: [0]}
      constraint: "b % a == 0"
      answer_expr: "b"
      basis: {quote: "我们先认识“整除”"}
      semantics:
        expect: "lcm(a, b)"
        requires: ["b % a == 0"]
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
  - id: ex2
    kind: template
    difficulty: 1
    template:
      prompt: "已知 {a} 和 {b} 都是正整数，且 {b} 是 {a} 的倍数。求 {a} 和 {b} 的最大公因数。"
      params:
        a: {range: [2, 9], exclude: [0]}
        b: {range: [2, 30], exclude: [0]}
      constraint: "b % a == 0"
      answer_expr: "a"
      basis: {quote: "我们先认识“整除”"}
      semantics:
        expect: "gcd(a, b)"
        requires: ["b % a == 0"]
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
feynman:
  task_prompt: 请用自己的话讲清楚：什么是因数、什么是倍数？质数和合数有什么不同？再举两个数，说说怎样找它们的最大公因数和最小公倍数。
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 1 是质数吗？为什么？
    - 如果 b 是 a 的倍数，a 和 b 的最大公因数是几？最小公倍数是几？
    - 两个数的公因数会不会比它们的最大公因数还大？
---
