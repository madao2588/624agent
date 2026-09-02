# 624agent 当前项目总结

更新日期：2026-09-02

当前阶段：候选实现已完成公开数据全量证据评测，尚未冻结为正式参评版本

## 先说结论

624agent 已经不是“靠冒号或固定符号触发搜索”的原型了。它现在是一个证据优先的单人多轮记忆服务：写入原始对话，建立词法、结构化状态和关系索引，再按自然语言问题找回同一用户的原始消息。没有可靠证据时返回空结果，不替评测系统编答案。

现在也终于有了一份能说明真实水平的公开数据结果：LongMemEval-S 全量 500 条记录已跑完，470 条有证据标注的问题中，Session Recall-any@5 为 **75.96%**，Turn Recall-all@5 为 **34.47%**。前者说明多数问题能先找到正确会话，后者说明要找齐回答所需的每一条消息仍不够强，尤其是 assistant 侧事实、偏好归纳和多会话问题。

这轮原定的核心开发已经完成：

- 本地无 Key 的结构化记忆检索；
- 固定 `gpt-4o-mini` 的 evaluation 模式，Add 和 Search 都有受约束的模型调用；
- 更新、取消、恢复、遗忘、偏好、规则和三跳关系检索；
- 召回原因、状态时间线和关系图的可解释界面；
- 官方 LongMemEval-S 格式适配、逐题证据映射和检索指标报告；
- 最大并发黑盒预检、CI、秘密扫描和提交说明。

目前服务主体和可复现评测入口已经具备，但真实基准暴露了两个代码内短板：语义弱重合问题的候选召回，以及跨会话多证据找全。外部仍需要真实模型凭证、评测资格与参赛者身份信息。本机 Docker Desktop 仍有运行时故障，但此前同一实现的 GitHub CI 已完成干净镜像构建和容器预检。

## 系统实际怎么工作

### Add：把对话写成可检索记忆

```text
Add 请求
  → 严格校验 request_id / user_id / session_id
  → 先做幂等检查
  → 本地提取人物、地点、时间、事件、偏好和规则标签
  → evaluation 模式再用固定模型补充受约束标签
  → 建立 FTS5/BM25、中文双字、状态链和关系边
  → 可选生成向量
  → 在同一个 SQLite 事务中写入
```

同一个 `request_id` 和相同内容重复提交不会重复写入，也不会再次调用模型；相同 ID 携带不同内容会返回 409。

### Search：只找证据，不生成答案

```text
自然语言问题和选项
  → BM25 / 中文双字检索
  → 人物、时间、事件、偏好、规则等结构通道
  → 当前状态或显式历史状态链
  → 最多三跳的来源关系扩展
  → 过滤遗忘内容、Prompt Injection 和弱相关噪声
  → 有依据的去重与重排
  → 返回当前 user_id 的原始消息
```

evaluation 模式会先让固定的 `gpt-4o-mini` 生成有限的检索词；模型输出只参与找证据，不会作为证据或答案返回。

## 现在具备的能力

### 记忆和治理

- 事实、人物、别名、代词、地点、日期和相对时间；
- 事件的更新、取消、恢复、遗忘和可审计历史；
- 偏好、厌恶、习惯与一次性行为的区分；
- 条件、要求、禁止、顺序和例外规则；
- 两跳、三跳的来源关系检索；
- 普通问题隐藏已遗忘内容，显式历史问题仍可审计；
- 存储型 Prompt Injection 不进入普通召回。

### 四种运行路径

| 路径 | Key | 用途 | 边界 |
| --- | --- | --- | --- |
| 本地模式 | 不需要 | 默认演示、开发、离线回归 | FTS5/BM25 + 结构标签 + 状态与关系 |
| DeepSeek 查询扩展 | 需要 | 中英问题改写和相关词扩展 | 只发送当前问题，不发送记忆正文 |
| OpenAI-compatible Embedding | 需要 | BM25 + 向量相似度融合 | 向量持久化；当前实现适合中小规模 |
| evaluation 模式 | 需要 | 冻结方法参评 | 固定 `gpt-4o-mini`，禁止临时连接覆盖 |

### 固定 evaluation 模式

配置文件是 [`../evaluation/evaluation-profile.json`](../evaluation/evaluation-profile.json)。它固定了模型、候选规模、三跳关系、相关性阈值、超时、重试和熔断参数。

模型客户端使用 OpenAI Responses API 严格结构化输出：

- Add：补充每条消息的有限结构标签；
- Search：生成有限检索词；
- `store: false`；
- 输入、输出和消息数量都有上限；
- 408、409、429 和 5xx 只做有限重试；
- 连续失败触发短时熔断；
- 错误返回脱敏 503，不记录 Key、正文或模型响应；
- Add 失败不会留下部分写入。

## 可解释演示页

启动服务后打开 <http://127.0.0.1:8000/demo>。

页面现在可以：

1. 写入同一个人的三段多轮对话；
2. 继续补充事实或计划变化；
3. 用自然语言提问；
4. 查看每条原始证据；
5. 查看“文字命中、结构标签、状态链、向量或模型扩展”等召回原因；
6. 查看当前、历史、取消和遗忘状态时间线；
7. 查看新记忆取代旧记忆、共享人物或地点的关系图；
8. 可选保存浏览器中的提供商配置和 Key，并随时清除。

诊断页使用隐藏接口 `POST /v1/memories/search/diagnostics`。它和正式 Search 共用检索管线、鉴权和用户隔离，但不会出现在 OpenAPI 中，也没有改变排行榜要求的 Search 响应。

## 本轮实测证据

以下结果来自当前工作区刚运行的命令：

| 检查 | 结果 |
| --- | --- |
| `python -m pytest -q` | 178 passed |
| `python -m ruff check .` | 通过 |
| `python -m mypy src scripts` | 29 个源码文件无类型错误 |
| `python -m compileall -q src tests scripts` | 通过 |
| `python scripts/scan_secrets.py` | 通过 |
| `python scripts/run_memory_challenges.py` | 20 组场景全部符合预期 |
| 本地 Recall@K / MRR / nDCG | 1.000 / 1.000 / 1.000 |
| 本地噪声率 / 空结果准确率 | 0.040 / 1.000 |
| 本地平均 / P95 搜索延迟 | 13.82 ms / 17.76 ms |
| LongMemEval-S 全量语料 | 500 条完成；470 条检索计分，30 条 abstention 跳过 |
| LongMemEval-S Session any@5 / all@5 | 75.96% / 58.51% |
| LongMemEval-S Turn any@5 / all@5 | 56.81% / 34.47% |
| LongMemEval-S Turn nDCG@5 | 39.82% |
| LongMemEval-S 搜索平均 / P95 延迟 | 166.72 ms / 336.40 ms |
| 黑盒预检 | 6 项、328 次操作全部通过 |
| 并发 Add | 64 次，2106 ms |
| 并发 Search | 256 次，7134 ms |
| 浏览器验收 | 桌面与 375px 手机流程通过，控制台 0 错误，无横向溢出 |
| GitHub CI | 提交 `25ffd59` 的质量检查、镜像构建和容器预检全部通过 |

20 组自建场景的满分只用于防回归。LongMemEval-S 是公开语料上的来源检索结果，但没有运行 answer reader 或 LLM judge，因此同样不是官方榜单成绩，也不能预测私有测试集表现。完整方法、分项和限制见 [`longmemeval-s-results.md`](longmemeval-s-results.md)。

## 怎么运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn aml_memory.app:app --host 127.0.0.1 --port 8000
```

无 Key 的直观测试：

```powershell
.\.venv\Scripts\python.exe scripts\run_memory_challenges.py
```

公开 LongMemEval-S 的分层冒烟和全量运行方式见 [`longmemeval-s-results.md`](longmemeval-s-results.md)。数据文件约 277 MB，不进入 Git；运行器会把逐题证据、汇总 JSON 和 Markdown 报告写入 `artifacts/longmemeval/`。

完整检查：

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
.\.venv\Scripts\python.exe scripts\scan_secrets.py
```

安全的环境变量模板见 [`.env.example`](../.env.example)。真实 Key 只能在运行时注入，不能提交到 Git。

## 还差什么

### 代码内待办

1. **语义候选召回**：优先解决 preference 和 assistant fact。当前 Turn all@5 分别只有 23.33% 和 25.00%。
2. **多证据聚合**：优先解决 multi-session。它的 Session any@5 已有 89.26%，但 Turn all@5 只有 19.01%，说明经常找到了正确会话却没找齐证据。
3. **Reader/Judge 分层**：在检索指标稳定后，再单独评测最终答案和 abstention；不能把生成质量与来源召回混成一个本地分数。
4. **重新冻结提交**：本轮 LongMemEval 适配完成验证和推送后，以新提交为参评候选，不再沿用旧的 `25ffd59`。

### 外部阻塞

1. **本机 Docker Desktop**：当前机器的 Docker Desktop 在启动时被损坏的 `dockerInference` 本地套接字阻断，因此没有在这台机器上构建镜像。没有执行“恢复出厂设置”，镜像和卷未受影响。同一提交的 GitHub CI 已成功完成干净镜像构建、页面检查和 64/256 容器黑盒预检，所以这是本机环境问题，不是当前仓库的构建失败。
2. **正式模型实调**：固定模型客户端、重试、熔断、结构化输出和失败路径都已用可控假服务测试；仍需要参赛者提供正式 OpenAI Key 后做一次真实请求冒烟。
3. **官方评测**：需要评测申请获批、由参赛者填写联系人和团队信息，再运行平台私有测试。当前没有官方成绩。

## 正式提交前清单

- [x] Add/Search 合同、持久化、幂等和用户隔离
- [x] 结构化状态、偏好、规则、安全过滤和三跳关系
- [x] 固定 evaluation 模式的 Add/Search 模型接线
- [x] 诊断接口、状态时间线、关系图和响应式页面
- [x] 178 项测试、静态检查、秘密扫描和本地 64/256 黑盒预检
- [x] GitHub CI 冷构建镜像并完成容器内预检
- [x] LongMemEval-S 500 条公开语料完成来源检索评测
- [ ] 真实 `gpt-4o-mini` 冒烟
- [ ] 填写联系人和团队信息
- [x] 实现提交并推送到 GitHub `main`
- [ ] 打正式参评标签
- [ ] 申请并运行官方评测

## 关键文件

- 使用说明：[`../README.md`](../README.md)
- 参评说明：[`../evaluation/SUBMISSION.md`](../evaluation/SUBMISSION.md)
- 固定评测配置：[`../evaluation/evaluation-profile.json`](../evaluation/evaluation-profile.json)
- 20 组可读场景：[`../evaluation/memory_challenges.json`](../evaluation/memory_challenges.json)
- LongMemEval-S 全量结果：[`longmemeval-s-results.md`](longmemeval-s-results.md)
- LongMemEval-S 运行器：[`../scripts/run_longmemeval.py`](../scripts/run_longmemeval.py)
- 完成路线：[`superpowers/plans/2026-09-02-roadmap-completion-implementation.md`](superpowers/plans/2026-09-02-roadmap-completion-implementation.md)
