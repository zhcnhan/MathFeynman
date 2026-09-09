# 06 · 后端 API 草案与数据模型
> 适用范围：范围：API 现状（math 形态端点）。subject 命名空间改造见 docs/14 Phase A

> 供前后端联调与实现参考。签名可微调，但**语义与状态流转必须符合 docs/03、docs/05**。
> 所有端点默认前缀 `/api`，JSON 通信，错误统一 `{error: {code, message}}`。

## 1. REST 端点草案

### 图谱与仪表盘
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/graph` | 全图（节点+边+状态），前端渲染图谱 |
| GET | `/nodes/{node_id}` | 节点元数据 + content 摘要（不含答案） |
| GET | `/dashboard` | 今日复习队列、当前推荐节点、累计统计、断点清单（捡拾结果） |

### 学习会话
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/session/start` | body `{node_id}` → 创建/恢复会话，返回状态机当前步与首批内容（讲解稿演绎结果可选异步）。**R18 总序门禁**：无既有会话而新建时校验蓝图总序（docs/09 R18）；越级 → `409 invalid_state`，detail 含"请先完成：<前置条目标题>"。既有会话恢复 / 练习·费曼续走 / 复习不受门禁影响 |
| POST | `/session/step` | body `{session_id, action, payload}`；action ∈ `ask_question / next / submit_exercise / request_hint / feynman_submit / feynman_answer / finish / quit`（`next` = 阶段前进：讲解→例题→练习，见 docs/09 R1）。返回：下一步 UI 状态 + 新内容 + 状态机事件流 |
| GET | `/session/{id}` | 恢复会话全状态 |

### 练习与判题（幂等，供前端直接调用或经由 step）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/exercises/check` | body `{exercise_id, params_seed, user_answer, session_id?}` → sympy 判题结果 + hint（不泄答案） |
| POST | `/exercises/next` | body `{node_id, exclude_ids}` → 下一道题（模板渲染或 AI 变体） |

### 复习
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/review/queue` | 到期复习列表（含堆积警示） |
| POST | `/review/submit` | body `{node_id, rating(1-4), answers[]}` → 更新 FSRS 状态，返回下个到期日 |

### 画像与配置
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/profile` | 画像（错误类型、风格偏好） |
| PATCH | `/profile` | 用户手动调整偏好（解释深度等） |
| GET | `/config/models` | 当前模型分级配置（供设置页显示，不改密钥） |

### 内容管理（开发工具，MVP 阶段 CLI 为主）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/content/validate` | 运行全库校验并返回报告 |
| GET | `/content/drafts` / POST `/content/drafts/{id}/promote` | 审核 drafts（见 04 §6） |

## 2. `/session/step` 的响应协议（前后端契约要点）

```jsonc
{
  "step": "practice",            // 状态机当前阶段 explain|example|practice|feynman|done
  "payload": { /* 依阶段而定：讲解文本 / 例题 / 题目对象 / 费曼任务或追问 */ },
  "events": [                    // 供 UI 展示的流水（也用于测试断言）
    {"type": "exercise_correct", "node_id": "...", "consecutive_correct": 2},
    {"type": "hint_given", "count": 1},
    {"type": "feynman_passed", "score": 0.83},
    {"type": "node_mastered", "node_id": "..."}
  ],
  "session": {"id": "...", "state": "learning", "attempts_left": 3}
}
```

前端**无状态判断逻辑**：所有"下一步显示什么"由后端状态机裁决（防止前端逻辑分支漂移）。

### 2.1 流式协议（R12-b，SSE 可选）

`POST /session/step?stream=1`（body 与普通 step 相同）返回 `text/event-stream`：

- `event: start` → `{"session_id", "action"}`；
- 处理期间每 ~1s 心跳：`event: ping` → `{"seconds"}`；
- 结束：`event: result` → **与普通响应完全一致的完整 JSON**（上文 §2 结构，契约不变）；
- 失败：`event: error` → `{"code", "message"}`（code 同 §4 错误码）。

约定：前端把流的 `result` 当作普通 step 响应处理；流不可用/解析失败/`error` 事件时
**自动回退普通 `POST /session/step`**；服务端同步逻辑跑在工作线程，不占事件循环，
LLM 等待前仍按 R7 先提交事务释放写锁。长文本（讲解/答疑回复/追问）由前端做打字机展示。

## 3. SQLite 表结构草案

```sql
users        (id TEXT PK, profile_json TEXT, created_at)            -- MVP 恒为 'local'
nodes        (id TEXT PK, yaml_path TEXT, title, level, topic,
              objectives_json, core_concepts_json, feynman_json,
              content_hash, enabled INTEGER)
edges        (node_id TEXT, prereq_id TEXT, PK(node_id, prereq_id))
             -- 内容库加载时由 `content validate` 写库，确保与文件一致（content_hash 校验）
user_nodes   (user_id, node_id, state TEXT,           -- locked/available/learning/mastered/reviewing
              consecutive_correct INT, attempts_total INT,
              last_error_type TEXT, mastered_at, PK(user_id,node_id))
sessions     (id TEXT PK, user_id, node_id, state TEXT,  -- 状态机当前步
              flow_json TEXT,           -- 会话内累积数据（练习计数、费曼轮次等）
              created_at, updated_at)
attempts     (id INTEGER PK, session_id, node_id, kind TEXT,   -- exercise|feynman
              exercise_id, params_json, user_input TEXT,
              verdict TEXT,             -- correct|wrong|score|pass|fail|deferred
              error_type TEXT NULL, meta_json, created_at)
reviews      (user_id, node_id, state_json,            -- FSRS 状态
              due_at, last_rating, lapse_count, PK(user_id,node_id))
ai_logs      (id INTEGER PK, call_name, model, tier, prompt_tokens, completion_tokens,
              ok INTEGER, error TEXT, latency_ms, created_at)
relearn_logs (user_id, node_id, reason TEXT, created_at)   -- mastered→learning 降级留痕
```

- 迁移策略：MVP 用 SQLAlchemy `create_all`；表结构变化时人工写 `ALTER` 迁移脚本放 `backend/migrations/`（不上 alembic，但结构保持文档同步）。
- 并发：本地单机单用户，无并发问题；但仍建议 SQLite `WAL` 模式。

## 4. 错误码（约定）

| code | 含义 |
|---|---|
| `not_found` / `invalid_state` | 会话已结束或状态非法（前端应刷新会话）；`/session/start` 的 `invalid_state` = **越级进入未解锁节点（R18 总序门禁）**，detail 含前置提示 |
| `ai_unavailable` | LLM 降级已发生（响应中带 `degraded: true`） |
| `exercise_broken` | 模板不可渲染（应触发 content 告警，不计入用户失败） |
| `validation_error` | 入参格式错 |
