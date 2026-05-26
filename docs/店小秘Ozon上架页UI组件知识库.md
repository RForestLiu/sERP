# 店小秘 Ozon 上架页 UI 组件知识库

更新时间: 2026-05-26

## 目标

这份知识库服务 Chrome 扩展自动填充: 扩展读取 sERP 采集到的产品数据，调用 AI 生成字段映射，再把结果填入店小秘 `https://www.dianxiaomi.com/web/ozonProduct/add` / `edit` 页面。

安全边界:

- 自动化只负责填写表单和展示结果。
- 不自动点击 `保存`、`发布`、`提交`、`创建` 等会产生真实业务动作的按钮。
- 价格、库存、重量、尺寸等确定性字段优先由程序计算或读取，不交给 AI 自由发挥。

## 页面分区

Ozon 创建页初始只显示少量字段。选定店铺和 Ozon 分类后，页面会追加分类属性、描述、图片、变种和 SKU 表格。

完整页面按视觉区域可分为:

- 顶部操作条: `一键翻译`、`存为模板`、`引用产品`、`保存`、`发布`。
- 右侧锚点导航: `基本信息`、`店小秘信息`、`产品信息`、`描述信息`、`变种属性`、`变种信息`、`变种图片`、`定时刊登` 等。
- 基本信息: 店铺、产品分类、平台分类属性。
- 店小秘信息: 店小秘分类、来源 URL。
- 产品信息: 标题、VAT、积分评价、分类公共属性。
- 描述信息: 产品描述、JSON 富文本、视频/PDF 上传。
- 变种属性: 变种主题、颜色/规格属性。
- 变种信息: SKU、售价、原价、库存、尺寸、重量、操作列。
- 变种图片: 每个变种的图片组、图片上传/排序/删除入口。
- 定时刊登: 定时发布开关和时间类控件。

## 分类选择后的动态展开

Ozon 分类是页面 schema 的分水岭。未选择分类时只能采集到店铺、分类、来源 URL、标题、VAT 等基础控件；选择分类并等待渲染后，才会出现平台分类属性、描述信息、变种属性、变种信息、变种图片和积分评价推广。

2026-05-24 在创建页选择 `小百货和配饰(Галантерея и аксессуары) > 配饰(Аксессуары) > 钱包(Кошелек)` 后，页面可见控件快照为:

- `ant-select`: 14 个。
- `button`: 22 个。
- `input-checkbox`: 209 个。
- `input-search`: 14 个。
- `input-text`: 25 个。
- `table`: 1 个。
- `textarea`: 1 个。

这些数量是钱包分类的 live 快照，其他 Ozon 分类会变化。扩展不能把数量写死，只能把它作为回归检测信号。

钱包分类展开后新增的典型属性:

- 直接文本/数字输入: `商品重量，克`、`配套`、`保修期`、`高度，厘米`、`宽度，厘米`、`深度，厘米`、`一个包装中的数量`、`原厂包装数量`、`组合成类似的产品`、`#主题标签`、`统一计量单位中的商品数量`。
- Ant 搜索下拉 + 添加 + 复选项: `包装`、`原产国`、`材料`。这类字段要先搜索字典值，必要时点 `添加`，再确认目标复选项被选中。
- 属性搜索过滤框 + 大量复选项: `五金材料`、`衬里/内饰材料`、`扣子类型`、`分行`。这里的输入框只是过滤选项，不是字段值；自动化应输入搜索词、勾选目标 checkbox，然后按需清空过滤词。
- 普通 Ant 单选: `签名18+`、`系列`、`欧亚经济联盟的HS编码`、`Haberdashery的类型`、`保证`。
- 普通 checkbox 组: `性别`、`目标受众`。
- 展开后的业务区: `产品描述` textarea、`JSON富文本`模板/编辑入口、视频按钮、`变种主题`、SKU 表格、变种图片上传区、`积分评价`开关。

扩展填充流程必须在分类路径文本出现、且 `产品属性` 区域内至少存在一个分类属性后，才允许执行完整字段采集。分类路径本身是展示文本，不是可填字段；真正驱动字段展开的是产品分类控件。

## 组件总表

| 组件类型 | DOM 特征 | 常见字段 | 填写方式 | 验证信号 |
|---|---|---|---|---|
| 普通文本输入 | `input.ant-input` | 标题、来源 URL、颜色名称、SKU | focus -> selectAll -> insertText/value setter -> `input/change/keyup/blur` | `input.value` 等于目标值，字数计数更新 |
| 数字输入 | `input.ant-input`, `.ant-input-number-input` | 重量、长宽高、售价、原价 | 同文本输入；值必须先规范成纯数字 | 页面显示值更新，SKU 行联动不丢失 |
| 多行文本 | `textarea.ant-input` | 产品描述、普通长文 | focus -> selectAll -> insertText/value setter -> `input/change` | `textarea.value` 更新，计数器更新 |
| Ant 单选下拉 | `.ant-select:not(.ant-select-multiple)` | 店铺、VAT、分类固定枚举 | 点击 `.ant-select-selector`，等待 `.ant-select-dropdown`，按文本匹配 option 点击 | `.ant-select-selection-item` 显示选中值 |
| Ant 搜索下拉 | `.ant-select-show-search` | 品牌、材质、产地、部分 Ozon 字典属性 | 点击后向内部 `input.ant-select-selection-search-input` 输入搜索词，等待远程候选，再点击 option | 选中项显示；远程候选消失 |
| Ant 多选下拉 | `.ant-select-multiple` | 标签、商品颜色、多值字典属性 | 逐个搜索/点击候选；避免重复；必要时限制最大数量 | 多个 `.ant-select-selection-item` 出现 |
| Checkbox 组 | `.ant-checkbox-group` 或同一 form-item 内多个 checkbox | 多选属性、功能、适用场景 | 按选项文本归一化匹配，设置 checked 并触发 `change` | 目标 checkbox 选中，非目标不误选 |
| 属性搜索过滤框 + Checkbox 组 | 同一 form-item 内有 `input.ant-input` 和大量 checkbox | 五金材料、衬里/内饰材料、扣子类型、分行 | 输入框只用于过滤候选；搜索后勾选目标 checkbox，不能把搜索词当成字段值 | 目标 checkbox 选中，过滤词不会被当作 currentValue |
| Radio 组 | `.ant-radio-group` 或同一 form-item 内多个 radio | 单选属性 | 按选项文本匹配，设置目标 radio checked 并触发 `change` | 同组只有一个 checked |
| 独立 Checkbox | 单个 `input[type=checkbox]` | 积分评价、开关类字段 | 布尔值 `true/false` 映射 checked | checked 状态符合目标 |
| Ant Switch | `.ant-switch` | JSON 模式、开关项、定时刊登 | 点击切换；不要用 value 写入 | `.ant-switch-checked` 状态符合目标 |
| JSON 编辑器 | `编辑JSON代码` 按钮、弹窗、CodeMirror/textarea/contenteditable | Ozon Rich Content JSON | 点击编辑按钮，优先用 CodeMirror API，其次写 textarea/contenteditable，再点确定/保存 | 弹窗关闭，JSON 字段区域保留内容 |
| 上传组件 | `.ant-upload`, 图片/视频上传卡片 | 主图、视频、PDF | 文件上传需要真实文件输入；URL 型图片通常不能靠普通 input 直接填 | 图片缩略图/文件列表出现 |
| 分类选择弹窗 | `选择分类` 按钮、modal/tree/search | Ozon 产品分类 | 点击按钮，搜索/逐级选择分类，确认后等待动态属性渲染 | 页面显示已选分类，产品属性区域出现 |
| SKU 表格输入 | `.ant-table`, `.skuData-body`, `table.myj-table` | SKU、售价、原价、长宽高、重量 | 结合表头和行上下文定位 input；写入后触发行级 change/blur | 对应行的单元格值更新 |
| 库存编辑弹窗 | SKU 库存单元格的编辑图标 + modal | 仓库库存/总库存 | 点击库存编辑图标，弹窗内填库存，点 `应用` / `确定` | 表格库存列更新 |
| 变种颜色控件 | `.sku-checkbox`, `.sku-checkbox-panel`, `input[name=skuMutiSelect]` | 商品颜色 `Цвет товара` | 打开面板，搜索标准色，点击候选；不要直接写文本 | 颜色标签/选中项出现在 SKU 行 |
| 变种图片组件 | 变种图片区域、上传/图片空间/排序控件 | 每个变种的图片 | 优先通过扩展辅助复制/选择图片 URL；自动上传需单独能力 | 每个变种下出现目标图片缩略图 |

## DXM 组件分类树

sERP 自动填充里的 DXM 组件分类分两层，不要混用。

第一层是页面控件分类，由 `collectFormFields()` 扫描 DOM 后交给 `dxmControlKindFromField()` 归类，结果写入 `form_fields[].controlKind`，主要回答“页面上这个东西怎么填”。

```text
页面控件 controlKind
├─ 文本/数值
│  ├─ input-text
│  ├─ input-number
│  ├─ textarea
│  ├─ contenteditable
│  └─ json-editor
├─ 原生控件
│  ├─ native-select
│  ├─ single-checkbox
│  └─ single-radio
├─ Ant Select
│  ├─ ant-select-single
│  ├─ ant-select-search
│  ├─ ant-select-multiple
│  └─ ant-select-multiple-search
├─ 分组选项
│  ├─ checkbox-group
│  └─ radio-group
└─ unknown
```

第二层是 DXM runtime 属性分类，由 `dxm_runtime_bridge.js` 从店小秘页面内 Vue/Pinia store 读取 `attrsInfo.attrsList`、`mergeAttrsList`、`skuList`，再由 `inferDxmControlKindFromMeta()` 根据 `dictionaryId`、`collection/maxValueCount`、`_remoteSearch/_searchFlag`、`type` 推断，结果写入 `field.dxmAttribute.dxmControlKind`，主要回答“这个属性是不是字典、候选值从哪里来、应该写到哪个 DXM 数据模型”。

```text
DXM runtime dxmControlKind
├─ text-input
├─ number-input
├─ dictionary-single
├─ dictionary-single-remote
├─ dictionary-multiple
├─ dictionary-multiple-remote
└─ unknown
```

关键规则:

- `controlKind` 决定填充器入口，例如文本输入、textarea、checkbox 组、Ant Select。
- `dxmAttribute.dxmControlKind` 决定字段语义和候选来源，例如字典字段、远程字典、多值字典。
- 只要 `dxmAttribute.dictionaryId` 非空且不是 `0`，就视为 DXM 字典字段，优先走 `fillDxmDictionaryField()`。
- DXM 字典字段不再用鼠标点击 Ant Select 作为主路径；应使用 DXM runtime 候选值和 `attributeId` 回填 store。
- `fillAntSelect()` 只保留给非 DXM 字典控件和少量特殊流程，例如变种主题选择、搜索型 checkbox 添加候选。

## DXM Runtime 回填模型

店小秘编辑已创建商品时，会先把属性值加载到页面 runtime store，再由 Vue 组件渲染 UI。sERP 自动填充字典字段时应复用这个模型，而不是模拟鼠标打开下拉框。

当前字典回填路径:

1. `dxm_runtime_bridge.js` 在页面上下文读取 DXM runtime 字段模型。
2. `compactDxmAttrMeta()` 保留 `attributeId`、`dictionaryId`、`sourceGroup`、`collection`、`maxValueCount`、`options` 等字段。
3. `compactDxmOptions()` 从 `_allOptions`、`_options`、`options` 中提取候选值，统一成 `{ id, value, valueCn, valueEn }`。
4. `_fieldForLLM()` 把 `dxmAttribute` 和候选值发给 LLM。
5. LLM 返回 `value`，字典字段可同时返回 `dictionary_value_id`。
6. `fillDxmDictionaryField()` 优先按 `dictionary_value_id` 匹配候选；没有 ID 时按 `value/valueCn/valueEn` 归一化匹配。
7. 命中后写入 DXM store:

```json
{
  "complex_id": 0,
  "id": "4389",
  "attribute_id": "4389",
  "values": [
    {
      "dictionary_value_id": 90296,
      "value": "Китай"
    }
  ]
}
```

写入位置由 `sourceGroup` 决定:

| `sourceGroup` | 店小秘 store | 写入字段 |
|---|---|---|
| `attrsList` | `ozonProductBasicStore.$state.formState` | `productAttrsData` |
| `mergeAttrsList` | `ozonProductStore.$state.formState` | `mergeAttrsData` |
| `skuList` | 暂按字段实际 DOM/后续 SKU 专用逻辑处理 | 不要猜，先诊断 |

写入后调用 Vue 组件链上的 `emit("update:value")`、`emit("change")`、`emit("select")`，并对字段 DOM 触发 `input/change`，让店小秘组件自己刷新显示。

## 填写注意事项

- 对 DXM 字典字段，LLM 返回值不在 `dxmAttribute.options` 里时，不填、不点击下拉，只显示“DXM候选不包含该值”或“DXM候选未加载”。
- 对产品属性区的 DXM 字典字段，禁止回退到鼠标点击 Ant Select，否则会再次出现“暂无数据”下拉和错误选项。
- 远程字典字段如果 runtime 没有加载目标候选，第一版先失败并留证；后续应接 DXM 自己的搜索接口，不要改用 Ozon 官方 API 字典硬塞。
- 品牌、VAT、店铺、分类这类非产品属性固定控件可能仍是普通 Ant Select，不能简单套用产品属性字典回填。
- 变种主题选择、SKU 颜色面板、库存编辑弹窗是特殊流程，不属于普通产品属性字典字段。
- 新增组件时先判断是 DOM 控件识别问题，还是 DXM runtime 候选缺失问题；前者改 `collectFormFields()` / `dxmControlKindFromField()`，后者改 runtime bridge 或 DXM 搜索接口。

## 未知组件处理

扩展版本 `3.2.43` 起，字段扫描阶段会自动记录未知 DXM 控件。未知控件的定义是：页面中存在可输入/可选择组件，但没有被 `collectFormFields()` 纳入字段模型。

这类诊断用于处理店小秘页面结构变化、新品类属性、新平台特殊控件。触发后扩展会:

- 弹窗提示发现未知 DXM 控件。
- 保存平台、店铺、URL、分类路径和 DXM runtime 分类上下文。
- 保存未知控件的可见文本、HTML 片段和基础特征。

保存位置:

```text
chrome.storage.local.serp_unknown_dxm_controls
```

复现和适配原则:

- 先按诊断记录里的 `platform`、`store_id`、`category_path`、`description_category_id`、`type_id` 复现页面。
- 如果未知控件只是现有组件的 DOM 变体，优先增强现有 `controlKind` 识别。
- 如果是全新交互模型，再新增控件类型，并记录它调用的店小秘 runtime 数据结构或事件链。
- 适配前不要让 LLM 自由猜控件语义；应先让程序能稳定识别字段边界和候选值来源。

## 自动填充顺序

推荐顺序:

1. 选择店铺。
2. 选择 Ozon 产品分类。
3. 等待动态属性区渲染完成。
4. 采集当前页面字段 schema。
5. 创建/补齐变种行。
6. 程序先填确定性字段: 重量、尺寸、售价、原价、库存、产地、SKU。
7. AI 填语义字段: 标题、描述、品牌、材质、功能、Rich Content、Hashtag、分类属性。
8. 二次校验: 必填项、下拉值命中、checkbox/radio 是否误选、SKU 行是否同步、JSON 是否有效。

不要在 `店铺` 和 `分类` 之前采集完整字段，否则只能拿到初始页面的少量控件。

## 字段采集规则

扩展应优先按 `.ant-form-item` 或等价容器采集标签和控件。表格内字段必须附加行上下文，避免多行同名字段混淆。

字段对象建议包含:

- `index`: 当前采集批次内的稳定序号。
- `label`: 清洗后的字段名，包含中文/俄文和必要行上下文。
- `controlKind`: 归一化组件类型，例如 `input-text`、`ant-select-search`。
- `options`: 有限选项列表，包含选项文本和值。
- `currentValue`: 当前值。
- `selector` / `_fid`: 运行期定位句柄。
- `rowContext`: SKU 表格行名、变体名或首列内容。

不要把下拉面板、隐藏菜单、顶部导航、浏览器插件浮层采集进业务字段。

## Ant Select 填写细节

Ant Select 是页面里最重要也最容易失败的组件。

普通单选:

1. 点击 `.ant-select-selector`。
2. 等待 `.ant-select-dropdown:not(.ant-select-dropdown-hidden)`。
3. 收集 `.ant-select-item-option` 文本。
4. 用精确匹配、归一化匹配、包含匹配依次尝试。
5. 点击命中 option。

搜索型:

1. 点击选择器。
2. 聚焦 `.ant-select-selection-search-input`。
3. 输入候选词，如品牌 `Bostanten`、材质 `Нейлон`、产地 `Китай`。
4. 触发 `input/change/compositionend/keyup`。
5. 等待远程 option 渲染。
6. 点击最匹配候选。

注意:

- 不要只检查初始 DOM 是否有 option，很多 Ozon 字典值必须搜索后才返回。
- 多选要逐个选择，选完一个后重新检查面板状态。
- 匹配失败时记录可见候选，方便后续补字典映射。

## 文本输入细节

店小秘是 React/Ant Design 页面，只写 `el.value = value` 经常不会触发内部状态更新。

可靠流程:

1. `focus()`
2. `select()` 或 `document.execCommand("selectAll")`
3. `document.execCommand("insertText", false, value)`
4. fallback 到原生 setter
5. 触发 `input`、`change`、`keyup`、`blur`

SKU 行里的颜色名称、价格和尺寸字段尤其需要触发行级事件，否则下方或旁边联动区域可能不同步。

## Checkbox / Radio 细节

多选和单选必须按 form-item 分组。不能把所有 checkbox 当成独立字段，否则 AI 会无法理解选项边界。

匹配策略:

- 先归一化空格、括号、中俄文混排。
- 再做词边界匹配，避免 `3 个卡槽` 误命中 `13 个卡槽`。
- checkbox 多值支持逗号、顿号、竖线分隔。
- 单个 checkbox 只接受明确布尔值或与本字段标签强匹配的文本。

## JSON 富文本

Ozon Rich Content JSON 不是普通描述。它应独立成 `json-editor` 字段。

填写策略:

1. 找到 `编辑JSON代码` 或 JSON 区域按钮。
2. 打开弹窗。
3. 优先使用 CodeMirror 实例 `setValue`。
4. 若没有 CodeMirror，写入 textarea/contenteditable/Monaco inputarea。
5. 触发输入事件。
6. 点击 `确定`、`保存`、`应用` 中的确认按钮。
7. 校验 JSON 可以 `JSON.parse`，并确认弹窗关闭。

禁止把 Rich Content JSON 填进产品描述 textarea。

## 变种和 SKU

变种是 Ozon 页面的特殊区，不完全适合走通用字段映射。

变种主题:

- 多变体商品先选择变种主题，如颜色 `Цвет`。
- 主题选定后才能创建对应 SKU 行。

变种行:

- 根据正式产品变体数补齐行数。
- 对 WALLET-0006 单黑色款，可以只保留/创建 1 行。
- 多变体时按产品数据顺序把每个变体映射到一行。

商品颜色:

- `商品颜色(Цвет товара)` 是有限标准色控件，不能直接写 `Black`。
- 应搜索并选择 Ozon 标准色，例如黑色应命中 `Черный`。

颜色名称:

- `颜色名称(Название цвета)` 是文本字段，可写俄文颜色名或原始变体名。
- 写入后必须触发 input/change/keyup/blur。

SKU 表格:

- 用表头判断列角色: SKU、售价、原价、库存、尺寸、重量。
- 用行上下文判断变体。
- 库存通常不是直接 input，需点击编辑图标打开库存弹窗。

## 图片和媒体

图片区域分两类:

- 产品描述/媒体区: 视频、PDF、Rich Content 图片。
- 变种图片区: 每个 SKU 或变种的主图组。

当前自动填充边界:

- 普通文字 URL 不能等价于上传图片。
- 真实上传需要处理 `<input type=file>`、图片空间弹窗或店小秘上传接口。
- 临时公网 URL 可用于 Rich Content JSON，但变种主图仍要以店小秘页面接受的图片组件方式进入。

扩展可以先提供“变种图”辅助面板，把采集到的图片 URL 按变体分组复制给运营或后续上传模块。

## AI 字段映射边界

适合 AI 判断:

- 标题、描述、卖点文案。
- 品牌规范化。
- 材质、功能、适用人群、风格等语义属性。
- Rich Content JSON 文案和结构。
- Hashtag。

不适合 AI 自由判断:

- 店铺。
- 产品分类 ID / type ID。
- SKU / offer_id。
- 售价、原价、库存。
- 重量、尺寸、产地。
- 字典字段的最终 `dictionary_value_id`。

AI 对有限选项字段只能在程序提供的候选中选择；没有候选时应返回“需要搜索词/无法确定”，由程序触发远程搜索或人工确认。

## WALLET-0006 参考映射

WALLET-0006 Black 已验证的核心目标值:

- 店铺: `Ozon 安凌`
- 分类: `Галантерея и аксессуары > Аксессуары > Кошелек`
- `description_category_id`: `17027904`
- `type_id`: `93338`
- 标题: `Кошелек Bostanten WALLET-0006, черный`
- offer_id / SKU: `WALLET-0006-BLACK`
- 品牌: `Bostanten`
- 颜色: `Черный`
- 重量: `200 g`
- 尺寸: `17.1 x 11.2 x 2.5 cm`
- 售价: `99.00 CNY`
- 产地: `Китай`
- 材质: `Нейлон`
- 闭合方式: `Молния`

这些值可作为扩展端 E2E 验证样本，但不能写死成钱包专用逻辑。正确流程仍然是: 先选类目、拉取候选属性和候选值，再填表。

## 验证清单

每轮自动填充完成后检查:

- 没有触发保存/发布。
- 店铺和分类已选中。
- 分类路径已显示，且字段 schema 是分类展开后重新采集的结果。
- 必填字段不为空。
- Ant Select 显示值与目标值一致。
- 搜索型下拉不是只写了搜索框文本，而是真的选中 option。
- checkbox/radio 没有误选相近项。
- SKU 行数和变体数一致。
- SKU、售价、库存、尺寸、重量在正确行。
- JSON 富文本可解析。
- 图片区域达到预期状态，或明确标记为“待人工/上传模块处理”。
- 控制台记录失败字段和可见候选，方便补充规则。

## 维护建议

- 页面结构变化时，先更新字段采集和 `controlKind` 判断，不要先改 AI prompt。
- 新增组件时先写最小复现页或 live 页面诊断脚本，确认事件触发链。
- 对远程搜索型字典值沉淀“搜索词 -> 命中选项”日志。
- 每次扩展行为变更同步更新 `SERP_EXTENSION_VERSION` 和 `manifest.json` 版本。
- 对真实店小秘页面测试时始终停在填写态，最后一步由人工决定是否保存或发布。
