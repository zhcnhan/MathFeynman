---
id: primary.s13
source: auto
title: 面积与体积单位换算
level: primary
topic: 量与测量
prereqs: [primary.s11]
objectives:
  - 掌握平方米、平方分米、平方厘米之间的进率及换算。
  - 认识公顷、平方千米，并掌握与平方米的换算关系。
  - 理解体积单位与容积单位（升、毫升）的关系，并会进行换算。
core_concepts: [面积单位, 体积单位, 容积单位, 进率, 单位换算]
explanation:
  role: 教师讲解稿
  body: |
    同学们，我们已经学过长度单位，今天我们来学习面积单位和体积单位的换算。

    首先，面积单位表示一个平面的大小。常用的面积单位有平方厘米、平方分米、平方米，还有更大的公顷和平方千米。相邻两个面积单位之间的进率是100。例如：

    $$1\text{平方分米} = 100\text{平方厘米}$$
    $$1\text{平方米} = 100\text{平方分米}$$

    对于更大的土地面积，我们使用公顷和平方千米。1公顷等于10000平方米，1平方千米等于100公顷，也等于1000000平方米。

    接下来看体积单位。体积单位表示物体所占空间的大小。常用体积单位有立方厘米、立方分米、立方米，相邻两个体积单位之间的进率是1000。例如：

    $$1\text{立方分米} = 1000\text{立方厘米}$$
    $$1\text{立方米} = 1000\text{立方分米}$$

    容积单位通常用来表示容器能容纳物体的体积，有升和毫升。它们与体积单位有紧密的联系：

    $$1\text{升} = 1\text{立方分米}$$
    $$1\text{毫升} = 1\text{立方厘米}$$

    所以，1升等于1000毫升。

    换算时，从高级单位到低级单位要乘以进率，从低级单位到高级单位要除以进率。例如：3平方米 = 300平方分米；5000立方厘米 = 5立方分米。

    我们来做一些练习吧！
worked_examples:
  - prompt: 把 3 平方米换算成平方分米。
    solution_steps:
      - 因为 1 平方米 = 100 平方分米，所以 3 平方米 = 3 × 100 平方分米。
      - 计算：3 × 100 = 300。
      - 所以 3 平方米 = 300 平方分米。
  - prompt: 把 2 升换算成立方厘米。
    solution_steps:
      - 因为 1 升 = 1 立方分米，所以 2 升 = 2 立方分米。
      - 又因为 1 立方分米 = 1000 立方厘米，所以 2 立方分米 = 2 × 1000 立方厘米。
      - 计算得 2000 立方厘米。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "把 {a} 平方米换算成平方分米。"
      params:
        a: {range: [1, 9], exclude: [0]}
      answer_expr: "a*100"
      basis: {quote: "同学们，我们已经学过长度单位，今天我们来学习面积单位和体积单位的换算"}
      semantics:
        expect: "100 * a"
        requires: []
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
  - id: ex2
    kind: template
    difficulty: 1
    template:
      prompt: "把 {a} 立方分米换算成立方厘米。"
      params:
        a: {range: [1, 9], exclude: [0]}
      answer_expr: "a*1000"
      basis: {quote: "同学们，我们已经学过长度单位，今天我们来学习面积单位和体积单位的换算"}
      semantics:
        expect: "1000 * a"
        requires: []
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
  - id: ex3
    kind: template
    difficulty: 2
    template:
      prompt: "把 {a} 升换算成毫升。"
      params:
        a: {range: [1, 9], exclude: [0]}
      answer_expr: "a*1000"
      basis: {quote: "同学们，我们已经学过长度单位，今天我们来学习面积单位和体积单位的换算"}
      semantics:
        expect: "1000 * a"
        requires: []
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
feynman:
  task_prompt: 请用自己的话向同学解释：为什么相邻面积单位之间的进率是100，而相邻体积单位之间的进率是1000？并举一个生活中的例子说明单位换算的重要性。
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 如果边长是1米的正方形，面积是多少平方分米？
    - 1立方米的水大约有多少升？
---