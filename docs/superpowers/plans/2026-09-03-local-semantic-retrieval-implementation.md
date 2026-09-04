# 本地语义检索实现计划

> 设计依据：`docs/superpowers/specs/2026-09-03-local-semantic-retrieval-design.md`

## 1. 先锁定适配器契约

- 在 `tests/test_embeddings.py` 添加 FastEmbed 假实现测试。
- 覆盖惰性初始化、批量向量转换、维度校验和脱敏错误。
- 先运行测试并确认因实现缺失而失败。

## 2. 锁定连接 API 契约

- 为 `local` provider 增加无 Key 创建测试。
- 覆盖固定模型、禁止自定义 Base URL、禁止携带 Key，以及外部 provider 仍要求 Key。
- 先运行测试并确认 schema/路由尚不支持。

## 3. 实现本地 Embedder

- 在 `src/aml_memory/embeddings.py` 增加惰性 FastEmbed 适配器和本地模型常量。
- 让临时本地连接共享一个进程内模型实例，并串行保护共享后端推理。
- FastEmbed 通过动态导入保持可选依赖。
- 在 `pyproject.toml` 增加 `local` extra，容器安装该 extra。

## 4. 接入连接和检索链路

- 扩展 connection schema 和 provider 类型。
- 本地连接走 `FastEmbedEmbedder`，外部连接保持原逻辑。
- 沿用 `EmbeddingSpaceEmbedder` 形成稳定的向量空间标识。

## 5. 完成演示页交互

- 新增“本地语义 · 免费”选项。
- 隐藏 Key、Base URL 和记住 Key 控件。
- 展示首次下载、隐私范围和本地连接状态。
- 增加静态页面测试，防止后续退化为外部 Key 流程。

## 6. 验证真实模型和回归

- 安装 `.[dev,local]`。
- 用合成中英文样例完成真实模型与 API 冒烟测试。
- 运行定向测试、全量测试、Ruff、Mypy、编译和密钥扫描。

## 7. 基准门禁与下一阶段

- 在 LongMemEval 小样本上对照 lexical 与 local hybrid。
- 若召回不退化且耗时可接受，再实现 session→turn 分层召回；否则保留本地能力为可选项并先优化批处理/缓存。
- 提交前运行 GitNexus `detect-changes`，只暂存本轮明确文件。
