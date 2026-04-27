# Ozon Seller API 知识库

> 本知识库整理自 Ozon Seller API 官方文档，包含所有 API 端点的描述、参数说明和使用示例。

## 目录

1. [API 基础信息](#api-基础信息)
2. [商品管理 API (Product)](#商品管理-api-product)
3. [类别管理 API (Category)](#类别管理-api-category)
4. [价格与库存 API (Prices & Stocks)](#价格与库存-api-prices--stocks)
5. [FBO 发货 API](#fbo-发货-api)
6. [FBS 发货 API](#fbs-发货-api)
7. [退货管理 API (Returns)](#退货管理-api-returns)
8. [聊天消息 API (Chat)](#聊天消息-api-chat)
9. [财务与报告 API (Finance & Report)](#财务与报告-api-finance--report)
10. [促销管理 API (Promos)](#促销管理-api-promos)
11. [认证管理 API (Certification)](#认证管理-api-certification)
12. [评论与问答 API (Review & Q&A)](#评论与问答-api-review--qa)
13. [仓库管理 API (Warehouse)](#仓库管理-api-warehouse)
14. [其他 API](#其他-api)

---

## API 基础信息

### 认证方式

Ozon Seller API 使用 API Key 认证，需要在请求头中包含以下信息：

```
Client-Id: 你的ClientID
Api-Key: 你的API密钥
Content-Type: application/json
```

### 基础 URL

```
https://api-seller.ozon.ru
```

### 获取 API 密钥

1. 登录 Ozon 卖家后台
2. 进入 **设置 → Seller API**
3. 点击 **生成密钥**
4. 选择角色（权限级别）
5. 点击 **生成**

### 常见 HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 400 | 无效参数 |
| 403 | 访问被拒绝 |
| 404 | 未找到资源 |
| 409 | 请求冲突 |
| 500 | 服务器内部错误 |

---

## 商品管理 API (Product)

### 1. 上传和更新商品

**接口**: `POST /v3/product/import`

**功能**: 上传新商品或更新已有商品，单次最多100个商品。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| items | array | 是 | 商品列表，最多100项 |

**请求示例**:
```json
{
  "items": [
    {
      "description_category_id": 17036038,
      "name": "商品名称",
      "offer_id": "SKU001",
      "price": "100.00",
      "attributes": [
        {
          "id": 31,
          "values": [{"value": "品牌名称"}]
        }
      ],
      "images": [
        {"url": "https://example.com/image.jpg"}
      ],
      "barcode": "1234567890123"
    }
  ]
}
```

**响应参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| task_id | string | 任务ID，用于查询上传状态 |

---

### 2. 查询上传状态

**接口**: `POST /v1/product/import/info`

**功能**: 查询商品上传任务的状态。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | string | 是 | 上传任务ID |

**响应示例**:
```json
{
  "items": [
    {
      "offer_id": "SKU001",
      "product_id": 12345678,
      "status": "imported",
      "errors": []
    }
  ]
}
```

---

### 3. 获取商品列表

**接口**: `POST /v3/product/list`

**功能**: 获取商品列表，支持按状态、可见性等条件筛选。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| filter | object | 否 | 筛选条件 |
| filter.visibility | string | 否 | 可见性: VISIBLE, INVISIBLE, ALL |
| filter.category_id | integer | 否 | 类别ID |
| last_id | string | 否 | 分页游标 |
| limit | integer | 否 | 每页数量，默认100 |

**响应示例**:
```json
{
  "items": [
    {
      "product_id": 12345678,
      "offer_id": "SKU001",
      "name": "商品名称",
      "status": "published"
    }
  ],
  "total": 100,
  "last_id": "next_page_cursor"
}
```

---

### 4. 获取商品详情

**接口**: `POST /v3/product/info/list`

**功能**: 批量获取商品基础信息（标题、价格、库存、状态等）。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| product_id | array | 否 | 商品ID列表，最多100个 |
| offer_id | array | 否 | 商品编码列表，最多100个 |
| sku | array | 否 | SKU列表，最多100个 |

**请求示例**:
```json
{
  "product_id": [12345678, 87654321],
  "offer_id": ["SKU001", "SKU002"]
}
```

**响应参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| product_id | integer | 商品ID |
| offer_id | string | 商品编码 |
| title | string | 商品标题 |
| price | string | 当前价格 |
| old_price | string | 原价 |
| stock | integer | 库存数量 |
| category_id | integer | 类别ID |
| status | string | 状态 |
| images | array | 图片列表 |
| barcode | string | 条码 |

---

### 5. 获取商品完整属性

**接口**: `POST /v4/product/info/attributes`

**功能**: 获取商品的全量属性信息（规格、描述、图片、视频等）。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| product_id | array | 是 | 商品ID列表 |

**请求示例**:
```json
{
  "product_id": [12345678]
}
```

**响应参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| attributes | array | 属性列表 |
| description | string | 商品描述 |
| images | array | 图片链接 |
| videos | array | 视频链接 |

---

### 6. 获取商品描述

**接口**: `POST /v1/product/info/description`

**功能**: 获取商品描述，用于创建相似商品。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| product_id | array | 是 | 商品ID列表 |

**响应示例**:
```json
{
  "result": [
    {
      "product_id": 12345678,
      "description": "商品详细描述..."
    }
  ]
}
```

---

### 7. 上传商品图片

**接口**: `POST /v1/product/pictures/import`

**功能**: 上传或更新商品图片。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| product_id | integer | 是 | 商品ID |
| images | array | 是 | 图片URL列表 |

**请求示例**:
```json
{
  "product_id": 12345678,
  "images": [
    {"url": "https://cloud-storage.com/image1.jpg"},
    {"url": "https://cloud-storage.com/image2.jpg"}
  ]
}
```

---

### 8. 检查图片上传状态

**接口**: `POST /v2/product/pictures/info`

**功能**: 检查图片上传状态。

---

### 9. 归档商品

**接口**: `POST /v1/product/archive`

**功能**: 将商品移至归档。归档前需先将库存清零。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| product_id | array | 是 | 商品ID列表 |

**请求示例**:
```json
{
  "product_id": [12345678]
}
```

---

### 10. 取消归档商品

**接口**: `POST /v1/product/unarchive`

**功能**: 将商品从归档中恢复。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| product_id | array | 是 | 商品ID列表 |

---

### 11. 删除商品

**接口**: `POST /v2/products/delete`

**功能**: 删除没有通过审核、没有SKU且在归档中的商品。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| product_id | array | 是 | 商品ID列表 |

---

### 12. 更新商品属性

**接口**: `POST /v1/product/attributes/update`

**功能**: 仅更新商品属性信息。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| attributes | array | 是 | 属性列表 |
| product_id | integer | 是 | 商品ID |

**请求示例**:
```json
{
  "product_id": 12345678,
  "attributes": [
    {
      "id": 31,
      "values": [{"value": "新品牌名称"}]
    }
  ]
}
```

---

### 13. 上传数字产品激活码

**接口**: `POST /v1/product/upload_digital_codes`

**功能**: 为数字产品上传激活码。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| offer_id | string | 是 | 商品编码 |
| codes | array | 是 | 激活码列表 |

---

### 14. 获取折扣商品信息

**接口**: `POST /v1/product/info/discounted`

**功能**: 通过折扣商品SKU获取折扣及其主商品信息。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| sku | array | 是 | 折扣商品SKU列表 |

---

## 类别管理 API (Category)

### 1. 获取类别树

**接口**: `POST /v1/description-category/tree`

**功能**: 获取完整的商品类别和类型树。

**响应示例**:
```json
{
  "category_tree": [
    {
      "id": 17036000,
      "name": "电子产品",
      "children": [
        {
          "id": 17036001,
          "name": "手机"
        }
      ]
    }
  ]
}
```

---

### 2. 获取类别属性列表

**接口**: `POST /v1/description-category/attribute`

**功能**: 获取特定类别的所有属性列表。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| description_category_id | integer | 是 | 类别ID |

**请求示例**:
```json
{
  "description_category_id": 17036038
}
```

**响应参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| id | integer | 属性ID |
| name | string | 属性名称 |
| description | string | 属性描述 |
| type | string | 值类型: string/dictionary/numeric |
| is_required | boolean | 是否必填 |
| is_collection | boolean | 是否支持多值 |
| is_aspect | boolean | 是否用于筛选 |
| max_value_count | integer | 最大值数量 |
| category_dependent | boolean | 是否依赖类别 |

---

### 3. 获取属性值列表

**接口**: `POST /v1/description-category/attribute/values`

**功能**: 获取特定属性的可选值列表（字典值）。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| attribute_id | integer | 是 | 属性ID |
| description_category_id | integer | 是 | 类别ID |

---

### 4. 搜索属性值

**接口**: `POST /v1/description-category/attribute/values/search`

**功能**: 搜索属性值的候选项。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| attribute_id | integer | 是 | 属性ID |
| description_category_id | integer | 是 | 类别ID |
| search | string | 是 | 搜索关键词 |

---

## 价格与库存 API (Prices & Stocks)

### 1. 更新库存

**接口**: `POST /v2/products/stocks`

**功能**: 更新一个或多个仓库的商品库存。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| warehouse_id | integer | 是 | 仓库ID |
| items | array | 是 | 商品库存列表 |

**请求示例**:
```json
{
  "warehouse_id": 123456,
  "items": [
    {
      "sku": 12345678,
      "stock": 100
    },
    {
      "offer_id": "SKU001",
      "stock": 50
    }
  ]
}
```

---

### 2. 获取库存信息

**接口**: `POST /v4/product/info/stocks`

**功能**: 获取商品库存信息。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| product_id | array | 否 | 商品ID列表 |
| offer_id | array | 否 | 商品编码列表 |

**响应示例**:
```json
{
  "items": [
    {
      "product_id": 12345678,
      "offer_id": "SKU001",
      "stocks": {
        "coming": 0,
        "present": 100,
        "reserved": 10
      }
    }
  ]
}
```

---

### 3. 更新价格

**接口**: `POST /v1/product/import/prices`

**功能**: 批量更新商品价格。

**请求示例**:
```json
{
  "items": [
    {
      "offer_id": "SKU001",
      "price": 99.99,
      "old_price": 129.99,
      "premium_price": 149.99
    }
  ]
}
```

---

## FBO 发货 API

### 1. 获取FBO订单列表

**接口**: `POST /v2/posting/fbo/list`

**功能**: 获取FBO（平台仓发货）订单列表。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| limit | integer | 否 | 每页数量，最大1000 |
| offset | integer | 否 | 偏移量 |
| filter | object | 否 | 筛选条件 |
| filter.since | string | 否 | 开始时间 |
| filter.to | string | 否 | 结束时间 |
| with | object | 否 | 包含额外数据 |

**请求示例**:
```go
body := posting.FboListPayload{
    Limit:  1000,
    Offset: 0,
    With: posting.FboListWith{
        AnalyticsData: true,
        FinancialData: true,
    },
    Filter: posting.FboListFilter{
        Since: "2022-01-01",
        To:    "2022-02-19",
    },
}
```

**响应参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| order_id | integer | 订单ID |
| order_number | string | 订单编号 |
| posting_number | string | 发货编号 |
| status | string | 状态 |
| created_at | string | 创建时间 |
| products | array | 商品列表 |
| analytics_data | object | 分析数据 |
| financial_data | object | 财务数据 |

---

## FBS 发货 API

### 1. 获取FBS订单列表

**接口**: `POST /v3/posting/fbs/list`

**功能**: 获取FBS（自发货）订单列表。

**筛选参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| status | string | 订单状态 |
| since | string | 开始时间 |
| to | string | 结束时间 |

---

### 2. 获取FBS订单详情

**接口**: `POST /v3/posting/fbs/get`

**功能**: 根据ID获取FBS订单详情。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| posting_number | string | 是 | 发货编号 |

---

### 3. 获取待打包订单

**接口**: `POST /v3/posting/fbs/unfulfilled/list`

**功能**: 获取等待打包的订单列表（状态: awaiting_packaging）。

---

### 4. 打包订单

**接口**: `POST /v3/posting/fbs/ship`

**功能**: 打包订单，状态变为 awaiting_deliver。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| posting_number | string | 是 | 发货编号 |

---

### 5. 部分打包订单

**接口**: `POST /v3/posting/fbs/package`

**功能**: 如果订单商品分布在多个包裹中，使用此方法部分打包。

---

### 6. 设置制造国家

**接口**: `POST /v2/posting/fbs/product/country/set`

**功能**: 设置订单商品的制造国家。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| items | array | 是 | 商品和国家的映射列表 |

---

### 7. 获取制造国家列表

**接口**: `POST /v2/posting/fbs/product/country/list`

**功能**: 获取可选的制造国家列表。

---

### 8. 设置物流追踪号

**接口**: `POST /v2/fbs/posting/tracking-number/set`

**功能**: 为第三方配送设置追踪号。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| posting_number | string | 是 | 发货编号 |
| tracking_number | string | 是 | 追踪号 |

---

### 9. 更新订单状态 - 配送中

**接口**: `POST /v2/fbs/posting/delivering`

**功能**: 更新状态为"配送中"。

---

### 10. 更新订单状态 - 最后里程

**接口**: `POST /v2/fbs/posting/last-mile`

**功能**: 更新状态为"快递员在途中"。

---

### 11. 更新订单状态 - 已送达

**接口**: `POST /v2/fbs/posting/delivered`

**功能**: 更新状态为"已送达"。

---

### 12. 打印配送标签

**接口**: `POST /v2/posting/fbs/package-label`

**功能**: 批量打印配送标签。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| posting_number | array | 是 | 发货编号列表 |

---

### 13. 创建发货单据

**接口**: `POST /v2/posting/fbs/act/create`

**功能**: 创建收货交接单和运单。

---

### 14. 获取发货单据状态

**接口**: `POST /v2/posting/fbs/act/check-status`

**功能**: 检查发货单据的状态。

---

## 退货管理 API (Returns)

### 1. 获取FBO退货列表

**接口**: `POST /v2/returns/company/fbo`

**功能**: 获取FBO退货申请列表。

---

### 2. 获取FBS退货列表

**接口**: `POST /v2/returns/company/fbs`

**功能**: 获取FBS退货申请列表。

---

### 3. 接受退货

**接口**: `POST /v1/returns/accept`

**功能**: 接受退货申请。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| return_id | integer | 是 | 退货ID |

---

### 4. 拒绝退货

**接口**: `POST /v1/returns/reject`

**功能**: 拒绝退货申请。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| return_id | integer | 是 | 退货ID |
| reason | string | 是 | 拒绝原因 |

---

## 聊天消息 API (Chat)

### 1. 获取聊天列表

**接口**: `POST /v2/chat/list`

**功能**: 获取与客户的聊天列表。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| unread | boolean | 否 | 仅未读 |

---

### 2. 获取聊天历史

**接口**: `POST /v2/chat/history`

**功能**: 获取特定聊天的消息历史。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| chat_id | integer | 是 | 聊天ID |

---

### 3. 发送消息

**接口**: `POST /v1/chat/send/message`

**功能**: 向客户发送消息。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| chat_id | integer | 是 | 聊天ID |
| message | string | 是 | 消息内容 |

---

### 4. 发送文件

**接口**: `POST /v1/chat/send/file`

**功能**: 发送文件消息。

---

### 5. 创建新聊天

**接口**: `POST /v1/chat/start`

**功能**: 创建新的聊天会话。

---

### 6. 标记消息已读

**接口**: `POST /v2/chat/read`

**功能**: 将聊天消息标记为已读。

---

## 财务与报告 API (Finance & Report)

### 1. 获取交易列表

**接口**: `POST /v1/finance/transaction/list`

**功能**: 获取财务交易流水。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| filter | object | 是 | 筛选条件 |
| filter.date | object | 是 | 日期范围 |
| page | integer | 否 | 页码 |
| page_size | integer | 否 | 每页数量 |

**请求示例**:
```json
{
  "filter": {
    "date": {
      "from": "2024-01-01",
      "to": "2024-01-31"
    }
  },
  "page": 1,
  "page_size": 100
}
```

---

### 2. 获取现金流量表

**接口**: `POST /v1/report/finance/cash-flow-statement`

**功能**: 获取财务现金流报表。

---

### 3. 获取库存报表

**接口**: `POST /v1/report/stocks`

**功能**: 获取库存变动报表。

---

### 4. 获取销售报表

**接口**: `POST /v1/report/sales`

**功能**: 获取销售数据报表。

---

### 5. 获取订单报表

**接口**: 根据配送模式选择
- FBS: `POST /v1/report/orders/fbs`
- FBO: `POST /v1/report/orders/fbo`

---

### 6. 获取分析数据

**接口**: `POST /v1/analytics/data`

**功能**: 获取业务分析数据。

---

### 7. 获取仓库库存

**接口**: `POST /v1/analytics/stocks/warehouse`

**功能**: 获取各仓库的库存数据。

---

## 促销管理 API (Promos)

### 1. 获取可用促销活动

**接口**: `GET /v1/actions`

**功能**: 获取当前可用的促销活动列表。

---

### 2. 获取活动候选商品

**接口**: `POST /v1/actions/candidates`

**功能**: 获取可以参与特定活动的商品列表。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| action_id | integer | 是 | 活动ID |

---

### 3. 设置活动商品

**接口**: `POST /v1/actions/products`

**功能**: 将商品添加到促销活动中。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| action_id | integer | 是 | 活动ID |
| products | array | 是 | 商品列表 |

---

## 认证管理 API (Certification)

### 1. 获取证书类型列表

**接口**: `GET /v1/product/certificate/types`

**功能**: 获取证书文件类型目录。

---

### 2. 获取符合类型列表

**接口**: `GET /v1/product/certificate/accordance-types`

**功能**: 获取符合类型目录。

---

### 3. 创建证书

**接口**: `POST /v1/product/certificate/create`

**功能**: 为商品添加证书。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| files | array | 是 | 证书文件列表（jpg/png/pdf） |
| name | string | 是 | 证书名称 |
| number | string | 是 | 证书编号 |

---

### 4. 获取证书列表

**接口**: `POST /v1/product/certificate/list`

**功能**: 获取卖家的证书列表。

---

### 5. 获取证书信息

**接口**: `POST /v1/product/certificate/info`

**功能**: 获取特定证书的详细信息。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| certificate_id | integer | 是 | 证书ID |

---

### 6. 绑定商品到证书

**接口**: `POST /v1/product/certificate/bind`

**功能**: 将商品与证书关联。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| certificate_id | integer | 是 | 证书ID |
| product_id | array | 是 | 商品ID列表 |

---

### 7. 解绑商品

**接口**: `POST /v1/product/certificate/unbind`

**功能**: 解除商品与证书的关联。

---

### 8. 删除证书

**接口**: `POST /v1/product/certificate/delete`

**功能**: 删除证书。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| certificate_id | integer | 是 | 证书ID |

---

### 9. 获取认证类别列表

**接口**: `POST /v1/product/certification/list`

**功能**: 获取需要认证的商品类别列表。

---

## 评论与问答 API (Review & Q&A)

### 1. 获取评论列表

**接口**: `POST /v1/review/list`

**功能**: 获取商品评论列表。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| product_id | integer | 否 | 商品ID |
| limit | integer | 否 | 每页数量 |

---

### 2. 获取评论详情

**接口**: `POST /v1/review/info`

**功能**: 获取特定评论的详细信息。

---

### 3. 获取评论数量

**接口**: `POST /v1/review/count`

**功能**: 按状态统计评论数量。

---

### 4. 获取评论回复列表

**接口**: `POST /v1/review/comment/list`

**功能**: 获取评论的回复列表。

---

### 5. 更改评论状态

**接口**: `POST /v1/review/change-status`

**功能**: 标记评论状态（如已回复）。

---

### 6. 获取问答列表

**接口**: `POST /v1/questions/list`

**功能**: 获取商品问答列表。

---

### 7. 获取问答详情

**接口**: `POST /v1/questions/info`

**功能**: 获取特定问题的详情。

---

### 8. 回复问题

**接口**: `POST /v1/questions/answer`

**功能**: 回复客户问题。

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| question_id | integer | 是 | 问题ID |
| answer | string | 是 | 回复内容 |

---

## 仓库管理 API (Warehouse)

### 1. 获取仓库列表

**接口**: `POST /v1/warehouse/list`

**功能**: 获取卖家的仓库列表。

**响应示例**:
```json
{
  "warehouses": [
    {
      "id": 123456,
      "name": "主仓库",
      "is_fbs": true,
      "address": {
        "city": "莫斯科",
        "street": "..."
      }
    }
  ]
}
```

---

### 2. 获取仓库详情

**接口**: `POST /v1/warehouse/info`

**功能**: 获取特定仓库的详细信息。

---

## 其他 API

### 1. 获取卖家评分

**接口**: `POST /v1/rating/summary`

**功能**: 获取当前卖家评分摘要。

---

### 2. 获取评分历史

**接口**: `POST /v1/rating/history`

**功能**: 获取卖家评分变化历史。

---

### 3. 生成条码

**接口**: `POST /v1/barcode/generate`

**功能**: 为商品生成条码。

---

### 4. 获取品牌列表

**接口**: `POST /v1/brand/list`

**功能**: 获取可用的品牌列表。

---

### 5. 创建/更新发票

**接口**: `POST /v2/invoice/create-or-update`

**功能**: 创建或更新供应商发票。

---

### 6. 删除发票

**接口**: `POST /v1/invoice/delete`

**功能**: 删除发票链接。

---

### 7. 获取供应订单列表

**接口**: `POST /v2/supplier/order/list`

**功能**: 获取供应商订单列表。

---

### 8. 获取供应订单详情

**接口**: `POST /v2/supplier/order/info`

**功能**: 获取特定供应订单的详情。

---

## 常用代码示例

### Python 示例

```python
import requests

# API 配置
BASE_URL = "https://api-seller.ozon.ru"
CLIENT_ID = "your_client_id"
API_KEY = "your_api_key"

headers = {
    "Client-Id": CLIENT_ID,
    "Api-Key": API_KEY,
    "Content-Type": "application/json"
}

# 获取商品列表
def get_products():
    url = f"{BASE_URL}/v3/product/list"
    data = {
        "filter": {"visibility": "VISIBLE"},
        "limit": 100
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()

# 获取商品详情
def get_product_info(product_ids):
    url = f"{BASE_URL}/v3/product/info/list"
    data = {"product_id": product_ids}
    response = requests.post(url, headers=headers, json=data)
    return response.json()

# 更新库存
def update_stocks(warehouse_id, items):
    url = f"{BASE_URL}/v2/products/stocks"
    data = {
        "warehouse_id": warehouse_id,
        "items": items
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()

# 更新价格
def update_prices(items):
    url = f"{BASE_URL}/v1/product/import/prices"
    data = {"items": items}
    response = requests.post(url, headers=headers, json=data)
    return response.json()
```

### JavaScript/TypeScript 示例

```javascript
const axios = require('axios');

const client = new OzonSellerApiClient({
  apiKey: createApiKey('your-api-key'),
  clientId: createClientId('your-client-id')
});

// 获取商品列表
async function getProducts() {
  const products = await client.product.getList({
    filter: { visibility: 'VISIBLE' },
    last_id: "",
    limit: 100
  });
  return products;
}

// 获取FBS订单
async function getFbsOrders() {
  const orders = await client.fbs.getOrders({
    dir: "ASC",
    filter: {},
    limit: 100,
    offset: 0,
    with: []
  });
  return orders;
}

// 获取财务数据
async function getFinanceData() {
  const finance = await client.finance.getTransactionList({
    filter: { date: { from: '2024-01-01', to: '2024-01-31' } },
    page: 1,
    page_size: 100
  });
  return finance;
}
```

---

## 注意事项

1. **限流**: 官方有QPS限制，批量请求建议分批处理
2. **审核延迟**: 商品信息修改需要通过审核，可能有几天延迟
3. **权限**: API密钥有不同的权限级别，确保选择正确的角色
4. **库存清零**: 归档商品前需先将库存设为0
5. **图片格式**: 图片需上传到云存储，使用直链

---

## 参考链接

- [Ozon Seller API 官方文档](https://docs.ozon.ru/api/seller/)
- [Ozon 开发者社区](https://docs.ozon.ru/global/en/)
- [GitHub SDK 示例](https://github.com/DragonSigh/ozon-seller-api-docs)

---

*文档更新时间: 2024年*
