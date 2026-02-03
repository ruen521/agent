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

### 请求处理流程

1. 前端发起请求，传入智能体类型、用户输入和会话 ID
2. 系统加载会话历史，保持对话上下文
3. 根据智能体类型路由到对应的处理节点
4. 调用工具层完成数据计算和分析
5. LLM 将计算结果转化为自然语言回复
6. 返回自然语言回复和结构化数据

### 核心设计理念

**确定性计算与智能解释分离**

- 工具层负责精确的数学计算、数据查询和规则判断
- LLM 负责理解用户意图、解释数据含义和生成行动建议
- 前端优先使用结构化数据渲染，确保展示稳定性

---

## 工具层设计

### 1. 库存查询工具（inventory_query_tool）

**查询类型**：全部商品、低库存、按品类、按 SKU、断货风险

**计算字段**：
- 预计断货天数（基于当前库存和销售速度）
- 紧急程度（CRITICAL < 3天，HIGH 3-5天，MEDIUM 5-7天，LOW > 7天）
- 缺货数量和风险金额
- 供应商联系信息

### 2. 补货计算工具（inventory_replenishment_tool）

**计算公式**：
```
补货数量 = (日销量 × 供应商交期) + (日销量 × 安全库存天数) - 当前库存
```

**功能**：
- 按供应商分组合并订单
- 校验最低起订金额
- 计算预计到货日期

### 3. 供应商信息工具（inventory_vendor_info_tool）

**提供数据**：供应商名称、联系方式、供货交期、最低起订金额、评分

### 4. 清仓折扣计算工具（inventory_markdown_calculator）

**折扣策略**：
- 45-60 天：10% off
- 60-90 天：20% off
- 90-180 天：30% off
- 180+ 天：50% off

**输出**：预计清仓天数、促销收入、节省仓储成本、净收益

### 5. 统计指标工具（stats_calculator）

**统计维度**：SKU 总数、低库存数量、断货风险数量、紧急风险数量、品类数量

---

## 五大智能体

### 1. 缺货哨兵（Stockout Sentinel）

**功能**：监控 1-7 天内的断货风险，按紧急程度排序

**输出**：SKU、断货天数、缺货数量、风险金额、供应商信息、行动建议

### 2. 补货规划师（Replenishment Planner）

**功能**：生成补货计划，按供应商分组订单

**输出**：供应商分组、商品清单、订单金额、最低起订校验、预计到货日期

### 3. 异常侦探（Exception Investigator）

**功能**：检测数据质量异常

**检查规则**：
- 补货点与销售速度不匹配
- 售价低于成本价
- 负毛利率
- 库存与销售速度不匹配

**输出**：异常类型、原因分析、修复建议

### 4. 清仓教练（Markdown & Clearance Coach）

**功能**：为滞销商品设计促销方案

**输出**：建议折扣、销售提速预测、清仓时间、收益分析

### 5. 库存助手（Inventory Copilot）

**功能**：多轮对话式库存分析

**特点**：
- 自动选择合适的工具
- 支持上下文追问
- 提供综合性建议

---

