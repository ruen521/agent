# MySQL 数据库完整配置指南

本指南将从零开始，详细说明如何安装 MySQL、配置数据库、安装依赖，并导入模拟数据。

---

## 📋 目录

1. [安装 MySQL](#1-安装-mysql)
2. [安装 Python 依赖](#2-安装-python-依赖)
3. [启动 MySQL 服务](#3-启动-mysql-服务)
4. [创建数据库](#4-创建数据库)
5. [配置环境变量](#5-配置环境变量)
6. [初始化数据库表](#6-初始化数据库表)
7. [生成模拟数据](#7-生成模拟数据)
8. [验证数据](#8-验证数据)
9. [启动 API 服务](#9-启动-api-服务)
10. [常见问题](#10-常见问题)

---

## 1. 安装 MySQL

### macOS (使用 Homebrew)

#### 1.1 安装 Homebrew（如果未安装）

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

#### 1.2 安装 MySQL

```bash
# 安装 MySQL
brew install mysql

# 查看版本
mysql --version
# 应该显示类似：mysql  Ver 9.x.x for macos...
```

#### 1.3 MySQL 安装位置

- **配置文件**: `/opt/homebrew/etc/my.cnf`
- **数据目录**: `/opt/homebrew/var/mysql`
- **日志文件**: `/opt/homebrew/var/mysql/*.err`
- **可执行文件**: `/opt/homebrew/bin/mysql`

### Linux (Ubuntu/Debian)

```bash
# 更新包列表
sudo apt update

# 安装 MySQL Server
sudo apt install mysql-server

# 查看版本
mysql --version
```

### Linux (CentOS/RHEL)

```bash
# 安装 MySQL
sudo yum install mysql-server

# 查看版本
mysql --version
```

---

## 2. 安装 Python 依赖

### 2.1 确认 Python 版本

```bash
python --version
# 需要 Python 3.11 或更高版本
```

### 2.2 安装项目依赖

```bash
cd /Users/zhaosibo/mycode/demo

# 安装所有依赖
pip install -r requirements.txt

# 或者单独安装数据库相关依赖
pip install SQLAlchemy==2.0.30
pip install PyMySQL==1.1.1
```

### 2.3 验证依赖安装

```bash
python -c "import sqlalchemy; print(f'SQLAlchemy: {sqlalchemy.__version__}')"
python -c "import pymysql; print(f'PyMySQL: {pymysql.__version__}')"
```

**预期输出**：
```
SQLAlchemy: 2.0.30
PyMySQL: 1.1.1
```

---

## 3. 启动 MySQL 服务

### macOS

#### 方式 1：使用 Homebrew Services（推荐）

```bash
# 启动 MySQL 服务（开机自启）
brew services start mysql

# 查看服务状态
brew services list | grep mysql
# 应该显示：mysql         started         ...

# 停止服务
brew services stop mysql

# 重启服务
brew services restart mysql
```

#### 方式 2：手动启动（不作为后台服务）

```bash
# 启动
mysql.server start

# 停止
mysql.server stop

# 重启
mysql.server restart

# 查看状态
mysql.server status
```

### Linux

```bash
# Ubuntu/Debian
sudo systemctl start mysql
sudo systemctl status mysql
sudo systemctl enable mysql  # 开机自启

# CentOS/RHEL
sudo systemctl start mysqld
sudo systemctl status mysqld
sudo systemctl enable mysqld
```

### 验证 MySQL 是否运行

```bash
# 检查进程
ps aux | grep mysqld | grep -v grep

# 或者
pgrep -x mysqld
```

如果有输出，说明 MySQL 正在运行。

---

## 4. 创建数据库

### 4.1 首次登录 MySQL

```bash
# macOS (Homebrew 安装的 MySQL 默认没有密码)
mysql -u root

# 如果提示输入密码，尝试空密码（直接回车）
mysql -u root -p
```

**如果无法登录**，参考 [常见问题 - 无法登录 MySQL](#问题-1无法登录-mysql)。

### 4.2 创建数据库

在 MySQL 命令行中执行：

```sql
-- 创建数据库（使用 utf8mb4 字符集）
CREATE DATABASE IF NOT EXISTS inventory_ai
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

-- 查看数据库
SHOW DATABASES;

-- 应该能看到 inventory_ai

-- 退出
EXIT;
```

### 4.3 创建专用用户（可选，推荐）

如果你想创建一个专用的数据库用户而不是使用 root：

```sql
-- 登录 MySQL
mysql -u root -p

-- 创建用户（替换 'your_password' 为你的密码）
CREATE USER IF NOT EXISTS 'inventory_user'@'localhost'
IDENTIFIED BY 'your_password';

-- 授予权限
GRANT ALL PRIVILEGES ON inventory_ai.* TO 'inventory_user'@'localhost';

-- 刷新权限
FLUSH PRIVILEGES;

-- 验证用户
SELECT User, Host FROM mysql.user WHERE User = 'inventory_user';

-- 退出
EXIT;

-- 测试新用户登录
mysql -u inventory_user -p inventory_ai
```

---

## 5. 配置环境变量

### 5.1 确定连接字符串

根据你的配置，选择对应的连接字符串：

#### 使用 root 用户（无密码）

```
mysql+pymysql://root@localhost:3306/inventory_ai?charset=utf8mb4
```

#### 使用 root 用户（有密码）

```
mysql+pymysql://root:你的密码@localhost:3306/inventory_ai?charset=utf8mb4
```

#### 使用专用用户

```
mysql+pymysql://inventory_user:your_password@localhost:3306/inventory_ai?charset=utf8mb4
```

### 5.2 设置环境变量

#### 方式 1：编辑 .env 文件（推荐）

```bash
cd /Users/zhaosibo/mycode/demo

# 编辑 .env 文件
nano .env
# 或者
vim .env
# 或者
code .env
```

添加或修改以下行：

```bash
# MySQL Database
DATABASE_URL=mysql+pymysql://root@localhost:3306/inventory_ai?charset=utf8mb4
```

保存并退出。

#### 方式 2：临时设置（当前终端会话）

```bash
export DATABASE_URL="mysql+pymysql://root@localhost:3306/inventory_ai?charset=utf8mb4"
```

#### 方式 3：永久设置（添加到 shell 配置）

```bash
# 编辑 ~/.zshrc 或 ~/.bash_profile
echo 'export DATABASE_URL="mysql+pymysql://root@localhost:3306/inventory_ai?charset=utf8mb4"' >> ~/.zshrc

# 重新加载配置
source ~/.zshrc
```

### 5.3 验证环境变量

```bash
echo $DATABASE_URL
# 应该输出你的连接字符串
```

---

## 6. 初始化数据库表

### 6.1 运行初始化脚本

```bash
cd /Users/zhaosibo/mycode/demo

# 确保环境变量已设置
echo $DATABASE_URL

# 运行初始化脚本
python scripts/init_mysql.py
```

**预期输出**：

```
mysql tables created
```

### 6.2 验证表是否创建成功

```bash
mysql -u root inventory_ai -e "SHOW TABLES;"
```

**预期输出**：

```
+-------------------------+
| Tables_in_inventory_ai  |
+-------------------------+
| inventory_items         |
| replenishment_plans     |
| vendor_call_logs        |
| vendors                 |
+-------------------------+
```

### 6.3 查看表结构

```bash
# 查看 vendors 表结构
mysql -u root inventory_ai -e "DESCRIBE vendors;"

# 查看 inventory_items 表结构
mysql -u root inventory_ai -e "DESCRIBE inventory_items;"
```

**vendors 表结构**：

| Field | Type | Null | Key | Default | Extra |
|-------|------|------|-----|---------|-------|
| vendor_id | varchar(32) | NO | PRI | NULL | |
| name | varchar(255) | NO | | NULL | |
| phone_number | varchar(64) | YES | | NULL | |
| email | varchar(255) | YES | | NULL | |
| lead_time_days | int | NO | | NULL | |
| minimum_order | float | NO | | NULL | |
| rating | float | NO | | NULL | |

**inventory_items 表结构**：

| Field | Type | Null | Key | Default | Extra |
|-------|------|------|-----|---------|-------|
| sku | varchar(64) | NO | PRI | NULL | |
| name | varchar(255) | NO | | NULL | |
| category | varchar(64) | NO | | NULL | |
| current_stock | int | NO | | NULL | |
| reorder_point | int | NO | | NULL | |
| daily_sales_velocity | float | NO | | NULL | |
| unit_cost | float | NO | | NULL | |
| vendor_id | varchar(32) | NO | MUL | NULL | |
| lead_time_days | int | NO | | NULL | |
| last_updated | date | YES | | NULL | |

---

## 7. 生成模拟数据

### 7.1 生成数据（5000 SKU + 20 供应商）

```bash
cd /Users/zhaosibo/mycode/demo

# 生成 5000 个 SKU 和 20 个供应商
python scripts/generate_mock_data.py --items 5000 --vendors 20
```

**预期输出**：

```
seeded vendors=20 items=5000
```

### 7.2 自定义数据量

```bash
# 生成 10000 个 SKU 和 50 个供应商
python scripts/generate_mock_data.py --items 10000 --vendors 50

# 生成 100 个 SKU 和 5 个供应商（测试用）
python scripts/generate_mock_data.py --items 100 --vendors 5

# 使用不同的随机种子
python scripts/generate_mock_data.py --items 5000 --vendors 20 --seed 123
```

**参数说明**：

- `--items`: SKU 数量（默认 2000）
- `--vendors`: 供应商数量（默认 12）
- `--seed`: 随机种子（默认 42，用于可重复生成）

### 7.3 数据生成过程说明

脚本会执行以下操作：

1. **生成供应商数据**：
   - 供应商 ID：V001, V002, V003, ...
   - 供应商名称：从预定义列表中循环选择
   - 交货周期：7-18 天（随机）
   - 最小起订量：300-1000（随机）
   - 评分：4.0-4.8（随机）

2. **生成库存商品数据**：
   - SKU：格式为 `类别前缀-序号`（如 HOL-000001）
   - 类别：12 个类别（Holiday, Electronics, Home, Outdoor, Toys, Apparel, Kitchen, Beauty, Office, Sports, Pets, Garden）
   - 当前库存：5-200（随机）
   - 补货点：基于当前库存的 60%-140%（随机）
   - 日销售速度：0.5-15.0（随机）
   - 单位成本：3.0-75.0（随机）
   - 供应商：从已生成的供应商中随机选择

3. **数据插入顺序**：
   - 先删除旧数据（inventory_items → vendors）
   - 先插入 vendors（父表）
   - 再插入 inventory_items（子表，有外键约束）

---

## 8. 验证数据

### 8.1 使用 MySQL 命令行验证

```bash
mysql -u root inventory_ai
```

在 MySQL 命令行中执行：

```sql
-- 查看数据量
SELECT 'Vendors' as Table_Name, COUNT(*) as Count FROM vendors
UNION ALL
SELECT 'Inventory Items', COUNT(*) FROM inventory_items;

-- 查看前 5 个供应商
SELECT * FROM vendors LIMIT 5;

-- 查看前 5 个 SKU
SELECT * FROM inventory_items LIMIT 5;

-- 查看各类别的 SKU 数量
SELECT category, COUNT(*) as count
FROM inventory_items
GROUP BY category
ORDER BY count DESC;

-- 查看库存风险（低于补货点）
SELECT sku, name, current_stock, reorder_point
FROM inventory_items
WHERE current_stock <= reorder_point
LIMIT 10;

-- 查看严重库存风险（库存 < 补货点的 50%）
SELECT sku, name, current_stock, reorder_point,
       ROUND(current_stock / daily_sales_velocity, 2) as days_until_stockout
FROM inventory_items
WHERE current_stock < reorder_point * 0.5
ORDER BY days_until_stockout
LIMIT 10;

-- 退出
EXIT;
```

### 8.2 使用 Python 验证

```bash
cd /Users/zhaosibo/mycode/demo

python -c "
from app.core.settings import settings
from app.db.mysql_repository import MysqlRepository

repo = MysqlRepository(settings.database_url)
items = repo.get_inventory_items()
vendors = repo.get_vendors()

print(f'✅ 库存商品数量: {len(items)}')
print(f'✅ 供应商数量: {len(vendors)}')
print(f'✅ 类别: {sorted(set(item[\"Category\"] for item in items))}')
print(f'✅ 前 3 个 SKU: {[item[\"SKU\"] for item in items[:3]]}')
print(f'✅ 前 3 个供应商: {[v[\"VendorID\"] + \" - \" + v[\"Name\"] for v in vendors[:3]]}')
"
```

**预期输出**：

```
✅ 库存商品数量: 5000
✅ 供应商数量: 20
✅ 类别: ['Apparel', 'Beauty', 'Electronics', 'Garden', 'Holiday', 'Home', 'Kitchen', 'Office', 'Outdoor', 'Pets', 'Sports', 'Toys']
✅ 前 3 个 SKU: ['APP-000012', 'APP-000043', 'APP-000061']
✅ 前 3 个供应商: ['V001 - Holiday Supplies Inc.', 'V002 - Evergreen Wholesale', 'V003 - Aurora Electronics']
```

---

## 9. 启动 API 服务

### 9.1 启动服务

```bash
cd /Users/zhaosibo/mycode/demo

# 确保环境变量已设置
echo $DATABASE_URL

# 启动 API 服务
uvicorn app.main:app --reload --port 8000
```

**预期输出**：

```
INFO:     Will watch for changes in these directories: ['/Users/zhaosibo/mycode/demo']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [xxxxx] using StatReload
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### 9.2 测试 API 端点

在另一个终端窗口中执行：

```bash
# 测试健康检查
curl http://localhost:8000/health | python -m json.tool

# 测试统计接口
curl http://localhost:8000/agents/stats | python -m json.tool

# 测试智能体列表
curl http://localhost:8000/agents/list | python -m json.tool

# 测试智能体调用
curl -X POST http://localhost:8000/agents/invoke \
  -H "Content-Type: application/json" \
  -d '{"agent": "stockout_sentinel", "input": "Show me critical risks", "session_id": "test-001"}' \
  | python -m json.tool
```

### 9.3 访问 API 文档

在浏览器中打开：

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## 10. 常见问题

### 问题 1：无法登录 MySQL

**错误**：`ERROR 1045 (28000): Access denied for user 'root'@'localhost'`

**解决方案 1：重置 root 密码**

```bash
# macOS
mysql.server stop
mysqld_safe --skip-grant-tables &

mysql -u root

# 在 MySQL 中执行
FLUSH PRIVILEGES;
ALTER USER 'root'@'localhost' IDENTIFIED BY 'new_password';
EXIT;

# 重启 MySQL
mysql.server restart

# 使用新密码登录
mysql -u root -p
```

**解决方案 2：使用 sudo（Linux）**

```bash
sudo mysql -u root
```

---

### 问题 2：MySQL 服务无法启动

**错误**：`ERROR! The server quit without updating PID file`

**解决方案**：

```bash
# 查看错误日志
tail -50 /opt/homebrew/var/mysql/*.err

# 常见原因：
# 1. 端口被占用
lsof -i :3306

# 2. 权限问题
sudo chown -R $(whoami) /opt/homebrew/var/mysql

# 3. 配置文件错误
cat /opt/homebrew/etc/my.cnf
```

---

### 问题 3：数据库不存在

**错误**：`Unknown database 'inventory_ai'`

**解决方案**：

```bash
mysql -u root -p -e "CREATE DATABASE inventory_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

---

### 问题 4：外键约束错误

**错误**：`Cannot add or update a child row: a foreign key constraint fails`

**原因**：尝试插入 inventory_items 时，对应的 vendor_id 不存在。

**解决方案**：

```bash
# 清空数据库并重新生成
mysql -u root inventory_ai -e "
DELETE FROM replenishment_plans;
DELETE FROM vendor_call_logs;
DELETE FROM inventory_items;
DELETE FROM vendors;
"

# 重新生成数据
python scripts/generate_mock_data.py --items 5000 --vendors 20
```

---

### 问题 5：SQLAlchemy 未安装

**错误**：`ModuleNotFoundError: No module named 'sqlalchemy'`

**解决方案**：

```bash
pip install SQLAlchemy==2.0.30 PyMySQL==1.1.1
```

---

### 问题 6：连接超时

**错误**：`Can't connect to MySQL server on 'localhost'`

**解决方案**：

```bash
# 检查 MySQL 是否运行
ps aux | grep mysqld | grep -v grep

# 如果未运行，启动服务
brew services start mysql

# 检查端口
lsof -i :3306
```

---

### 问题 7：字符集问题

**错误**：中文或特殊字符显示乱码

**解决方案**：

```sql
-- 检查数据库字符集
SHOW CREATE DATABASE inventory_ai;

-- 应该显示：
-- CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci

-- 如果不是，重新创建数据库
DROP DATABASE inventory_ai;
CREATE DATABASE inventory_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

---

## 📊 数据库表关系图

```
vendors (父表)
├── vendor_id (PK)
├── name
├── phone_number
├── email
├── lead_time_days
├── minimum_order
└── rating

inventory_items (子表)
├── sku (PK)
├── name
├── category
├── current_stock
├── reorder_point
├── daily_sales_velocity
├── unit_cost
├── vendor_id (FK → vendors.vendor_id)
├── lead_time_days
└── last_updated

vendor_call_logs
├── id (PK, AUTO_INCREMENT)
├── vendor_id
├── contact_time
└── notes

replenishment_plans
├── id (PK, AUTO_INCREMENT)
├── created_at
├── total_cost
└── vendor_groups (JSON)
```

---

## 🎯 快速命令参考

```bash
# 1. 启动 MySQL
brew services start mysql

# 2. 创建数据库
mysql -u root -e "CREATE DATABASE inventory_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 3. 设置环境变量
export DATABASE_URL="mysql+pymysql://root@localhost:3306/inventory_ai?charset=utf8mb4"

# 4. 初始化表
python scripts/init_mysql.py

# 5. 生成数据
python scripts/generate_mock_data.py --items 5000 --vendors 20

# 6. 验证数据
mysql -u root inventory_ai -e "SELECT COUNT(*) FROM inventory_items; SELECT COUNT(*) FROM vendors;"

# 7. 启动 API
uvicorn app.main:app --reload --port 8000

# 8. 测试 API
curl http://localhost:8000/agents/stats
```

---

## ✅ 完成检查清单

配置完成后，确认以下所有项目：

- [ ] MySQL 服务已启动
- [ ] 数据库 `inventory_ai` 已创建
- [ ] Python 依赖已安装（SQLAlchemy, PyMySQL）
- [ ] 环境变量 `DATABASE_URL` 已设置
- [ ] 数据库表已初始化（4 张表）
- [ ] 模拟数据已导入（5000 SKU + 20 供应商）
- [ ] 数据验证通过（能查询到数据）
- [ ] API 服务能连接数据库并正常响应

---

## 📚 相关文档

- **API 文档**: `docs/API.md`
- **SP-API 字段映射**: `docs/spapi-mapping.md`
- **开发计划**: `DEV_PLAN.md`
- **项目说明**: `README-2.md`

---

**配置完成！祝你使用愉快！** 🎉
