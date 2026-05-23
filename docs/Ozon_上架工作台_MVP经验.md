# Ozon 上架工作台 MVP 经验

日期: 2026-05-23

## 目标

先不追求完整 DDD，把 Ozon 上架/更新业务跑通，并把 WALLET-0006 Black 的经验沉淀到我们自己的上架页面。

上架和更新走同一条逻辑：`offer_id` 已存在时，Ozon `/v3/product/import` 会按增量更新处理；不存在时就是新建上架。

## 当前页面能力

入口: `/ozon-listing?skc=WALLET-0006&store_id=ozon_anling`

页面新增“上架工作台”区，覆盖五个动作：

- 自动生成草稿: 调用 `/api/ozon/<store_id>/listing/generate-draft`
- 程序验证: 调用 `/api/ozon/<store_id>/listing/validate`
- 准备图片 URL: 调用 `/api/ozon/<store_id>/listing/prepare-images`
- 官方评分: 调用 `/api/ozon/<store_id>/listing/official-rating`
- 提交/更新: 调用 `/api/ozon/<store_id>/listing/upsert`

## 分类匹配

WALLET 系列先用确定性规则：

- `description_category_id`: `17027904`
- `type_id`: `93338`
- 类目: `Галантерея и аксессуары > Аксессуары > Кошелек`

后续扩展其它品类时，先用程序规则缩小候选，再让 LLM 只在候选集中结构化选择，不能让 LLM 自由发挥类目 ID。

## 属性填充原则

属性分三层：

- 程序确定: category/type、offer_id、颜色、数量、材质、产地、尺寸、重量等。
- 运营确认: 品牌、系列、是否基础款、卖点表达。
- LLM 生成: 标题、描述、富文本文案、标签等表达型字段。

重要属性要单独开 LLM 会话，并要求结构化输出。程序必须验证：

- 必填字段是否齐全。
- 字典属性是否有 `dictionary_value_id`。
- 品牌来源是否可信。
- Rich Content JSON 是否符合 Ozon 当前可接受模板。
- 图片是否有可公开访问 URL。

## 品牌规则

不能直接把采集店铺名当品牌。

当前规则：

- 人工录入品牌优先，来源标记为 `manual`。
- 已知品牌词命中时规范化，比如 `BOSTANTEN Store` 会变成 `Bostanten`，并使用 Ozon 字典值 `971068372`，来源标记为 `known_brand`。
- 未知采集品牌会标记为 `scraped_shop`，程序验证阻断提交。
- 没有证据时，WALLET-0006 先使用运营默认 `Bostanten`。

## 系列属性

`Коллекция / 系列` 不能按字面翻成“采集到什么填什么”。运营视角更接近“商品生命周期/主题系列”：

- 没有明确季节、联名、节日或款式系列证据时，用 `Базовая коллекция`。
- 不从店铺名、标题噪声、Amazon 分类名里推断系列。
- 若后续有新品系列，应作为运营字段写入 `manual_data`，再由程序填入 Ozon 字典值。

## 图片经验

Ozon 需要公网可访问图片 URL。页面当前能把本地 `/product_images/...` 转成当前站点绝对 URL，也能保留已经是 `http/https` 的图片。

真实提交通常仍要先把图片上传到临时图床或自有服务器：

- 0x0 当前可能返回 `503`，脚本保留但要自动降级。
- tmpfiles 可用于临时跑通，但不适合长期正式业务。
- 正式业务建议用香港服务器、OSS、R2 或 S3，保证链接不过期。

## 分数经验

WALLET-0006 Black 已经通过真实 Ozon 环境验证：

- `offer_id`: `WALLET-0006-BLACK`
- Ozon `product_id`: `4708278736`
- Ozon `sku`: `4408894048`
- 官方内容评分: `77.5`

评分从约 `65` 提升到 `77.5` 的关键是补上 `11254 Rich Content JSON`。

继续提升优先级：

- 图片数量从 6 张补到 8 张以上。
- 增加视频或视频封面。
- 保证 Rich Content 使用真实商品图，不使用占位图。

## 下一步

- 把图片上传能力从脚本沉到页面工作台。
- 给重要属性增加单独 LLM 结构化生成和程序校验。
- 对不同品类建立候选类目规则，而不是只支持钱包。
- 提交后自动轮询 import 状态，并把 Ozon warning/error 回写到页面。
