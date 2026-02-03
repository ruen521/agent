#!/usr/bin/env python3
"""
SP-API 连接测试脚本
用于验证沙箱环境配置是否正确
"""

import os
import sys
from datetime import datetime, timedelta
import requests

# 添加生成的客户端到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'my-spapi-client'))

try:
    from swagger_client import ApiClient, Configuration
    from swagger_client.api import FbaInventoryApi
except ImportError:
    print("✗ 导入失败，请确保已安装依赖：")
    print("  cd my-spapi-client && pip install -r requirements.txt")
    sys.exit(1)


REGION_ENDPOINTS = {
    'na': 'https://sellingpartnerapi-na.amazon.com',
    'na_sandbox': 'https://sandbox.sellingpartnerapi-na.amazon.com',
    'eu': 'https://sellingpartnerapi-eu.amazon.com',
    'eu_sandbox': 'https://sandbox.sellingpartnerapi-eu.amazon.com',
    'fe': 'https://sellingpartnerapi-fe.amazon.com',
    'fe_sandbox': 'https://sandbox.sellingpartnerapi-fe.amazon.com'
}

MARKETPLACE_IDS = {
    'us': 'ATVPDKIKX0DER',
    'ca': 'A2EUQ1WTGCTBG2',
    'uk': 'A1F83G8C2ARO7P',
    'de': 'A1PA6795UKMFR9',
    'fr': 'A13V1IB3VIYZZH',
    'it': 'APJ6JRA9NG5V4',
    'es': 'A1RKKUPIHCS9HS',
    'jp': 'A1VC38T7YXB528'
}


def _get_marketplace_id(marketplace_code):
    return MARKETPLACE_IDS.get(marketplace_code, marketplace_code)


def _get_access_token(client_id, client_secret, refresh_token):
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret
    }
    response = requests.post(
        "https://api.amazon.com/auth/o2/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10
    )
    response.raise_for_status()
    data = response.json()
    return data["access_token"]


def test_connection():
    """测试 SP-API 连接"""
    
    print("=" * 70)
    print("SP-API 连接测试")
    print("=" * 70)
    
    # 获取配置（仅从环境变量读取）
    client_id = os.getenv('AMAZON_SP_API_CLIENT_ID')
    client_secret = os.getenv('AMAZON_SP_API_CLIENT_SECRET')
    refresh_token = os.getenv('AMAZON_SP_API_REFRESH_TOKEN')
    region = os.getenv('AMAZON_SP_API_REGION', 'na')
    use_sandbox = os.getenv('AMAZON_SP_API_USE_SANDBOX', 'false').lower() == 'true'
 
    if not all([client_id, client_secret, refresh_token]) or refresh_token == 'YOUR_REFRESH_TOKEN_HERE':
        print("\n✗ 缺少以下环境变量:")
        print("  - AMAZON_SP_API_CLIENT_ID")
        print("  - AMAZON_SP_API_CLIENT_SECRET")
        print("  - AMAZON_SP_API_REFRESH_TOKEN")
        print("\n请先执行:")
        print("  source ./config.ini")
        return False
    
    print(f"\n配置信息:")
    print(f"  区域: {region}")
    print(f"  环境: {'沙箱' if use_sandbox else '生产'}")
    print(f"  Client ID: {client_id[:20]}...")
    
    try:
        # 获取 Access Token
        print("\n正在获取 Access Token...")
        access_token = _get_access_token(client_id, client_secret, refresh_token)
        print(f"✓ Access Token 获取成功")
        print(f"  Token 前缀: {access_token[:30]}...")

        # 创建客户端
        print("\n正在创建 SP-API 客户端...")
        endpoint_key = f"{region}_sandbox" if use_sandbox else region
        endpoint = REGION_ENDPOINTS.get(endpoint_key, REGION_ENDPOINTS['na'])
        config = Configuration()
        config.host = endpoint
        api_client = ApiClient(config)
        api_client.set_default_header('x-amz-access-token', access_token)
        api_client.set_default_header('Content-Type', 'application/json')
        api_client.set_default_header('Accept', 'application/json')
        api = FbaInventoryApi(api_client)

        print(f"✓ 客户端创建成功")
        print(f"  端点: {endpoint}")
        print(f"  区域: {region}")
        print(f"  环境: {'沙箱' if use_sandbox else '生产'}")
        
        # 测试 API 调用
        print("\n正在测试 API 连接...")
        marketplace_code = os.getenv('AMAZON_SP_API_MARKETPLACE', 'us')
        marketplace_id = _get_marketplace_id(marketplace_code)
        response = api.get_inventory_summaries(
            granularity_type='Marketplace',
            granularity_id=marketplace_id,
            marketplace_ids=[marketplace_id],
            details=True
        )
        
        print("✓ API 调用成功！")
        print(f"  响应类型: {type(response).__name__}")
        
        if response and hasattr(response, 'payload'):
            payload = response.payload
            if payload and hasattr(payload, 'inventory_summaries'):
                summaries = payload.inventory_summaries
                count = len(summaries) if summaries else 0
                print(f"  库存项数量: {count}")
        
        print("\n" + "=" * 70)
        print("✓ 配置验证成功！所有测试通过")
        print("=" * 70)
        print("\n您可以开始使用 SP-API 了！")
        print("\n下一步:")
        print("  - 运行完整测试: python test_sandbox.py")
        print("  - 查看示例代码: spapi_config_example.py")
        print("  - 阅读使用指南: 沙箱环境使用指南.md")
        
        return True
        
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        print("\n可能的原因:")
        print("  1. 凭证不正确")
        print("  2. 网络连接问题")
        print("  3. API 端点不可访问")
        print("  4. 权限不足")
        
        import traceback
        print("\n详细错误信息:")
        traceback.print_exc()
        
        return False


if __name__ == '__main__':
    success = test_connection()
    sys.exit(0 if success else 1)
