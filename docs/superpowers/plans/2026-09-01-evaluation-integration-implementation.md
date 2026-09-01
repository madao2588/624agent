# Agent Memory Leaderboard 评测接入实施计划

> 对应设计：`docs/superpowers/specs/2026-09-01-evaluation-integration-design.md`

目标：把 `624agent` 准备为“学术方法 · 代码提交”候选版本，使平台维护者可以从 GitHub 构建 Docker、启动服务，并通过官方同步 Add/Search 合同预检。

## 步骤 1：锁定鉴权行为

涉及文件：

- 新增 `tests/test_auth.py`
- 修改 `src/aml_memory/config.py`
- 新增 `src/aml_memory/auth.py`
- 修改 `src/aml_memory/app.py`

执行：

1. 先写失败测试：默认无鉴权保持兼容；Token、Bearer、X-Api-Key 正确凭证成功；缺失或错误凭证返回 401；Health 始终匿名成功；响应与日志不得包含密钥。
2. 给 `Settings` 增加 `auth_scheme` 和 `api_key`，验证合法组合。
3. 实现常量时间凭证比较和统一 401 错误结构。
4. 只把鉴权依赖应用到 Add/Search 及兼容别名。
5. 运行 `pytest -q tests/test_auth.py tests/test_health.py tests/test_api_add_search.py`。

验收：新增测试由红转绿，现有无鉴权接口行为不变。

## 步骤 2：实现可复用的合同预检核心

涉及文件：

- 新增 `src/aml_memory/preflight.py`
- 新增 `tests/test_preflight.py`

执行：

1. 先写失败测试覆盖响应校验、Top K、Add ID 回显、Search 必填字段、认证头生成和错误脱敏。
2. 定义不可变配置、结构化检查结果和专用 `PreflightError`。
3. 使用 `urllib.request` 实现带超时的 JSON HTTP 客户端。
4. 实现 Health、同步 Add、幂等、立即检索、options、Top K、稳定排序和用户隔离检查。
5. 用 `ThreadPoolExecutor` 实现配置化并发 Add/Search 检查。
6. 确保失败输出只含阶段、HTTP 状态和脱敏原因。
7. 运行 `pytest -q tests/test_preflight.py`。

验收：合格响应通过；缺字段、越过 Top K、ID 不匹配和跨用户泄漏都被准确拒绝。

## 步骤 3：提供命令行入口

涉及文件：

- 新增 `scripts/eval_preflight.py`
- 修改 `pyproject.toml`
- 修改 `.dockerignore`

执行：

1. 编写薄 CLI，支持 base URL、三条路径、超时、鉴权方案、密钥环境变量名和并发参数。
2. 禁止通过命令行值直接传密钥，只允许从指定环境变量读取。
3. 成功时输出逐阶段摘要并退出 0；失败时输出脱敏错误并退出 1。
4. 增加可安装命令 `aml-eval-preflight`。
5. 保证脚本包含在 Docker 构建上下文之外也可从宿主机运行。

验收：`python scripts/eval_preflight.py --help` 和 `aml-eval-preflight --help` 均成功。

## 步骤 4：补齐提交材料和运行文档

涉及文件：

- 新增 `evaluation/SUBMISSION.md`
- 修改 `README.md`
- 修改 `.gitignore`

执行：

1. 填写仓库、路线、Docker、API、容量、鉴权、原创性与 AI 辅助说明。
2. 联系人和团队等未知信息使用明确的 `TODO(before submission)`，不猜测用户身份。
3. README 增加评测状态、Preflight 用法、鉴权配置和正式申请步骤。
4. 明确“本地预检通过不等于官方评测成绩”。
5. 确认 `.env`、数据库、日志、评测临时文件和密钥不会被提交。

验收：新维护者仅阅读 README 和提交材料即可构建、启动并验证服务。

## 步骤 5：增加 GitHub Actions

涉及文件：

- 新增 `.github/workflows/ci.yml`

执行：

1. 使用官方 GitHub Actions 当前稳定主版本。
2. Python 3.11 job 运行 Ruff、Mypy、Pytest、compileall。
3. Docker job 构建镜像、启动临时容器、等待 Health、运行完整 Preflight。
4. 使用 `if: always()` 清理容器；不配置或读取 Secrets。
5. 本地检查 YAML 内容、路径、命令和 shell 语法。

验收：推送后 GitHub Actions 两个 job 均成功。

## 步骤 6：完整本地验证

执行命令：

1. `.venv\\Scripts\\ruff.exe check .`
2. `.venv\\Scripts\\mypy.exe src`
3. `.venv\\Scripts\\pytest.exe -q`
4. `.venv\\Scripts\\python.exe -m compileall -q src tests scripts`
5. `docker build --pull=false -t aml-memory-eval:local .`
6. 启动临时容器并等待 healthy。
7. `.venv\\Scripts\\python.exe scripts\\eval_preflight.py --base-url http://127.0.0.1:18080`
8. 停止并删除临时容器。

验收：所有命令退出 0；容器无残留；日志不包含密钥或完整测试内容。

## 步骤 7：审查、提交和远端验证

执行：

1. 检查 `git diff --check`、敏感文件名和凭证模式。
2. 只暂存本计划涉及的明确文件。
3. 使用 Lore Commit Protocol 创建提交。
4. 推送 `main`。
5. 验证本地 HEAD 与 `origin/main` 一致。
6. 等待 GitHub Actions 完成并读取失败详情；若失败则修正后重新验证。

验收：远端仓库包含完整接入材料，工作树干净，GitHub Actions 成功。

## 已知外部阻塞

- 第一评测周期已经关闭，第二周期预计 2026-09-20 开放。
- 官方 smoke/full 只能在提交申请并由平台审核后运行。
- 本计划能完成代码和合同接入，但不能提前生成官方 Job ID 或分数。
