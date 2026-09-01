# Agent Memory Leaderboard 评测接入设计

日期：2026-09-01

状态：用户已确认

## 1. 目标

把当前 `624agent` 仓库准备成 Agent Memory Leaderboard 的“学术方法 · 代码提交”候选版本。平台维护者应能够从公开 GitHub 仓库构建 Docker 镜像、启动服务，并用官方同步 Add/Search 合同完成 smoke 和后续评测。

当前评测周期尚未开放，因此本阶段不声称获得官方分数，也不模拟平台私有的 Answer/Eval 流程。本阶段交付“可复现、可自动验证、可提交审核”的集成能力。

官方规范来源：<https://agentmemoryleaderboard.ai/api-guide>

## 2. 已选路线

- 参赛组别：Academic Methods
- 评测类型：Textual Memory
- 提交方式：公开代码，由平台构建和部署
- 仓库：<https://github.com/madao2588/624agent>
- 运行方式：Docker
- 对外合同：同步 Add/Search，Health 无鉴权

该路线不依赖 Leaderboard Eval Key。平台收到申请并完成审核后，根据仓库中的固定版本和 Docker 说明运行兼容性 smoke 与正式评测。

## 3. 设计边界

### 3.1 本阶段包含

1. 官方合同级本地预检器。
2. 可选 Token、Bearer、X-Api-Key 鉴权，默认关闭。
3. Health、同步 Add、立即 Search、Top K、幂等和用户隔离验证。
4. 并发 Add/Search 容量预检。
5. GitHub Actions 自动执行静态检查、单元测试、镜像构建和容器预检。
6. 学术代码提交材料模板与完整 Docker/API 说明。

### 3.2 本阶段不包含

1. 不下载或重建平台私有评测数据。
2. 不生成最终答案或本地伪造官方评分。
3. 不创建或提交任何真实 Eval Key、Memory System Key。
4. 不启动正式 full 评测；第二评测周期开放后由用户提交申请。
5. 不把当前词法基线冻结为最终冲榜版本。

## 4. 组件设计

### 4.1 配置化鉴权

运行配置新增：

- `MEMORY_AUTH_SCHEME=none|token|bearer|x-api-key`
- `MEMORY_API_KEY=<secret>`

默认 `none` 保持当前本地和平台 Docker 运行兼容。启用鉴权时，仅保护 Add/Search 及其兼容别名；`GET /health` 始终无需鉴权。

密钥只从环境变量读取，使用常量时间比较，不写入日志、响应、测试快照或仓库。缺失或错误凭证返回 HTTP 401，错误正文采用官方文档建议的 `{"detail":{"reason":"..."}}` 形状。

### 4.2 官方合同预检器

新增 `scripts/eval_preflight.py`，只使用 Python 标准库并接受：

- `--base-url`
- `--timeout`
- `--auth-scheme`
- `--api-key-env`
- `--add-concurrency`
- `--search-concurrency`

预检器执行以下黑盒验证：

1. 无鉴权 Health 返回 2xx。
2. Add 返回 HTTP 200、`success=true`，并逐字回显三个 ID。
3. 同一 Add 重试保持幂等。
4. Add 成功后记忆可立即被 Search 找到。
5. Search 返回顶层 `data` 数组，每项包含非空 `id` 和 `content`。
6. 结果数量不超过 `top_k`，顺序和 ID 稳定。
7. 选择题 `options` 可以作为检索线索。
8. 其他 `user_id` 的标记内容不得泄漏。
9. 并发 Add/Search 无协议错误或丢失。

脚本只打印阶段名称、计数、耗时和脱敏错误，不输出 API Key 或完整评测内容。

### 4.3 CI 流水线

新增 `.github/workflows/ci.yml`：

1. Python 3.11 安装项目开发依赖。
2. 运行 Ruff、Mypy、Pytest 和 compileall。
3. 构建 Docker 镜像。
4. 启动临时容器并等待 Health。
5. 对容器运行官方合同预检器。
6. 无论成功失败都停止并删除测试容器。

CI 不保存评测数据库，不使用仓库 Secrets，也不运行官方 full 任务。

### 4.4 提交材料

新增 `evaluation/SUBMISSION.md`，包含：

- 系统、版本、赛道、组别和提交方式。
- GitHub 仓库与固定提交字段。
- Docker 构建/运行命令。
- Health、Add、Search 地址。
- 鉴权方式和容量配置。
- 原创性、方法来源和 AI 辅助开发披露。
- 尚需用户填写的联系人/团队字段。

README 增加评测接入、Preflight 和申请步骤，并明确当前结果是本地兼容性验证，不是官方成绩。

## 5. 安全与数据生命周期

- `.env`、密钥、SQLite 数据和评测日志保持在 `.gitignore` 中。
- Preflight 为每次运行生成唯一 `user_id` 和 `request_id`，避免与其他运行冲突。
- 容器 CI 使用临时可写层，任务结束后删除。
- 正式评测产生的数据应在任务完成后 30 天内删除，除非获得书面延长许可。
- Search 继续只返回记忆证据，不生成答案。

## 6. 验收标准

1. 现有无鉴权行为保持兼容。
2. 三种鉴权方式都有成功、缺失和错误凭证测试。
3. Health 在鉴权开启时仍可匿名访问。
4. Preflight 对合格服务退出 0，对合同破坏退出非 0。
5. 完整 Python 质量门禁通过。
6. Docker 镜像构建成功，容器 Preflight 通过。
7. GitHub Actions 提交后成功运行。
8. 提交文档不含密钥，未把本地验证描述为官方成绩。

## 7. 后续阶段

评测接入完成后，再单独推进语义向量、混合召回和 RRF。正式 full 配额稀缺，在取得本地回归基线并完成检索质量优化前，不提交最终 full 任务。
