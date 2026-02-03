#!/usr/bin/env python3
"""
亚马逊 SP-API 沙箱环境测试脚本
测试沙箱环境的所有功能
"""

import os
import sys
import uuid
import requests
from typing import Tuple

# 添加生成的客户端到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'my-spapi-client'))

from swagger_client import ApiClient, Configuration
from swagger_client.api import FbaInventoryApi
from swagger_client.models import (
    CreateInventoryItemRequest,
    InventoryItem,
    AddInventoryRequest
)
from swagger_client.rest import ApiException


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


def _build_client(region: str, use_sandbox: bool, access_token: str) -> Tuple[FbaInventoryApi, str]:
    endpoint_key = f"{region}_sandbox" if use_sandbox else region
    endpoint = REGION_ENDPOINTS.get(endpoint_key, REGION_ENDPOINTS['na'])
    config = Configuration()
    config.host = endpoint
    api_client = ApiClient(config)
    api_client.set_default_header('x-amz-access-token', access_token)
    api_client.set_default_header('Content-Type', 'application/json')
    api_client.set_default_header('Accept', 'application/json')
    return FbaInventoryApi(api_client), endpoint


def _print_api_error(prefix, err: ApiException):
    print(f"✗ {prefix}: {err.status}")
    if err.body:
        print(f"  响应: {err.body}")


def test_sandbox_environment():
    """测试沙箱环境的所有功能"""
    
    print("=" * 70)
    print("亚马逊 SP-API 沙箱环境测试")
    print("=" * 70)
    
    # 获取配置（仅从环境变量读取）
    client_id = os.getenv('AMAZON_SP_API_CLIENT_ID')
    client_secret = os.getenv('AMAZON_SP_API_CLIENT_SECRET')
    refresh_token = os.getenv('AMAZON_SP_API_REFRESH_TOKEN')
    region = os.getenv('AMAZON_SP_API_REGION', 'na')
    use_sandbox = os.getenv('AMAZON_SP_API_USE_SANDBOX', 'true').lower() == 'true'

    if not all([client_id, client_secret, refresh_token]) or refresh_token == 'YOUR_REFRESH_TOKEN_HERE':
        print("\n✗ 缺少必要的环境变量！")
        print("\n请先执行:")
        print("  source ./config.ini")
        return False
    
    try:
        # 获取 Access Token
        print("\n正在获取 Access Token...")
        access_token = _get_access_token(client_id, client_secret, refresh_token)

        # 创建客户端
        print("正在创建沙箱客户端...")
        api, endpoint = _build_client(region, use_sandbox, access_token)
        
        print(f"\n✓ 沙箱客户端已创建")
        print(f"  端点: {endpoint}")
        print(f"  区域: {region}")
        
        # 测试 1: 获取库存摘要
        print("\n" + "-" * 70)
        print("测试 1: 获取库存摘要")
        print("-" * 70)
        try:
            marketplace_code = os.getenv('AMAZON_SP_API_MARKETPLACE', 'us')
            marketplace_id = _get_marketplace_id(marketplace_code)
            response = api.get_inventory_summaries(
                granularity_type='Marketplace',
                granularity_id=marketplace_id,
                marketplace_ids=[marketplace_id],
                details=True
            )
            if response:
                print("✓ 成功获取库存摘要")
                if hasattr(response, 'payload') and response.payload:
                    summaries = getattr(response.payload, 'inventory_summaries', None)
                    count = len(summaries) if summaries else 0
                    print(f"  找到 {count} 个库存项（沙箱测试数据）")
                    
                    # 显示前3个
                    if summaries and len(summaries) > 0:
                        print("\n  前3个库存项:")
                        for i, summary in enumerate(summaries[:3], 1):
                            sku = getattr(summary, 'seller_sku', 'N/A')
                            asin = getattr(summary, 'asin', 'N/A')
                            print(f"    {i}. SKU: {sku}, ASIN: {asin}")
        except ApiException as e:
            _print_api_error("API 错误", e)
        except Exception as e:
            print(f"✗ 失败: {e}")
        
        # 测试 2: 创建库存商品（仅沙箱）
        print("\n" + "-" * 70)
        print("测试 2: 创建库存商品（仅沙箱环境支持）")
        print("-" * 70)
        test_sku = f'TEST-SKU-{uuid.uuid4().hex[:8].upper()}'
        print(f"  测试 SKU: {test_sku}")
        
        try:
            marketplace_code = os.getenv('AMAZON_SP_API_MARKETPLACE', 'us')
            marketplace_id = _get_marketplace_id(marketplace_code)
            request = CreateInventoryItemRequest(
                seller_sku=test_sku,
                marketplace_id=marketplace_id,
                product_name='Sandbox Test Item'
            )

            if not use_sandbox:
                print("↷ 跳过：仅沙箱环境支持")
            else:
                response = api.create_inventory_item(
                    create_inventory_item_request_body=request
                )
                print(f"✓ 成功创建库存商品: {test_sku}")
                print(f"  商品名: Sandbox Test Item")
        except ApiException as e:
            if e.status == 404:
                print("✗ 此操作仅在沙箱环境中可用")
                print("  提示: 请确保 use_sandbox=True")
            elif e.status == 400:
                _print_api_error("请求参数错误", e)
            else:
                _print_api_error("API 错误", e)
        except Exception as e:
            print(f"✗ 失败: {e}")
            test_sku = None  # 标记为未创建，跳过后续测试
        
        # 测试 3: 添加库存（仅沙箱）
        if test_sku:
            print("\n" + "-" * 70)
            print("测试 3: 添加库存（仅沙箱环境支持）")
            print("-" * 70)
            try:
                marketplace_code = os.getenv('AMAZON_SP_API_MARKETPLACE', 'us')
                marketplace_id = _get_marketplace_id(marketplace_code)
                inventory_item = InventoryItem(
                    seller_sku=test_sku,
                    marketplace_id=marketplace_id,
                    quantity=5
                )
                
                add_request = AddInventoryRequest(
                    inventory_items=[inventory_item]
                )
                
                idempotency_token = str(uuid.uuid4())
                if not use_sandbox:
                    print("↷ 跳过：仅沙箱环境支持")
                else:
                    response = api.add_inventory(
                        x_amzn_idempotency_token=idempotency_token,
                        add_inventory_request_body=add_request
                    )
                    print(f"✓ 成功添加库存: {test_sku}")
                    print(f"  添加数量: 5")
            except ApiException as e:
                if e.status == 404:
                    print("✗ 此操作仅在沙箱环境中可用")
                elif e.status == 400:
                    _print_api_error("请求参数错误", e)
                else:
                    _print_api_error("API 错误", e)
            except Exception as e:
                print(f"✗ 失败: {e}")
        
        # 测试 4: 删除库存商品（仅沙箱）
        if test_sku:
            print("\n" + "-" * 70)
            print("测试 4: 删除库存商品（仅沙箱环境支持）")
            print("-" * 70)
            try:
                marketplace_code = os.getenv('AMAZON_SP_API_MARKETPLACE', 'us')
                marketplace_id = _get_marketplace_id(marketplace_code)
                if not use_sandbox:
                    print("↷ 跳过：仅沙箱环境支持")
                else:
                    delete_sku = f'DEL-SKU-{uuid.uuid4().hex[:8].upper()}'
                    create_req = CreateInventoryItemRequest(
                        seller_sku=delete_sku,
                        marketplace_id=marketplace_id,
                        product_name='Sandbox Delete Item'
                    )
                    api.create_inventory_item(create_inventory_item_request_body=create_req)
                    response = api.delete_inventory_item(
                        seller_sku=delete_sku,
                        marketplace_id=marketplace_id
                    )
                    print(f"✓ 成功删除库存商品: {delete_sku}")
            except ApiException as e:
                if e.status == 404:
                    print("✗ 此操作仅在沙箱环境中可用")
                elif e.status == 400:
                    _print_api_error("请求参数错误", e)
                else:
                    _print_api_error("API 错误", e)
            except Exception as e:
                print(f"✗ 失败: {e}")
        
        print("\n" + "=" * 70)
        print("测试完成")
        print("=" * 70)
        print("\n提示:")
        print("- 如果某些操作失败，请确保使用的是沙箱环境（use_sandbox=True）")
        print("- 沙箱环境返回的是测试数据，不是真实库存")
        print("- 创建/删除/添加库存操作仅在沙箱环境中可用")
        
        return True
        
    except Exception as e:
        print(f"\n✗ 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = test_sandbox_environment()
    sys.exit(0 if success else 1)
