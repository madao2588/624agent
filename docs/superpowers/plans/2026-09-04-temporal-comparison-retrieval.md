# 双时态证据检索实现计划

## 任务 1：锁定拆解边界

- 修改 `tests/test_retrieval.py`，先添加英中双时态、单时态不触发的失败测试。
- 验收：新测试失败，失败点是当前没有生成双时态组件。

## 任务 2：锁定会话内证据补全

- 在 `tests/test_retrieval.py` 添加旧状态、新状态、主题相似噪声和其他用户数据。
- 验收：现有混合检索无法把两条正确证据都放进前五。

## 任务 3：实现最小双时态路径

- 修改 `src/aml_memory/retrieval.py`：检测双时态、提取主题、搜索候选会话、按视角
  选择互不重复证据，并保留两个早期结果位置。
- 复用现有 session-scoped vector search、topic bridge 和安全过滤，不新增依赖。
- 验收：任务 1、2 的测试转绿，原年龄补全测试仍通过。

## 任务 4：真实样本和回归门禁

- 运行 LongMemEval `f685340e` 本地语义检索。
- 重跑冻结六类样本，与上一版汇总逐项比较。
- 验收：目标问题 Turn Recall-all@5 为 1；冻结样本 Recall/nDCG 不下降。

## 任务 5：文档、静态检查和交付

- 更新 `README.md` 与 `docs/longmemeval-s-results.md`。
- 运行 Ruff、Mypy、Pytest、compileall、secret scan、`git diff --check`。
- 运行 GitNexus `detect-changes`，精确暂存本阶段文件，按 Lore 协议提交并推送。
- 验收：本地检查和 GitHub CI 均通过，用户未跟踪文件保持不动。
