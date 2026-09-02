# 混合检索设计

日期：2026-09-01

状态：用户已确认，进入实现

## 目标

在现有 SQLite/FTS5 基线上增加真正的语义召回，同时保持评测方看到的
Add/Search HTTP 契约不变。Search 最终仍然只返回原始消息证据。

## 本次范围

- 增加可插拔的 `Embedder` 接口；
- 提供不增加第三方依赖的 OpenAI 兼容 Embeddings HTTP 适配器；
- Add 时批量生成消息向量，并与原始消息放在同一个 SQLite 事务中提交；
- 向量以稳定的 float32 BLOB 持久化，并保留模型与维度；
- Search 时分别取得 BM25 和向量候选，再用 RRF 合并名次；
- 融合后再做原有的同会话邻居扩展；
- 默认不配置 Embedding 时，行为完全退回现有 BM25 基线。

## 不做的内容

- 不加入知识图谱、事实抽取、时间推理或最终答案生成；
- 不增加向量数据库、NumPy、OpenAI SDK 等依赖；
- 不把模型生成文本写成证据；
- 不在 Embedding 服务失败时静默切换检索方法。

## 写入流程

```text
Add 请求
  -> 校验原始消息
  -> 只读检查 request_id：重复请求直接成功，冲突请求直接 409
  -> 未启用 Embedding：沿用原 SQLite + FTS5 事务
  -> 已启用 Embedding：一次批量请求生成全部消息向量
  -> 校验数量、维度、有限值和非零向量
  -> 原始消息 + FTS5 + message_vectors 同事务提交
  -> 成功后返回 200
```

外部 Embedding 在开启数据库事务前完成，避免网络等待长期占用 SQLite 写锁。
如果生成失败，Add 不写入任何消息。事务提交失败时，消息、FTS 和向量一起回滚。
写入事务仍会再次检查 request_id，用来处理预检之后发生的并发竞争。

## 检索流程

```text
Search 请求
  -> BM25 候选（始终可用）
  -> 查询向量 + 余弦相似度候选（配置后启用）
  -> RRF(k=60) 融合两个名次列表
  -> 分数归一化
  -> 同用户、同会话邻居扩展
  -> 回表返回原始消息证据
```

RRF 只使用名次，不直接比较 BM25 分数和余弦相似度。每路候选数量有上限，
避免随着功能增加无界扩大后续排序集合。

## 存储

新增 `message_vectors`：

| 字段 | 说明 |
| --- | --- |
| `message_id` | 原始 `messages.id`，主键和外键 |
| `user_id` | 用户隔离键 |
| `model` | 生成向量的模型名 |
| `dimensions` | 向量维度 |
| `embedding` | 小端 float32 BLOB |
| `created_at` | 写入时间 |

向量查询同时过滤 `user_id`、`model` 和 `dimensions`，取回的消息再次校验
`messages.user_id`，避免跨用户候选泄漏。

## 配置

默认 `MEMORY_EMBEDDING_PROVIDER=none`。启用 OpenAI 兼容接口时需要：

- `MEMORY_EMBEDDING_PROVIDER=openai-compatible`
- `MEMORY_EMBEDDING_API_KEY`
- `MEMORY_EMBEDDING_MODEL`，默认 `text-embedding-3-small`
- `MEMORY_EMBEDDING_BASE_URL`，默认 `https://api.openai.com/v1`
- 可选 `MEMORY_EMBEDDING_DIMENSIONS` 和请求超时

密钥只从环境变量读取，不进入日志、API 请求体、数据库或错误响应。

## 当前性能边界

本次 SQLite 实现用纯 Python 计算余弦相似度，目的是先建立正确、可测试、可替换的
语义检索通路。它适合本地演示和中小规模回归，不宣称适合百万级向量。
后续只需替换 `search_vectors` 的后端即可接入 sqlite-vec、FAISS 或独立向量库，
Add/Search 契约和融合逻辑不用改。

## 验收

- 没有相同关键词的同义问题能够召回原始消息；
- 精确姓名、日期等 BM25 能力不退化；
- 两路都命中的候选优先于单路命中；
- 向量重启后仍可搜索；
- 向量检索严格隔离 `user_id`；
- Embedding 失败时 Add 不产生部分数据；
- 默认无模型配置时全部现有测试保持通过。
