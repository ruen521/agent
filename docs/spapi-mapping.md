# SP-API 字段映射（M3）

## 数据域
- Catalog Items → `InventoryItems` (预留 `ASIN`, `Name`, `Category`)
- Listings → `InventoryItems` (预留 `SellerSKU`, `FulfillmentChannel`)
- Inventory (FBA summaries) → `InventoryItems`
- Orders → `SalesHistory` (预留)

## Inventory Summaries → InventoryItems
| SP-API 字段 | 说明 | InventoryItems 字段 |
| --- | --- | --- |
| `sellerSku` | SKU | `SKU` |
| `asin` | ASIN | `ASIN` (预留) |
| `productName` | 商品名 | `Name` |
| `condition` | 货况 | `Condition` (预留) |
| `totalQuantity` | 可售总数 | `CurrentStock` |
| `inboundQuantity` | 在途 | `InboundStock` (预留) |
| `reservedQuantity` | 已预留 | `ReservedStock` (预留) |
| `inventoryDetails.fulfillableQuantity` | 可履约 | `FulfillableStock` (预留) |
| `inventoryDetails.unfulfillableQuantity` | 不可履约 | `UnfulfillableStock` (预留) |

## Orders → SalesHistory（预留）
| SP-API 字段 | 说明 | SalesHistory 字段 |
| --- | --- | --- |
| `AmazonOrderId` | 订单ID | `OrderId` |
| `PurchaseDate` | 购买时间 | `OrderDate` |
| `OrderTotal.Amount` | 金额 | `OrderAmount` |
| `OrderStatus` | 状态 | `OrderStatus` |
| `SellerSKU` | SKU | `SKU` |

## Catalog Items → InventoryItems（预留）
| SP-API 字段 | 说明 | InventoryItems 字段 |
| --- | --- | --- |
| `asin` | ASIN | `ASIN` |
| `attributes.item_name` | 商品名 | `Name` |
| `attributes.item_type_keyword` | 类目关键词 | `Category` |
