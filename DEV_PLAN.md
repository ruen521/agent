# 开发计划：Multi-Agent AI Inventory Management System（SP-API + QingyunTop GPT-4o）
版本：v1.0｜日期：2026-02-03｜负责人：待定

## 1. 目标与范围
1. 交付与 README-2.md 等价的功能全量覆盖：五个智能体、工具层、/agents API、前端仪表盘与聊天、监控与运维、未来增强路线。
2. 大模型切换为 QingyunTop 接口，URL `https://api.qingyuntop.top`，密钥 `sk-***`（仅占位，不提交真实密钥），模型 `gpt-4o`；保留可替换接口的抽象层。
3. 初期数据使用本地/服务端模拟数据（对标 30 个 SKU、4 个供应商等），预留真实接入路径。
4. 接入亚马逊 Selling Partner API（SP-API）：先以桩实现接口契约，完成认证流程与字段映射，后续切换为真实调用。
5. 质量与运维要求：具备日志、指标、健康检查；具备安全基线（API 密钥或 LWA 授权）；满足 README-2.md 的性能与可靠性目标的等价版本（本地/云）。

## 2. 里程碑与输出
1. M0（0.5 周）：环境与依赖就绪（Python 3.11 + FastAPI 固定）；配置模板、密钥管理方案；Mock 数据集落地。
2. M1（1 周）：后端骨架完成（/agents/list、/agents/stats、/agents/invoke），工具层四个函数可返回模拟数据；健康检查接口。
3. M2（1 周）：五个智能体完成提示词、工具绑定、响应模板；集成 QingyunTop GPT-4o；多轮会话上下文内存。
4. M3（1 周）：SP-API 适配层（认证、签名、速率限制器、重试），以桩返回 Mock 数据；字段映射与错误处理完成。
5. M4（1 周）：前端 React 仪表盘与聊天界面实现，展示实时统计、风险列表、对话区；与后端联调。
6. M5（0.5 周）：可观测性与安全基线（结构化日志、指标、告警钩子、简单 API 鉴权/CORS）；性能与并发烟测。
7. M6（0.5 周）：端到端验收、文档完善、交付包与后续计划评审。

## 3. 架构落地方案（对齐 README-2）
1. 前端：React 18 + Axios；深色主题与图表；页面包含仪表盘、聊天、多智能体选择、风险列表、快捷操作按钮。
2. API 层：HTTP 服务提供 `GET /agents/list`、`POST /agents/invoke`、`GET /agents/stats`，形同 API Gateway；可选 `/health`。
3. 智能体编排：本地服务内的 Agent Orchestrator 替代 Bedrock；调用 QingyunTop GPT-4o；统一 Router 将智能体工具调用分发到工具函数。
4. 工具层：实现 `inventory-query-tool`、`inventory-replenishment-tool`、`inventory-vendor-info-tool`、`inventory-markdown-calculator`、`stats-calculator`；接口保持 README-2 的入参与出参格式。
5. 数据层：用 JSON/SQLite/内存集合模拟 DynamoDB 表 InventoryItems、Vendors、VendorCallLogs、ReplenishmentPlans；保留 CategoryIndex 等查询能力；提供种子数据加载脚本。
6. SP-API 适配：独立模块封装 LWA 获取 token、Signature V4 签名、节流；首期以桩返回模拟库存与订单数据，真实参数和限流策略预埋。
7. 可观测性：结构化日志、请求 ID、耗时、错误码；指标（成功率、P95 时延、令牌用量）；Tracing 挂钩（OpenTelemetry，可映射到 X-Ray）。
8. 部署形态：本地 Docker Compose 与云端等价蓝图（API 服务 + 前端静态资源 + 可观测性组件）；后续可迁移到 API Gateway + Lambda + DynamoDB + CloudWatch。

## 4. 工作分解
### 4.1 环境与配置
1. 固定后端运行时为 Python 3.11 + FastAPI；初始化依赖管理（uv/poetry 或 pip + requirements.txt）、lint/format（ruff/black）、测试（pytest）。
2. 配置文件 `.env` 样例：`QINGYUN_API_URL`、`QINGYUN_API_KEY`、`QINGYUN_MODEL=gpt-4o`、`SPAPI_REFRESH_TOKEN`、`LWA_CLIENT_ID`、`LWA_CLIENT_SECRET`、`AWS_SELLER_ID`、`AWS_ROLE_ARN`、`MOCK_MODE=true`。
3. 公共模块：请求 ID 中间件、错误处理中间件、速率限制器、超时控制；OpenAPI 文档开启；SP-API 沙箱配置参考 `沙箱环境完整配置指南.md` 与 `config.ini`，提供加载/验证脚本。

### 4.2 数据层与模拟数据
1. 定义与 README-2 对齐的表结构：InventoryItems（SKU、Name、Category、CurrentStock、ReorderPoint、DailySalesVelocity、UnitCost、VendorID、LeadTimeDays、LastUpdated）、Vendors（VendorID、Name、PhoneNumber、Email、LeadTimeDays、MinimumOrder、Rating）、VendorCallLogs、ReplenishmentPlans。
2. 种子数据：加载 30 个 SKU、9 类别、4 个供应商，字段与原文示例一致；提供脚本 `scripts/load-sample-data.sh` 或 Python Seeder。
3. 查询支持：按 SKU、按类别、low_stock、stockout_risk、全表扫描；计算 days_until_stockout、urgency_level、shortage_amount；可选 GSI 模拟（内存索引）。
4. 将 SP-API 数据字段映射表补充到 `docs/spapi-mapping.md`（catalogItems→InventoryItems，orders→SalesHistory 预留）。

### 4.3 后端 API（等价 API Gateway）
1. `GET /agents/list`：返回五个智能体元数据（id、name、description、status、friendly_name、updated）。
2. `POST /agents/invoke`：请求体包含 agent、input、session_id，可选 parameters；响应包含 success、response、session_id、timestamp、request_id；错误码 400/404/500 兼容 README-2。
3. `GET /agents/stats`：全表扫描统计 total_skus、stockout_risks、critical_risks、low_stock_items、total_categories、categories；返回耗时指标。
4. `GET /health`：依赖检查（模型可达、数据源可读、SP-API LWA token 可获取或 Mock 正常）。
5. CORS、速率限制、API Key 或 Bearer Token 简易鉴权；日志记录 request_id、agent、latency、status。

### 4.4 工具函数实现（对应四个 Lambda + 统计）
1. inventory-query-tool：支持 all、low_stock、by_category、by_sku、stockout_risk；输出 enriched 字段 days_until_stockout、urgency_level、shortage_amount、vendor_name；性能目标 <250ms 本地。
2. inventory-replenishment-tool：按 `(velocity * lead_time) + (velocity * safety_days) - current_stock` 计算建议量；按 vendor 分组，校验最小起订量，返回 total_cost 与 ETA；输出 ReplenishmentPlans 写入模拟表。
3. inventory-vendor-info-tool：按 VendorID 查询，返回联系方式、LeadTimeDays、MinimumOrder、Rating；支持全量列表。
4. inventory-markdown-calculator：按 days_of_supply 计算 10%/20%/30%/50% 分级，给出 expected_velocity_multiplier、days_to_clear、revenue_at_markdown、net_benefit。
5. stats-calculator：提取公共统计逻辑，供 /agents/stats 使用；便于将来迁移到独立 Lambda。

### 4.5 智能体定义（5 个，全量覆盖能力与输出结构）
1. Stockout Sentinel：绑定 inventory-query-tool（stockout_risk）与 inventory-vendor-info-tool；提示词包含紧迫度阈值、行动建议模板；输出包含 days、shortage、revenue_at_risk、urgency、actions。
2. Replenishment Planner：绑定 inventory-query-tool（low_stock）和 inventory-replenishment-tool、inventory-vendor-info-tool；覆盖供应商合并、成本拆分、ETA、最低起订校验、预算提示。
3. Exception Investigator：使用 inventory-query-tool 全表；内置统计检测 velocity-reorder mismatch、价格异常、库存异常；生成根因假设与修复建议。
4. Markdown & Clearance Coach：使用 inventory-markdown-calculator；输出按分级策略的折扣、预期提速、清仓时间线、收益与持有成本对比。
5. Inventory Copilot：可调用全部工具；支持多轮上下文、教学模式、跨来源综合；提供概览、对比、解释型回答。
6. 对话管理：session_id 关联上下文存储；防止幻觉的工具优先策略；错误降级文案。

### 4.6 SP-API 接入计划（先桩后真）
1. 认证与安全：实现 LWA 获取 access_token，签名 V4；配置 refresh_token 等敏感值从环境读取；在 MOCK_MODE=true 时短路为桩响应。
2. 数据域选择：首期拉取 Catalog Items、Listings、Inventory、Orders；映射库存数、补货点、供应商/ASIN 关系；将订单销售记录写入 SalesHistory 预留表，为未来 Forecast 与盈利分析做准备。
3. 速率与重试：实现令牌桶限流、指数退避重试；记录 API 用量指标。
4. 同步策略：定时任务拉取增量（近 24h），并行度与分页控制；失败队列与补偿机制。
5. 合规：日志脱敏（买家信息）；参数校验与错误分类（429、503、签名失败）。

### 4.7 前端（React 仪表盘 + Chat）
1. 页面：顶部统计卡片（total_skus、stockout_risks、critical_risks、low_stock_items、categories）；风险列表表格；聊天区域；智能体切换；快捷查询按钮；错误与空状态。
2. API 对接：统一 axios 客户端，包含 request_id header；处理 loading、重试、节流；在 MOCK_MODE 下展示模拟数据。
3. 交互：聊天支持 Markdown 渲染、代码块、响应延迟提示；表格支持排序与过滤；链接到供应商联系方式。
4. 性能：首屏 <1.5s，接口缓存 30s 可选；资源体积控制在 1MB 级别。
5. 可测试性：组件测试（React Testing Library），端到端场景（Playwright/Cypress）。

### 4.8 可观测性与运维
1. 日志：结构化 JSON，字段包含 timestamp、level、request_id、agent、tool、latency_ms、status、error_code；本地输出到 stdout，云端可对接 CloudWatch/OpenSearch。
2. 指标：成功率、P95/P99 延迟、Bedrock 替换后的模型 token 用量、SP-API 命中率/限流次数；暴露 `/metrics`（Prometheus/OpenTelemetry）。
3. Tracing：OpenTelemetry trace id 贯穿前后端；在云端映射到 X-Ray；对工具调用链做 span。
4. 告警：错误率阈值、接口超时、SP-API 429 次数；本地用日志提示，云端接 SNS/Email 升级。
5. 健康检查脚本：对标 README-2 的 `health-check.sh`，增加模型可达性与 SP-API token 检查；提供 macOS 与 Linux 版本，记录在 MONITORING.md。

### 4.9 安全与合规
1. API 访问控制：API Key 或 Bearer Token；限制跨域来源列表；限制请求大小与频率。
2. 密钥管理：环境变量 + 本地 .env.example；禁止硬编码密钥；未来迁移到 Secrets Manager/KMS。
3. 数据保护：HTTPS 部署；日志脱敏；模拟数据不包含真实个人信息。
4. 权限模型：为未来云上部署预留最小权限策略（等价 InventorySystemLambdaRole、BedrockAgentExecutionRole）。

### 4.10 测试与质量
1. 单元测试：工具函数的计算正确性（stockout 计算、replenishment、markdown 分级、异常检测）。
2. 合约测试：/agents API 输入输出契约；SP-API 桩接口返回格式；前端 API Mock。
3. 集成测试：端到端调用智能体 → 工具 → 数据层；多轮会话；错误路径（超时、无数据）。
4. 性能与负载：模拟 README-2 的压测场景（100 并发、1k 顺序、Burst 50），记录时延与错误率；调优线程池/连接池。
5. 跨平台脚本验证：macOS 与 Linux 监控脚本各自通过；记录差异。

### 4.11 部署与交付
1. 本地：Docker Compose（api、frontend、mock-db、otel-collector 可选）；一键 `make up`；`make seed` 加载样例数据。
2. 云蓝图：API Gateway + Lambda + DynamoDB + S3 + CloudWatch/X-Ray 的 IaC 草案；前端 S3/CloudFront；为 SP-API 预置 VPC 出口策略。
3. CI/CD：lint/test/build；可选 GitHub Actions；环境区分 dev/stage/prod；自动注入版本号与构建时间。
4. 文档：更新 README、API 文档、运维手册、SP-API 配置指南、QingyunTop 接口说明。

### 4.12 风险与缓解
1. SP-API 限流与配额：采用令牌桶 + 指数退避；提前监控 429；必要时降级到本地缓存。
2. 大模型调用成本与稳定性：增加请求重试与超时；缓存相同问题的短期答案；可切换模型接口。
3. Mock 与真实数据差异：定义契约与映射表，确保切换只需替换数据源；在测试用例中覆盖两种模式。
4. 多平台脚本差异：保留 macOS 与 Linux 双版本；在 CI 中运行两套脚本的 dry run。

### 4.13 验收标准
1. 功能覆盖：README-2 所列五智能体、四工具、三主 API、前端展示、统计与监控均可运行并产生期望输出。
2. 模拟数据：30 SKU、4 供应商、9 类别、统计口径与示例相符；stockout_risk、replenishment、markdown 计算匹配示例。
3. SP-API：认证流程可跑通或在 MOCK_MODE 下正常桩返回；字段映射文档齐全；实际调用入口可配置启用。
4. 性能：本地单次 /agents/invoke P95 < 12s，/agents/stats < 500ms，前端首屏 < 1.5s。
5. 可观测性：日志包含 request_id；指标可导出；health-check 脚本通过。
6. 安全：API 有最小限度鉴权；密钥不落盘；CORS 配置合理。

### 4.14 未来增强路线（对应 README-2 Phase 2-5）
1. Phase 2 Q2 2026：Demand Forecasting Agent（AWS Forecast/自研）、SalesHistory 表、inventory-forecast-tool；Multi-Location 支持（Locations 表、inventory-transfer-tool）；Supplier Performance（VendorPerformance 表、vendor-performance-tool）。
2. Phase 3 Q3 2026：自动采购单生成（PurchaseOrders 表、create-purchase-order、SES/Step Functions）；语音集成与通话记录（Twilio/Connect、VendorCallLogs 入库、Transcribe/Comprehend 预留）；电商多平台同步（Shopify/WooCommerce/Amazon/eBay webhook、EventBridge 模拟）。
3. Phase 4 Q4 2026：Profitability Analysis Agent（profitability-calculator、SellingPrice/FulfillmentCost 字段）；Customer Segmentation（CustomerPurchases 表、customer-segmentation-tool、Personalize 预留）；Environmental Impact Tracking（CarbonFootprintPerUnit、carbon-calculator）。
4. Phase 5 2027：多租户（TenantID 方案、Cognito 与 API Key 配额）、移动端 React Native、QuickSight 报表与定时报表。

## 5. 依赖与资源
1. 账号与密钥：QingyunTop API Key、SP-API 凭证（LWA、refresh_token、seller_id、role_arn）。
2. 工具链：Python 3.11、Node 18、Docker、Make、GitHub Actions（可选）。
3. 测试数据：README-2 示例 SKU/Vendor JSON；可从 `fbaInventory.json`、`config.ini` 等本仓库文件补足。

## 6. 覆盖性自检（对应 README-2.md）
1. 五智能体：Stockout Sentinel、Replenishment Planner、Exception Investigator、Markdown Coach、Inventory Copilot —— 均已在计划中定义能力、工具绑定、输出结构与示例格式。
2. 工具层：inventory-query/replenishment/vendor-info/markdown + stats-calculator —— 入参、出参、性能目标、数据 enrichment 与最小起订校验均覆盖。
3. API 层：/agents/list、/agents/invoke、/agents/stats、/health —— 与 README-2 定义一致，含错误码、CORS、鉴权。
4. 数据层：InventoryItems、Vendors、VendorCallLogs、ReplenishmentPlans（Mock 数据 30 SKU/4 Vendor/9 类别）、GSI 类查询能力、统计口径；预留 SalesHistory 等未来表。
5. 前端：仪表盘统计、风险列表、聊天与智能体切换、可视化指标、错误/空状态；性能目标与缓存策略。
6. 运维：日志、指标、Tracing、健康检查脚本、告警阈值；macOS/Linux 双脚本策略；成本/性能对标 README-2 的目标。
7. 安全与权限：最小鉴权、密钥管理、CORS、速率限制；云上最小权限角色蓝图（对应 InventorySystemLambdaRole、BedrockAgentExecutionRole）。
8. 未来增强：Phase 2-5 的九项增强（需求预测、多仓、供应商表现、自动 PO、语音、全渠道、盈利分析、客户分群、碳排追踪、多租户、移动端、BI）均映射并列出。

## 7. 下一步行动（启动前）
1. 后端语言已定：FastAPI（Python 3.11）。
2. SP-API：优先按 `沙箱环境完整配置指南.md` 与 `config.ini` 沙箱凭证跑通；缺失项由用户补充（refresh_token、role_arn 等），默认 MOCK_MODE=true。
3. 部署形态：本迭代保持本地/容器形态，不上云；预留 IaC 蓝图。
4. 认领负责人与时间表，启动 M0 任务。
