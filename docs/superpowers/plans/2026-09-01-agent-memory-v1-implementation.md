# Agent Memory V1 实施计划

设计依据：`docs/superpowers/specs/2026-09-01-agent-memory-design.md`

目标：交付一个可通过 AML Add/Search 契约冒烟测试的模块化文本记忆服务，并为混合检索和后续 Agentic Retrieval 保留稳定扩展边界。

执行规则：每项行为都先写测试并确认失败，再写使其通过的最小实现；每个阶段完成后运行相关测试，最后运行完整质量门禁。

## 任务 1：建立 Python 项目骨架和质量门禁

创建：

- `pyproject.toml`
- `.gitignore`
- `.dockerignore`
- `src/aml_memory/__init__.py`
- `tests/__init__.py`

内容：

- Python 支持版本设为 `>=3.11`；
- 运行依赖：FastAPI、Uvicorn；
- 开发依赖：pytest、HTTPX、Ruff、mypy；
- 配置 pytest 的 `pythonpath=src`；
- 配置 Ruff 和 mypy 的基础严格规则；
- 忽略数据库、缓存、虚拟环境、日志和密钥文件。

验收：

- `python -m pytest --collect-only` 可执行；
- `python -m ruff check .` 可执行；
- `python -m mypy src` 可执行。

## 任务 2：健康检查和应用生命周期

先创建失败测试：

- `tests/test_health.py`

再创建实现：

- `src/aml_memory/config.py`
- `src/aml_memory/app.py`

行为：

- `create_app()` 支持测试时注入数据库路径；
- FastAPI lifespan 中创建和关闭数据库资源；
- `GET /health` 返回 HTTP 200 和 `{"status":"ok"}`；
- 健康检查执行轻量数据库探测。

验收：

- 先看到健康检查测试因模块或路由不存在而失败；
- 实现后 `python -m pytest tests/test_health.py -q` 通过。

## 任务 3：定义 API Schema 和契约校验

先创建失败测试：

- `tests/test_contract_validation.py`

再创建实现：

- `src/aml_memory/schemas.py`

覆盖：

- Add 必填字段；
- 非空消息、内容、用户和会话 ID；
- `role` 仅接受 `user|assistant`；
- 时间戳为可选 Unix 毫秒整数；
- Search 的 `top_k` 限制为 1..100；
- Search `options` 可选；
- 响应 schema 严格输出 `data` 包装。

验收：

- 非法请求返回 422；
- 合法 schema 可完成序列化。

## 任务 4：SQLite 原始消息存储与幂等事务

先创建失败测试：

- `tests/test_store.py`

再创建实现：

- `src/aml_memory/models.py`
- `src/aml_memory/store.py`
- `src/aml_memory/errors.py`

实现：

- `add_requests`、`messages` 和 FTS5 表；
- WAL、外键和 busy timeout；
- 规范化负载 SHA-256；
- 一个 Add 一个事务；
- 相同 request ID/相同 hash 幂等成功；
- 相同 request ID/不同 hash 抛出领域冲突；
- 稳定消息 ID；
- 按用户和会话查询消息及邻居。

验收：

- 部分失败不会留下消息；
- 关闭并重新打开数据库后数据仍存在；
- 两个用户使用相同内容时记录互不影响。

## 任务 5：FTS5 安全词法检索和证据格式化

先创建失败测试：

- `tests/test_retrieval.py`

再创建实现：

- `src/aml_memory/retrieval.py`
- `src/aml_memory/formatting.py`

实现：

- 将自然语言查询保守转换为 FTS5 token OR 查询；
- 对引号、括号、连字符等 FTS 特殊输入不报 500；
- 候选阶段和回表阶段都应用 `user_id`；
- BM25 结果转换为稳定的高分优先证据分数；
- 命中后在同用户、同会话内扩展相邻消息；
- 去重，按命中优先和稳定次序返回；
- 格式化时间、角色和未改写内容。

验收：

- 精确关键词可检索；
- 不同措辞但无共同词时基线允许空结果；
- 特殊字符查询不导致服务错误；
- 邻居不会跨用户或跨会话扩展。

## 任务 6：MemoryService 和 Add/Search API

先创建失败测试：

- `tests/test_api_add_search.py`
- `tests/test_idempotency.py`
- `tests/test_user_isolation.py`

再创建实现：

- `src/aml_memory/service.py`
- 更新 `src/aml_memory/app.py`

实现：

- `POST /v1/memories/add`；
- `POST /v1/memories/search`；
- 兼容别名 `POST /add`、`POST /search`；
- Add 冲突映射为 HTTP 409；
- Search 返回原始证据且不超过 `top_k`；
- 依赖由 app factory 注入，便于替换存储和检索实现。

验收：

- Add 后同一请求中可立即 Search；
- 重复 Add 不增加消息数量；
- 用户 B 搜不到用户 A 的任何内容；
- Search 响应没有最终答案字段或额外顶层包装。

## 任务 7：并发、持久化和日志安全

先创建失败测试：

- `tests/test_concurrency.py`
- `tests/test_restart_recovery.py`
- `tests/test_logging_safety.py`

再调整：

- `src/aml_memory/store.py`
- `src/aml_memory/app.py`

实现：

- 每个操作使用独立 SQLite 连接，避免跨线程共享连接；
- 并发相同 Add 最终只存在一份消息；
- SQLite locked 使用 busy timeout，不做无界重试；
- 日志只记录结构化元数据，不记录消息、查询或密钥；
- 重启后重新打开同一数据库即可检索。

验收：

- 并发测试无重复写入和未处理异常；
- 数据库重开后 Search 结果一致；
- 捕获日志中不存在测试负载秘密字符串。

## 任务 8：Docker、冒烟脚本和使用文档

创建：

- `Dockerfile`
- `scripts/smoke_test.py`
- `README.md`

内容：

- Python 3.11 slim 镜像；
- 非 root 用户运行；
- 数据目录 `/data`；
- 默认监听 `0.0.0.0:8000`；
- 健康检查；
- 冒烟脚本完成 health -> Add -> Search -> isolation；
- README 说明架构、配置、运行、测试、API 和 AML 提交边界。

验收：

- `docker build -t aml-memory-v1 .` 成功；
- 容器启动后冒烟脚本通过；
- 挂载卷重启后记忆仍可搜索。

## 任务 9：完整质量门禁和设计一致性检查

执行：

```powershell
python -m ruff check .
python -m mypy src
python -m pytest -q
python -m compileall -q src tests scripts
docker build -t aml-memory-v1 .
```

随后启动容器并运行：

```powershell
python scripts/smoke_test.py http://127.0.0.1:8000
```

检查：

- API 响应与设计文档一致；
- 没有越过 `user_id` 的读写路径；
- Search 内容来自原始消息；
- 无密钥、数据库或缓存进入 Git；
- 记录 V1 未覆盖项：语义召回、RRF、LLM 查询规划、正式公开数据集得分。

完成后更新 README 的验证证据和剩余风险，不创建提交，除非用户另行要求。

## 后续 V2 入口

V1 通过后，V2 从以下测试开始：

- 两个没有共同关键词但语义相同的句子能够互相召回；
- BM25 和 Dense 候选使用 RRF 融合；
- Embedding 失败时按配置选择确定性降级或清晰失败；
- 向量候选仍必须通过 `user_id` 回表验证；
- 返回集合与排序通过公开 LoCoMo/AML 提示端到端回归，而不是只看 Recall。
