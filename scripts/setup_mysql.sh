#!/bin/bash
# MySQL 数据库快速配置脚本
# 用法: ./scripts/setup_mysql.sh

set -e  # 遇到错误立即退出

# 获取脚本所在目录的父目录（项目根目录）
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# 切换到项目根目录
cd "$PROJECT_ROOT"

echo "=========================================="
echo "MySQL 数据库配置脚本"
echo "=========================================="
echo "项目目录: $PROJECT_ROOT"
echo ""

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 检查 MySQL 是否运行
echo "📋 步骤 1: 检查 MySQL 服务状态..."
if pgrep -x mysqld > /dev/null; then
    echo -e "${GREEN}✅ MySQL 服务正在运行${NC}"
else
    echo -e "${YELLOW}⚠️  MySQL 服务未运行，正在启动...${NC}"
    brew services start mysql
    sleep 3
    if pgrep -x mysqld > /dev/null; then
        echo -e "${GREEN}✅ MySQL 服务已启动${NC}"
    else
        echo -e "${RED}❌ MySQL 服务启动失败${NC}"
        exit 1
    fi
fi
echo ""

# 提示输入 root 密码
echo "📋 步骤 2: 配置数据库..."
echo -e "${YELLOW}请输入 MySQL root 密码（如果没有设置密码，直接回车）:${NC}"
read -s MYSQL_ROOT_PASSWORD
echo ""

# 测试连接
echo "🔍 测试 MySQL 连接..."
if [ -z "$MYSQL_ROOT_PASSWORD" ]; then
    MYSQL_CMD="mysql -u root"
else
    MYSQL_CMD="mysql -u root -p$MYSQL_ROOT_PASSWORD"
fi

if ! $MYSQL_CMD -e "SELECT 1;" > /dev/null 2>&1; then
    echo -e "${RED}❌ 无法连接到 MySQL，请检查密码是否正确${NC}"
    exit 1
fi
echo -e "${GREEN}✅ MySQL 连接成功${NC}"
echo ""

# 创建数据库
echo "📋 步骤 3: 创建数据库 inventory_ai..."
$MYSQL_CMD <<EOF
CREATE DATABASE IF NOT EXISTS inventory_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
EOF
echo -e "${GREEN}✅ 数据库 inventory_ai 已创建${NC}"
echo ""

# 询问是否创建专用用户
echo -e "${YELLOW}是否创建专用数据库用户？(y/n，推荐选 y):${NC}"
read -r CREATE_USER

if [ "$CREATE_USER" = "y" ] || [ "$CREATE_USER" = "Y" ]; then
    echo "请输入新用户名（默认: inventory_user）:"
    read -r DB_USER
    DB_USER=${DB_USER:-inventory_user}

    echo "请输入新用户密码:"
    read -s DB_PASSWORD
    echo ""

    echo "正在创建用户 $DB_USER..."
    $MYSQL_CMD <<EOF
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON inventory_ai.* TO '$DB_USER'@'localhost';
FLUSH PRIVILEGES;
EOF
    echo -e "${GREEN}✅ 用户 $DB_USER 已创建并授权${NC}"

    # 生成连接字符串
    DATABASE_URL="mysql+pymysql://$DB_USER:$DB_PASSWORD@localhost:3306/inventory_ai?charset=utf8mb4"
else
    DB_USER="root"
    if [ -z "$MYSQL_ROOT_PASSWORD" ]; then
        DATABASE_URL="mysql+pymysql://root@localhost:3306/inventory_ai?charset=utf8mb4"
    else
        DATABASE_URL="mysql+pymysql://root:$MYSQL_ROOT_PASSWORD@localhost:3306/inventory_ai?charset=utf8mb4"
    fi
fi
echo ""

# 更新 .env 文件
echo "📋 步骤 4: 更新 .env 文件..."
ENV_FILE=".env"

if [ -f "$ENV_FILE" ]; then
    # 检查是否已有 DATABASE_URL
    if grep -q "^DATABASE_URL=" "$ENV_FILE"; then
        # 备份原文件
        cp "$ENV_FILE" "${ENV_FILE}.backup"
        echo -e "${YELLOW}⚠️  已备份原 .env 文件到 .env.backup${NC}"

        # 替换 DATABASE_URL
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s|^DATABASE_URL=.*|DATABASE_URL=$DATABASE_URL|" "$ENV_FILE"
        else
            sed -i "s|^DATABASE_URL=.*|DATABASE_URL=$DATABASE_URL|" "$ENV_FILE"
        fi
    else
        # 追加 DATABASE_URL
        echo "" >> "$ENV_FILE"
        echo "# MySQL Database" >> "$ENV_FILE"
        echo "DATABASE_URL=$DATABASE_URL" >> "$ENV_FILE"
    fi
else
    # 创建新的 .env 文件
    echo "DATABASE_URL=$DATABASE_URL" > "$ENV_FILE"
fi
echo -e "${GREEN}✅ .env 文件已更新${NC}"
echo ""

# 导出环境变量
export DATABASE_URL="$DATABASE_URL"

# 初始化表结构
echo "📋 步骤 5: 初始化数据库表..."
if python scripts/init_mysql.py; then
    echo -e "${GREEN}✅ 数据库表已创建${NC}"
else
    echo -e "${RED}❌ 数据库表创建失败${NC}"
    exit 1
fi
echo ""

# 验证表
echo "🔍 验证表结构..."
$MYSQL_CMD inventory_ai -e "SHOW TABLES;"
echo ""

# 询问是否生成数据（会清空现有数据）
echo -e "${YELLOW}是否生成模拟数据？会删除现有 vendors 与 inventory_items（y/n）:${NC}"
read -r GENERATE_DATA

if [ "$GENERATE_DATA" = "y" ] || [ "$GENERATE_DATA" = "Y" ]; then
    echo "请输入 SKU 数量（默认: 30）:"
    read -r ITEMS_COUNT
    ITEMS_COUNT=${ITEMS_COUNT:-30}

    echo "请输入供应商数量（默认: 4）:"
    read -r VENDORS_COUNT
    VENDORS_COUNT=${VENDORS_COUNT:-4}

    echo "📋 步骤 6: 生成模拟数据（$ITEMS_COUNT SKU + $VENDORS_COUNT 供应商）..."
    if python scripts/generate_mock_data.py --items "$ITEMS_COUNT" --vendors "$VENDORS_COUNT"; then
        echo -e "${GREEN}✅ 模拟数据已生成${NC}"
    else
        echo -e "${RED}❌ 模拟数据生成失败${NC}"
        exit 1
    fi
    echo ""

    # 验证数据
    echo "🔍 验证数据..."
    $MYSQL_CMD inventory_ai -e "
    SELECT 'Vendors' as Table_Name, COUNT(*) as Count FROM vendors
    UNION ALL
    SELECT 'Inventory Items', COUNT(*) FROM inventory_items;
    "
fi
echo ""

# 完成
echo "=========================================="
echo -e "${GREEN}✅ MySQL 配置完成！${NC}"
echo "=========================================="
echo ""
echo "📝 连接信息："
echo "  数据库: inventory_ai"
echo "  用户: $DB_USER"
echo "  连接字符串已保存到 .env 文件"
echo ""
echo "🚀 下一步："
echo "  1. 启动 API 服务: uvicorn app.main:app --reload"
echo "  2. 测试接口: curl http://localhost:8000/agents/stats"
echo ""
