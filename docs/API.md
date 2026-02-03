# API Reference (M1)

Base URL: `http://localhost:8000`

Authentication:
- `X-API-Key: <API_KEY>` or `Authorization: Bearer <API_KEY>` if `API_KEY` is set.

## GET /agents/list
Returns the list of available agents.

Response:
- `agents`: array of agent metadata.

## GET /agents/stats
Returns real-time inventory statistics.

Response:
- `total_skus`
- `stockout_risks`
- `critical_risks`
- `low_stock_items`
- `total_categories`
- `categories`
- `request_id`
- `timestamp`

## POST /agents/invoke
Invoke a specific agent.

Request body:
- `agent`: agent id
- `input`: user prompt
- `session_id`: optional
- `parameters`: optional tool call

Tool call format:
```json
{
  "tool": "inventory_query",
  "args": {"query_type": "stockout_risk"}
}
```

Response:
- `success`
- `response.text`
- `response.reasoning`
- `response.structured_output`
- `response.tool_output`
- `session_id`
- `timestamp`
- `request_id`
- `model`

## GET /health
Health check.

Response:
- `status`
- `data_loaded`
- `timestamp`
