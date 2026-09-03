# LongMemEval-S 本地证据检索结果

评测日期：2026-09-03

## 先看结论

这次不是拿 20 条自建题反复跑到满分，而是把公开的
[LongMemEval](https://github.com/xiaowu0162/LongMemEval) 数据适配进真实
`MemoryStore -> LexicalRetrievalPipeline -> MemoryService` 检索链路，并跑完
LongMemEval-S 的 500 条记录。

470 条有答案位置标注的问题全部参与检索指标；30 条 abstention 没有证据
位置，按检索口径跳过。最能说明现状的两组数字是：

- Session Recall-any@5：**84.04%**。多数问题能把至少一个正确会话找进前五。
- Turn Recall-all@5：**42.13%**。前五条消息的证据完整率比上一版提高 7.66 个
  百分点，但跨会话找全仍明显不足。

本轮修复了一个检索意图错误：`previous chat/conversation/discussion/game`
原本会被当成“最早历史状态”，使大量 assistant 问题跳过相关性排序、强制按
时间升序。现在它们被视为对话来源说明；只有 `original`、`earliest`、`history`
等明确措辞才触发历史状态排序。全量对比中 39 道题的 Session nDCG@5 提升、
36 道题的 Turn nDCG@5 提升，没有题目的 Recall 或 nDCG 下降。

系统已经具备更可靠的长对话候选定位基础，但还没有达到强语义、多证据聚合的
水平。下一步应集中补 preference 和跨会话证据组合。

## 全量结果

| 粒度 | K | Recall any | Recall all | nDCG |
| --- | ---: | ---: | ---: | ---: |
| session | 1 | 69.57% | 28.30% | 69.57% |
| session | 5 | 84.04% | 66.60% | 72.18% |
| session | 10 | 90.43% | 75.74% | 74.95% |
| turn | 1 | 42.98% | 19.57% | 42.98% |
| turn | 5 | 64.47% | 42.13% | 47.36% |
| turn | 10 | 72.77% | 51.49% | 50.44% |

`Recall any` 表示至少找到一个标注来源；`Recall all` 要求找齐全部标注来源。
Session 排名按每个会话的首条命中去重；Turn 排名使用数据中的 `has_answer`
标注。Recall 和 nDCG 公式沿用 LongMemEval 上游脚本；Session 排名采用本服务
协议中更明确的“每个 session 只保留首次命中”。

来源角色口径与上游旧检索示例有一个重要差异：本服务按 Add 合同索引 user 和
assistant 两类消息。清洗版数据的 470 个计分题中，有 51 题的金标只落在 assistant
turn；上游旧脚本只索引 user turn，并把这些没有 user 金标的题排除。因此这里的指标
公式沿用上游，但候选语料是本服务的双角色证据协议，不能与旧脚本的 user-only BM25
数字直接横向比较。

## 六类问题的差异

| 问题类型 | Session any@5 | Session all@5 | Turn any@5 | Turn all@5 | Turn nDCG@5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| single-session-user | 90.62% | 90.62% | 79.69% | 79.69% | 76.00% |
| single-session-assistant | 98.21% | 98.21% | 89.29% | 89.29% | 86.29% |
| single-session-preference | 63.33% | 63.33% | 33.33% | 23.33% | 24.44% |
| temporal-reasoning | 76.38% | 51.18% | 54.33% | 30.71% | 37.03% |
| knowledge-update | 80.56% | 63.89% | 62.50% | 38.89% | 41.48% |
| multi-session | 89.26% | 57.85% | 64.46% | 19.01% | 34.22% |

单会话 user 与 assistant 事实现在都较稳定。最弱的是偏好归纳，以及需要从多个
会话找齐证据的问题；multi-session 的 Session any@5 已经很高，但 Turn all@5
仍只有 19.01%，说明主要瓶颈已经从“找到话题”转向“找齐来源”。

## 本次到底测了什么

本次默认使用 `benchmark-lexical` 写入模式：

1. 保留官方原始消息、角色、session id、时间和 turn id；
2. 将 user 和 assistant 原始消息都写入项目现有 SQLite/FTS5 索引；
3. 用项目现有 BM25/CJK 词法检索管线搜索；
4. 将返回的内部 message id 映射回官方 session/turn 标注；
5. 输出逐题 JSONL、汇总 JSON 和 Markdown 报告。

每题按排行榜服务合同请求 `top_k=100`，再从同一条有序结果中计算 @1、@5 和
@10。不能只请求 10 条来测 @10：当前管线会随 `top_k` 扩大候选池，较小请求的
高分不代表 100 条合同深度下的真实排序。

这个模式只隔离测量基础证据检索，不构建项目的 facet、状态链和关系图。完整 Add
路径仍可用 `--ingestion-mode full` 在小范围问题上运行，但不适合把 500 份彼此隔离
的长历史逐份做生产级富化。

本次也**没有**：

- 调用答案生成模型；
- 运行 LongMemEval 的 reader；
- 运行 LLM judge；
- 计算官方榜单总分；
- 把私有评测结果伪装成本地结果。

因此，这是一份可复现的公开数据“证据检索体检”，不是官方排行榜成绩。

## 数据与复现

数据来自 Hugging Face 上的
[`xiaowu0162/longmemeval-cleaned`](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)：

- 文件：`longmemeval_s_cleaned.json`
- 大小：277,383,467 bytes
- SHA-256：`d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`
- 总记录：500
- 有证据位置标注：470
- Abstention：30

完整命令：

```powershell
.\.venv\Scripts\python.exe scripts\run_longmemeval.py `
  --data artifacts\longmemeval\data\longmemeval_s_cleaned.json `
  --output-dir artifacts\longmemeval\conversation-reference-full-500 `
  --cutoffs 1,5,10
```

输出目录包含：

- `retrieval.jsonl`：每题的问题、金标位置、检索位置、原始证据和逐题指标；
- `summary.json`：配置、数据哈希、总指标、六类分项和延迟；
- `report.md`：人类可读总表。

最终复跑的纯搜索阶段平均延迟为 138.62 ms，P95 为 320.96 ms。它不包含数据
下载和每题数据库写入时间，因此只用于同一实现的本地回归比较。

## 接下来优先改什么

1. 为 preference 和同义表达增加真正的语义候选通道；
2. 对 multi-session、temporal 和 knowledge-update 增加受约束的多证据聚合；
3. 用这 470 条逐题结果建立失败切片，避免优化一种问题却破坏另一种；
4. 最后再接统一 reader/judge，单独测答案正确性和 abstention，不与检索指标混算。
