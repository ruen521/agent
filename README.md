# 跨境电商库存智能体平台

一个多智能体库存管理系统，覆盖缺货预警、补货规划、异常检测、清仓建议与对话式分析。后端基于 FastAPI + LangGraph + MySQL，前端基于 React + Vite。支持纯 Mock 数据与 MySQL 数据源切换。

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
git clone <你的仓库地址>
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

## 快速启动

### 前置依赖

**系统依赖：**
- Python 3.11+
- Node.js 18+
- MySQL 8.0+

**安装系统依赖（macOS）：**
```bash
# 使用 Homebrew
brew install python@3.11 node mysql
brew services start mysql
```

**安装系统依赖（Ubuntu/Debian）：**
```bash
sudo apt update
sudo apt install python3.11 python3-pip nodejs npm mysql-server
sudo systemctl start mysql
```

### 1. 安装 Python 依赖
```bash
# 进入项目根目录
cd /Users/zhaosibo/mycode/demo

# 安装后端依赖
pip install -r requirements.txt

# 安装开发依赖（可选）
pip install -r requirements-dev.txt
```

**requirements.txt 包含：**
- fastapi==0.115.8 - Web 框架
- uvicorn[standard]==0.30.6 - ASGI 服务器
- langgraph==0.2.38 - AI Agent 编排
- SQLAlchemy==2.0.30 - ORM 数据库
- PyMySQL==1.1.1 - MySQL 驱动
- pydantic==2.10.6 - 数据验证
- pydantic-settings==2.7.1 - 配置管理
- python-dotenv==1.0.1 - 环境变量加载
- httpx==0.27.2 - HTTP 客户端
-- cryptography==44.0.0 - 加密库
### 2. 安装前端依赖
```bash
cd frontend
npm install
```

**package.json 包含：**
- react@18.3.1 - UI 框架
- react-dom@18.3.1 - React DOM
- vite@5.4.3 - 构建工具
- axios@1.7.7 - HTTP 客户端
-- recharts@3.7.0 - 图表库
### 3. 启动后端
```bash
# 返回项目根目录
cd /Users/zhaosibo/mycode/demo

# 启动 API 服务
uvicorn app.main:app --reload --port 8000
```

### 4. 启动前端
```bash
cd frontend
npm run dev
```

访问：`http://localhost:5173` 或 `http://localhost:5174`


## 环境配置

### 后端 `.env`
项目根目录已有 `.env`，最小配置示例：
```env
QINGYUN_API_URL=https://api.qingyuntop.top
QINGYUN_API_KEY=
QINGYUN_MODEL=gpt-4o

API_KEY=
ALLOWED_ORIGINS=http://localhost:5173

DATABASE_URL=mysql+pymysql://root:123456@localhost:3306/inventory_ai?charset=utf8mb4
DB_STRICT=false

ALERT_ERROR_RATE=0.2
ALERT_MIN_REQUESTS=50
```

说明：
- `DATABASE_URL` 配置后优先走 MySQL。
- `DB_STRICT=false` 时数据库不可用会自动降级为 Mock 数据。
 - 未配置 `QINGYUN_API_KEY` 时调用 `/agents/invoke` 会返回 502 错误。

### 前端 `.env`（可选）
```env
VITE_API_BASE_URL=http://localhost:8000
VITE_API_KEY=
```

## MySQL 初始化与灌数

创建数据库：
```sql
CREATE DATABASE inventory_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

初始化表结构：
```bash
source demo/bin/activate
python scripts/init_mysql.py
```

生成大量模拟数据：
```bash
source demo/bin/activate
python scripts/generate_mock_data.py --items 5000 --vendors 20
```

## 关键接口
- `GET /agents/list` 获取智能体列表
- `POST /agents/invoke` 调用智能体
- `GET /agents/stats` 获取统计指标
- `GET /health` 健康检查
- `GET /metrics` 指标输出

示例：
```bash
curl http://localhost:8000/agents/stats
```

## 健康检查与监控

macOS：
```bash
API_KEY=your_key scripts/health_check_mac.sh http://localhost:8000
```

Linux：
```bash
API_KEY=your_key scripts/health_check_linux.sh http://localhost:8000
```

性能烟测：
```bash
python scripts/perf_smoke.py --base-url http://localhost:8000 --concurrency 50 --total 200
```

## 测试
```bash
source demo/bin/activate
pytest -q
```



---

## 版权与许可
MIT License
