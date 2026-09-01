# Agent Memory Leaderboard 应试记忆系统设计

日期：2026-09-01

状态：用户已确认
目标路线：Academic Textual Memory / 公开代码 / 平台部署

## 1. 设计目标

构建一个符合 Agent Memory Leaderboard Add/Search 契约的长期记忆服务。首版重点是可参赛、可复现、可测试和可扩展，而不是一次性堆叠复杂的 Agent 能力。

系统负责：

- 同步接收并持久化对话消息；
- 保证 `request_id` 幂等；
- 按 `user_id` 严格隔离数据；
- 从历史中检索并排序原始证据；
- 为命中结果补充必要的会话上下文；
- 向平台返回证据，不生成最终答案；
- 提供可替换的存储、检索、融合、重排和模型适配边界。

## 2. 非目标

首版不实现：

- 面向最终用户的聊天界面；
- 独立的最终答案生成器；
- 知识图谱或多 Agent 编排；
- 依赖未公开评测数据的定向规则；
- 将模型生成内容当成唯一事实来源；
- 与正式评测契约无关的账号、计费或管理后台。

这些能力不得侵入核心 Add/Search 契约，未来只能以独立适配器或服务层扩展的方式加入。

## 3. 核心原则

1. 原始证据优先：原始消息是事实来源，抽取事实和摘要只能作为检索辅助。
2. 写入可见性：Add 返回成功前，所有消息必须已持久化并立即可搜索。
3. 精确隔离：所有读写路径都必须显式携带并校验 `user_id`。
4. 幂等优先：相同 `request_id` 和相同负载可重复成功；相同 ID 和不同负载返回 409。
5. 确定性基线：不开启外部模型时，系统仍能稳定运行和复现结果。
6. 逐层增强：先完成可靠的 FTS5 基线，再增加 Embedding、混合融合、查询规划和记忆治理。
7. 证据而非答案：Search 只返回有来源的记忆内容，不直接回答评测问题。

## 4. 总体架构

```text
AML Platform
  |-- GET  /health
  |-- POST /v1/memories/add
  `-- POST /v1/memories/search
             |
             v
        API / Schemas
             |
             v
        MemoryService
        |-- Add orchestration
        |-- Search orchestration
        |-- Idempotency policy
        `-- Evidence formatting
             |
       +-----+--------------------+
       |                          |
       v                          v
  MessageStore               RetrievalPipeline
  |-- SQLite                 |-- Query planner
  |-- transactions           |-- Lexical retriever
  |-- user isolation         |-- Vector retriever (optional)
  `-- neighbor lookup        |-- Rank fusion
                             |-- Context expansion
                             `-- Reranker (optional)
```

API、领域服务和基础设施通过显式接口分开。SQLite/FTS5 是首版实现，但领域服务不得依赖 SQLite 特有的数据结构。

## 5. API 契约

### 5.1 健康检查

`GET /health`

- 无需鉴权；
- 服务和数据库可用时返回 HTTP 200；
- 响应为简单 JSON，例如 `{"status":"ok"}`。

### 5.2 Add

`POST /v1/memories/add`

请求：

```json
{
  "request_id": "eval:run:sample:chunk-0",
  "messages": [
    {
      "role": "user",
      "timestamp": 1704067200000,
      "content": "I adopted a cat named Luna."
    }
  ],
  "user_id": "eval:run:user-0",
  "session_id": "eval:run:session-0"
}
```

规则：

- `request_id`、非空 `messages`、`user_id`、`session_id` 必填；
- `role` 只接受 `user` 或 `assistant`；
- `timestamp` 可选，单位为 Unix 毫秒；
- 所有消息在一个数据库事务中提交；
- 成功响应前必须可被 Search 查询；
- 相同请求重复提交返回相同成功结果；
- 相同 `request_id` 对应不同规范化负载时返回 HTTP 409。

成功响应：

```json
{
  "success": true,
  "request_id": "eval:run:sample:chunk-0",
  "user_id": "eval:run:user-0",
  "session_id": "eval:run:session-0"
}
```

### 5.3 Search

`POST /v1/memories/search`

请求：

```json
{
  "query": "What is the name of my cat?",
  "options": ["Luna", "Milo"],
  "user_id": "eval:run:user-0",
  "top_k": 100
}
```

规则：

- `query`、`user_id`、`top_k` 必填；
- `options` 可选，只能作为检索提示，不得被当成最终答案；
- `top_k` 限制在 1 到 100；
- 所有检索和上下文扩展都必须限制在相同 `user_id` 内；
- 无结果时返回空 `data` 数组；
- 返回顺序即最终证据顺序。

响应：

```json
{
  "data": [
    {
      "id": "memory-id",
      "content": "[2024-01-01T00:00:00Z] USER: I adopted a cat named Luna.",
      "score": 1.0,
      "created_at": "2026-09-01T00:00:00Z"
    }
  ]
}
```

## 6. 数据模型

### 6.1 `add_requests`

| 字段 | 说明 |
| --- | --- |
| `request_id` | 主键 |
| `payload_hash` | 规范化请求负载的 SHA-256 |
| `user_id` | 所属用户 |
| `session_id` | 所属会话 |
| `created_at` | 服务写入时间 |

### 6.2 `messages`

| 字段 | 说明 |
| --- | --- |
| `id` | 稳定、非空的记忆 ID |
| `request_id` | 对应 Add 请求 |
| `user_id` | 强隔离键 |
| `session_id` | 会话键 |
| `ordinal` | 消息在 Add 请求中的顺序 |
| `role` | `user` 或 `assistant` |
| `occurred_at_ms` | 来源时间，可空 |
| `content` | 未改写的原始文本 |
| `created_at` | 服务写入时间 |

### 6.3 FTS 索引

FTS5 索引至少保存 `message_id`、`user_id` 和 `content`。检索时必须在候选查询和最终消息查询两处执行 `user_id` 过滤，形成纵深防御。

未来的向量、实体、事实或状态表只能引用原始 `messages.id`，不能替代原始消息。

## 7. 写入流程

1. Pydantic 校验请求。
2. 对规范化负载生成稳定 SHA-256。
3. 查询 `request_id`：
   - 不存在：继续；
   - hash 相同：返回幂等成功；
   - hash 不同：返回 409。
4. 开启 SQLite 事务。
5. 按消息顺序生成稳定 ID 并写入原始消息。
6. 同步更新 FTS5；未来可同步更新向量索引。
7. 写入 `add_requests`。
8. 提交事务。
9. 返回成功响应。

任何步骤失败都回滚，不能留下部分可见的 Add。

## 8. 检索流程

首版流程：

1. 校验 `query`、`user_id`、`top_k`。
2. 对查询做保守的 FTS5 词法化，避免把用户输入直接拼接进 FTS 查询语法。
3. 在指定用户分区中执行 BM25 检索。
4. 按命中消息 ID 获取原始消息。
5. 在同用户、同会话内补充相邻消息。
6. 去重并保持确定性顺序。
7. 将时间、角色和原始内容格式化为证据。
8. 最多返回 `top_k` 条。

混合检索增强：

1. 词法检索与向量检索独立产生候选排名。
2. 使用 RRF 融合，不直接比较不可校准的原始分数。
3. 可选重排器只能重新排列候选 ID，不得生成新证据。
4. 最终仍回表读取原始消息并格式化。

## 9. 扩展边界

以下组件使用协议或抽象基类定义：

- `MessageStore`：持久化、幂等和邻居查询；
- `Retriever`：返回带排名的候选消息 ID；
- `Embedder`：文本到向量；
- `RankFusion`：融合多个候选排名；
- `QueryPlanner`：生成受限检索查询，不生成答案；
- `Reranker`：对允许列表内的候选排序；
- `MemoryAnnotator`：生成事实、实体或状态注释；
- `RetentionPolicy`：清理过期评测数据。

默认实现必须在没有外部 API Key 时工作。任何 LLM 增强均通过配置显式开启，失败时要么安全降级，要么返回清晰错误，不能静默改变评测方法。

## 10. 错误处理

- 422：请求结构或字段校验失败；
- 409：`request_id` 冲突；
- 500：不可恢复的存储或服务错误；
- 日志只记录 request ID、阶段、耗时、数量和错误分类；
- 不记录完整记忆、评测问题、API Key 或 Authorization 头。

## 11. 验证策略

测试必须先于实现，至少覆盖：

- 健康检查；
- Add/Search 响应结构；
- Add 后立即可搜索；
- 重复 Add 幂等；
- 冲突 Add 返回 409；
- 用户隔离；
- 会话相邻消息扩展；
- `top_k` 上限；
- 空结果；
- 数据库重启恢复；
- 非法角色和空字段；
- 并发重复 Add；
- 日志不泄漏负载或密钥。

验证分层：

1. 单元测试：规范化、hash、排序、格式化；
2. 存储集成测试：事务、幂等、隔离、持久化；
3. API 契约测试：真实 FastAPI 请求/响应；
4. Docker 冒烟测试：容器启动后完成 Add/Search；
5. 公开评测回归：接入官方公开流水线后记录配置与结果。

## 12. 分阶段交付

### V1：可靠契约基线

- FastAPI API；
- SQLite 原始消息存储；
- FTS5 检索；
- 幂等、隔离、持久化；
- 相邻上下文；
- Docker 和完整契约测试。

### V2：混合检索

- 可插拔 Embedding；
- 向量候选存储；
- BM25 + Dense + RRF；
- 公开数据集回归。

### V3：时间与记忆治理

- 时间查询线索；
- 事实更新、冲突和当前状态注释；
- 原始证据可追溯；
- 数据保留和自动清理。

### V4：受控 Agentic Retrieval

- 使用规则允许的模型做查询规划；
- 多跳证据需求；
- 有界二次检索；
- 候选允许列表内重排；
- 成本、延迟和准确率消融。

## 13. 完成定义

V1 只有在以下条件全部满足后才算完成：

- 所有契约与隔离测试通过；
- Add 成功后立即可搜索；
- 重启后数据存在；
- 同一请求并发重试不重复写入；
- Docker 可复现启动；
- Search 永远只返回原始证据；
- 未发现跨用户读取路径；
- README 包含启动、配置、API、测试和提交说明；
- 已记录未覆盖的正式榜单风险。
