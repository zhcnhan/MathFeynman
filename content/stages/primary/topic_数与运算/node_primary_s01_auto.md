---
id: primary.s01
source: auto
title: 数的认识与读写（万以内）·四舍五入与估算
level: primary
topic: 数与运算
prereqs: []
objectives:
  - 认识数位（个/十/百/千/万）
  - 能正确读写与比较（万以内）
  - 会用四舍五入取近似数并估算
core_concepts: [数位, 读数写数, 比较大小, 四舍五入, 估算]
explanation:
  role: 教师讲解稿
  body: |
    同学们，我们先来认识数位。一个数从右往左依次是个位、十位、百位、千位、万位。比如 3456，个位是 6，十位是 5，百位是 4，千位是 3。

    读数和写数时，要从高位读起或写起。比如 3456 读作“三千四百五十六”，写作 3456。注意中间有一个或两个 0 时，只读一个“零”，末尾的 0 不读。例如 3005 读作“三千零五”，3500 读作“三千五百”。

    比较两个数的大小时，先看位数，位数多的数大；位数相同，从高位依次比较。比如 999 和 1000，1000 位数多，所以 1000 大。

    四舍五入：要保留到某一位，就看它后面一位，如果小于 5 就舍去，如果大于等于 5 就向前一位进 1。例如 3456 四舍五入到百位，看十位是 5，所以变成 3500。

    估算时，先取近似数再计算。比如买两件商品，价格分别是 198 元和 305 元，大约需要多少钱？可以把 198 看成 200，305 看成 300，大约需要 500 元。
worked_examples:
  - prompt: 写出 4050 的组成，并读出来。
    solution_steps:
      - 4050 由 4 个千、0 个百、5 个十和 0 个一组成。
      - 读数时从高位读起，千位是 4 读“四千”，百位是 0 不读，十位是 5 读“五十”，个位是 0 不读。
      - 所以 4050 读作“四千零五十”。
  - prompt: 比较 3200 和 2999 的大小。
    solution_steps:
      - 3200 是四位数，2999 也是四位数。
      - 比较千位：3 大于 2，所以 3200 大于 2999。
  - prompt: 把 6789 四舍五入到百位。
    solution_steps:
      - 看十位，十位是 8，大于等于 5，所以向百位进 1。
      - 百位原来是 7，进 1 后变成 8，十位和个位变成 0。
      - 结果是 6800。
exercises:
  - id: ex1
    kind: template
    difficulty: 1
    template:
      prompt: "把 {a}{b}{c}{d} 四舍五入到百位，结果是多少？"
      params:
        a: {range: [1, 9], exclude: [0]}
        b: {range: [0, 9]}
        c: {range: [0, 9]}
        d: {range: [0, 9]}
      answer_expr: "(a*1000 + b*100 + c*10 + d + 50) // 100 * 100"
      basis: {quote: "四舍五入：要保留到某一位，就看它后面一位，如果小于 5 就舍去，如果大于等于 5 就向前一位进 1。"}
      semantics:
        expect: "floor((a*1000 + b*100 + c*10 + d + 50) / 100) * 100"
        requires: []
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
  - id: ex2
    kind: template
    difficulty: 1
    template:
      prompt: "估算：{a} + {b} 大约等于多少？（把每个数看成最接近的整十数再相加）"
      params:
        a: {range: [11, 99], exclude: [0]}
        b: {range: [11, 99], exclude: [0]}
      answer_expr: "(a + 5) // 10 * 10 + (b + 5) // 10 * 10"
      basis: {quote: "估算时，先取近似数再计算。"}
      semantics:
        expect: "10 * floor((a + 5) / 10) + 10 * floor((b + 5) / 10)"
        requires: []
        domain: {nonneg: true, integer: true}
    check:
      mode: numeric_value
feynman:
  task_prompt: 请用自己的话向同学解释：什么是四舍五入？在什么情况下用四舍五入？并举一个生活中的例子。
  rubric:
    dimensions:
      - {key: correctness, weight: 0.4}
      - {key: own_words, weight: 0.2}
      - {key: example_and_edge, weight: 0.2}
      - {key: self_correction, weight: 0.2}
    pass_threshold: 0.7
  socratic_followups:
    - 如果近似到十位，应该看哪一位？
    - 估算时，为什么有时候把数看成整百数更方便？
    - 你能举一个四舍五入到万位的例子吗？
---
