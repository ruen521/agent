# 跨境电商库存智能体平台

一个多智能体库存管理系统，覆盖缺货预警、补货规划、异常检测、清仓建议与对话式分析。后端基于 FastAPI + LangGraph + MySQL，前端基于 React + Vite。支持 MySQL 数据源（目前是虚拟数据）。

## 功能概览
- 五个智能体：缺货哨兵、补货规划、异常侦测、清仓教练、库存助手
- 工具层：库存查询、补货计算、供应商信息、清仓折扣、统计指标
- API：`/agents/list`、`/agents/invoke`、`/agents/stats`、`/health`、`/metrics`
- 前端：仪表盘、风险列表、聊天面板、SQL 字段明细表（分页/搜索/筛选）
- 可观测性：结构化日志、Prometheus 风格指标、健康检查脚本

## 技术栈
- 后端：FastAPI、LangGraph、SQLAlchemy、PyMySQL、httpx
- 前端：React 18、Vite、Axios、Recharts
- 数据源：MySQL 或 JSON Mock
- 模型：QingyunTop GPT-4o（兼容 OpenAI Chat Completions 接口）

## 目录结构
- `app/` 后端代码
- `frontend/` 前端代码
- `data/` Mock 数据
- `scripts/` 初始化与健康检查脚本
- `docs/` 说明文档

## 克隆后启动命令（命令行）

**后端：**
```bash
git clone https://github.com/ruen521/agent.git
cd <仓库目录>

# 创建并激活虚拟环境
python3 -m venv demo
source demo/bin/activate

# 安装依赖
pip install -r requirements.txt -r requirements-dev.txt

# 启动 API
uvicorn app.main:app --reload --port 8000
```

**前端：**
```bash
cd frontend
npm install
npm run dev
```

访问：`http://localhost:5173`

## 智能体工作原理
一次请求的处理流程如下：
1. 前端调用 `/agents/invoke`，传入 `agent`、`input`、`session_id`。
2. 后端进入 LangGraph 工作流，先加载会话历史。
3. 根据 `agent` 路由到对应节点执行工具调用与结构化渲染。
4. 将工具输出与系统提示词一起交给 LLM 生成自然语言回复。
5. 写入会话历史，返回 `response_text` + `structured_output` 给前端。

系统的关键目标是把“确定性计算”放在工具层，把“解释与行动建议”交给 LLM。

## LangGraph 工作流设计
核心节点：
1. `load_session` 读取 `session_id` 的历史消息。
2. `stockout_sentinel`、`replenishment_planner`、`exception_investigator`、`markdown_clearance_coach`、`inventory_copilot` 执行专属工具逻辑。
3. `finalize` 将问答写回内存，形成多轮对话上下文。

AgentState 关键字段：
1. `agent` 目标智能体 ID。
2. `input` 用户问题。
3. `session_id` 会话 ID。
4. `messages` 对话历史。
5. `tool_output` 工具原始结果。
6. `response_text` LLM 输出。
7. `structured_output` 结构化结果给前端渲染。
8. `forced_tool` 与 `forced_args` 支持强制工具调用。

## 工具层设计
所有智能体通过工具函数完成数据计算，避免 LLM 幻觉。

**inventory_query_tool**
1. 查询类型：`all`、`low_stock`、`by_category`、`by_sku`、`stockout_risk`。
2. 衍生字段：`days_until_stockout`、`urgency_level`、`shortage_amount`、`revenue_at_risk`、供应商联系方式。
3. 紧急度阈值：CRITICAL `<3` 天，HIGH `3-5` 天，MEDIUM `5-7` 天。

**inventory_replenishment_tool**
1. 公式：`(velocity * lead_time) + (velocity * safety_days) - current_stock`。
2. 按供应商合并，校验最小起订金额，输出 ETA 与预计到货日期。

**inventory_vendor_info_tool**
1. 按 `VendorID` 查询供应商联系方式、交期、最低起订金额、评分。

**inventory_markdown_calculator**
1. 分级策略：`45/60/90/180+` 天分别对应 `10%/20%/30%/50%`。
2. 输出 `days_to_clear`、`revenue_at_markdown`、`holding_cost_avoided`、`net_benefit`。

**stats_calculator**
1. 统计 SKU 总数、低库存、缺货风险、紧急风险与类目数量。

## 五大智能体设计

### 1. 缺货哨兵（Stockout Sentinel）
目标：1-7 天缺货风险预警，优先级排序，给出行动建议。
1. 工具：`inventory_query_tool(stockout_risk)`。
2. 关键输出：SKU、缺货天数、缺口、风险收入、紧急度、供应商联系方式、行动建议。


### 2. 补货规划（Replenishment Planner）
目标：自动生成补货计划，按供应商合并订单，满足最低起订。
1. 工具：`inventory_replenishment_tool(safety_days=14)`。
2. 关键输出：供应商分组、单品数量、订单金额、最低起订提示、预计到货日期。

### 3. 异常侦测（Exception Investigator）
目标：发现数据质量异常并给出修复建议。
1. 规则：补货点与速度不匹配、价格异常、负毛利、库存与速度不匹配。
2. 输出：异常类型、原因假设与修复动作。

### 4. 清仓教练（Markdown & Clearance Coach）
目标：对高库存低动销 SKU 给出折扣策略并估算收益。
1. 工具：`inventory_markdown_calculator`。
2. 输出：建议折扣、提速倍数、清仓天数、净收益与持有成本对比。

### 5. 库存助手（Inventory Copilot）
目标：多轮对话分析，全局库存问答。
1. 工具选择：根据问题语义自动调用查询、补货、供应商或清仓工具。
2. 输出：简洁结论 + 关键指标 + 后续建议。

## 前端与结构化输出
前端页面不直接依赖 LLM 自然语言，而以 `structured_output` 作为稳定展示来源：
1. 风险表读取 `risks` 列表。
2. 明细表读取 `inventory_query` 的 enrich 字段。
3. 统计卡片读取 `/agents/stats` 统计数据。

