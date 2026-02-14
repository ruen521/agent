# Team V1 协作机制说明

## 目标

在跨境电商场景落地一套可演示、可追溯、低耦合的多成员协作流程，采用“法律示例风格”的串行协同。

## 主流程（LangGraph）

`load_session -> copilot_team_v1_plan -> copilot_team_v1_execute_loop -> copilot_team_v1_aggregate -> finalize`

- `inventory_copilot` 在 `collab_mode=team` 下只进入 Team V1。
- 输入 `mode=team_v2` 会被兼容映射到 `team`。

## 成员与顺序

固定 4 个成员，默认执行顺序：
1. `exception_investigator`
2. `stockout_sentinel`
3. `replenishment_planner`
4. `markdown_clearance_coach`

每个成员仅允许输出自身职责域结论，禁止复写全量巡检模板。

## 本地 RAG 机制

- 每次成员工具调用会写入本地证据库：`data/team_v1_runs/<run_id>/evidence_index.jsonl`
- 证据字段：
  - `evidence_id`
  - `run_id`
  - `member_id`
  - `tool_name`
  - `title_cn`
  - `content_text_cn`
  - `raw_json`
  - `created_at`
- 成员执行前固定检索（轻量词项打分，`top_k=8`），检索结果注入成员提示词。

## 聚合原则

综合结论仅使用：
- `team_execution`（成员结构化输出）
- `rag_corpus`（证据）
- `rag_retrieval_trace`（检索轨迹）
- 成员原始结论

输出状态：
- `team_v1_completed`
- `team_v1_partial`
- `team_v1_failed`

## 导出要求

Excel（analysis）固定输出中文工作表：
- `报告概览`
- `成员执行总览`
- `成员原始结论`
- `成员工具输出总表`
- `RAG证据库`
- `RAG检索轨迹`
- `异常明细`
- `缺货明细`
- `补货明细`
- `清仓明细`

PDF 允许 TopN；Excel 保持本轮全量。
