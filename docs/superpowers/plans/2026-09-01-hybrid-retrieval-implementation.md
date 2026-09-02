# 混合检索实施计划

日期：2026-09-01

## 1. 用测试定义向量边界

涉及：`tests/test_embeddings.py`、`tests/test_store.py`、
`tests/test_retrieval.py`、`tests/test_api_add_search.py`。

- 为测试提供确定性的 Fake Embedder；
- 先写 OpenAI 兼容响应解析、向量持久化、用户隔离、同义召回、RRF 和 API 原子写入测试；
- 运行这些测试并确认因缺少新接口而失败。

验收点：失败原因指向尚未实现的 Embedding/向量能力，不是测试本身语法错误。

## 2. 增加模型与接口

涉及：`src/aml_memory/models.py`、`src/aml_memory/ports.py`、
`src/aml_memory/embeddings.py`。

- 定义不可变的 Embedding 批次模型并集中校验；
- 定义 `Embedder` 协议；
- 用标准库实现同步 OpenAI 兼容 `/embeddings` 请求；
- 对 HTTP、JSON、数量、索引和向量异常返回脱敏错误。

验收点：适配器测试通过，不发真实网络请求，不记录输入或密钥。

## 3. 持久化向量

涉及：`src/aml_memory/store.py`、`src/aml_memory/ports.py`。

- 创建 `message_vectors` 表和用户/模型索引；
- 把向量与消息放进同一个 Add 事务；
- 实现 float32 BLOB 编解码和余弦排序；
- 查询时重复执行用户隔离校验。

验收点：向量跨 Store 实例存在，维度和模型不匹配不会混用，跨用户不泄漏。

## 4. 实现混合检索

涉及：`src/aml_memory/retrieval.py`。

- 保留现有 `LexicalRetrievalPipeline`；
- 新增 `HybridRetrievalPipeline`；
- 分别获取 BM25/向量候选；
- 用 `k=60` 的 RRF 融合并按消息序号稳定破平；
- 复用同会话邻居扩展。

验收点：同义问题被召回；双路命中优先；精确检索和邻居测试不退化。

## 5. 接入服务与配置

涉及：`src/aml_memory/config.py`、`src/aml_memory/service.py`、
`src/aml_memory/app.py`。

- 环境配置默认关闭 Embedding；
- 开启时校验 provider、key、model、维度和超时；
- Add 在存储前生成向量；
- 调用外部模型前先处理已存在 request_id，保留幂等成功和冲突 409；
- App 选择词法或混合检索管线；
- 测试允许注入 Fake Embedder。

验收点：默认应用行为不变；启用 Fake Embedder 的真实 API 路径完成语义 Add/Search；
Embedding 失败时数据库保持空。

## 6. 文档和完整验证

涉及：`README.md`。

- 说明启用方式、数据流、成本和当前线性扫描边界；
- 运行 Ruff、Mypy、Pytest、Compileall；
- 启动本地服务完成默认 BM25 HTTP 冒烟；
- 用 Fake Embedder 完成不依赖密钥的语义 API 演示测试。

验收点：所有验证命令通过，默认模式不需要外部密钥，正式 OpenAI 调用仅缺真实凭据验证。
