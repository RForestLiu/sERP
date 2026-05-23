# Ozon WALLET-0006 Black 上架复盘

日期: 2026-05-23

## 结果

- `offer_id`: `WALLET-0006-BLACK`
- Ozon `product_id`: `4708278736`
- Ozon `sku`: `4408894048`
- 提交接口: `/v3/product/import`
- 状态: 已导入/可用同 `offer_id` 增量更新
- 内容评分: `77.5`

## 图片临时图床

- 0x0 当前返回 `503`，原因是服务方暂停上传。
- 脚本保留 `--upload-0x0` 参数，但会在 0x0 不可用时自动降级到 tmpfiles。
- tmpfiles 链接过期时间短，适合临时跑通 Ozon 抓图，不适合正式长期业务。
- 成功上传后脚本会缓存 URL 到 `data/ozon_live/wallet0006_black_image_urls.json`，避免短时间内重复上传。

正式业务建议还是用自有服务器、OSS、R2 或 S3 保存图片，避免临时图床过期导致后续更新失败。

## 评分经验

第一次导入后评分为 `65`:

- 媒体: `50`
- 文本描述: `50`
- 其他属性: `100`

补上 `11254 Rich-контент JSON` 后，评分提升到 `77.5`:

- 文本描述变为 `100`
- `text_rich` 条件变为 `fulfilled=true`
- 媒体仍是 `50`，因为只有 6 张图片，没有视频，也没有 8 张以上图片

要继续提高分数，优先补第 8 张图或视频/视频封面。

## Rich Content 要点

Ozon 接受的 Rich Content 不是普通的 `version/content/type=text` 简化 JSON。当前验证可用的结构是:

```json
{
  "content": [
    {
      "widgetName": "raShowcase",
      "type": "billboard",
      "blocks": []
    }
  ],
  "version": 0.3
}
```

每个 block 使用 `imgLink`、`img`、`title`、`text`，其中 `title` 和 `text` 都要按 Ozon 模板带 `content/size/align/color`。模板错误时，Ozon 不会阻塞导入，但会用 `erased_attribute_value` warning 擦除 `11254`。

## 脚本修复点

- Windows 输出强制 UTF-8/replace，避免 Ozon 返回特殊空格时 GBK 控制台崩溃。
- `rating-by-sku` 需要 Ozon 数字 SKU，不能传本地 `offer_id`。
- 脚本现在先调用 `/v3/product/info/list` 按 `offer_id` 查询数字 SKU，再调用 `/v1/product/rating-by-sku`。
- Ozon import 状态 `skipped` 也是终态，重复更新时不应继续轮询。
