# API Reference

Base URL: `http://localhost:8000`

Authentication:
- `X-API-Key: <API_KEY>`
- or `Authorization: Bearer <API_KEY>` (if enabled)

## GET /agents/list
返回可用智能体列表与生命周期状态。

## GET /agents/stats
返回库存统计指标。

## POST /agents/invoke
同步调用智能体。

Request body:
- `agent`: 智能体 ID（支持别名）
- `input`: 用户输入
- `session_id`: 可选
- `parameters`: 可选

`inventory_copilot` 协同参数示例：

```json
{
  "mode": "team",
  "orchestration": {
    "member_allowlist": ["stockout_sentinel"],
    "member_denylist": ["markdown_clearance_coach"]
  }
}
```

说明：
- `mode` 支持 `planner` 与 `team`。
- 输入 `mode=team_v2` 仍被接受，但会映射到 `team`。
- `mode=team` 仅走 Team V1。

Response（核心字段）：
- `response.text`
- `response.reasoning`
- `response.structured_output`
- `response.tool_output`
- `collab_mode`

Team V1 `structured_output`：
- `team_version`: `v1`
- `status`: `team_v1_completed | team_v1_partial | team_v1_failed`
- `team_plan`
- `team_execution`
- `team_summary`
- `rag_summary`

Team V1 `tool_output`：
- `workflow_results`
- `member_tool_outputs`
- `rag_corpus`
- `rag_retrieval_trace`

## POST /agents/invoke_stream
流式调用智能体（SSE）。

Team V1 关键节点事件：
- `copilot_team_v1_plan`
- `copilot_team_v1_execute`
- `copilot_team_v1_aggregate`

## POST /reports/exports
创建异步导出任务（`pdf` / `xlsx`）。

`analysis` 导出在 Team V1 下会包含全量协同数据（含 RAG 证据与检索轨迹）。

## GET /reports/exports/{job_id}
查询导出任务状态。

## GET /reports/exports/{job_id}/download
下载导出文件。

## GET /health
服务健康检查。

## GET /metrics
Prometheus 文本指标。
