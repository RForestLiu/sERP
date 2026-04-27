# sERP — 跨境电商运营工具套件

> AI 图像批量处理 + 电商产品采集 + Ozon 品类管理 + 自动上架
>
> 基于 Flask + DeepSeek/Gemini API

---

## 功能模块

### 📷 图片批量处理
- ✅ **任务管理** — 创建、切换、重命名、删除任务
- ✅ **批量上传** — 拖拽或点击上传多张图片
- ✅ **JSON 导入** — 批量导入 Prompt 配置
- ✅ **AI 生图** — 调用 Gemini API 批量生成产品图
- ✅ **图片压缩** — 自动/手动压缩到 1.5MB 以下
- ✅ **数据持久化** — 每个任务独立文件夹 + JSON

### 📦 电商产品采集
- ✅ **多平台支持** — Ozon、Wildberries、Amazon、Yandex
- ✅ **Playwright + requests 双引擎** — 静态/动态页面自适应
- ✅ **DeepSeek AI 图片分类** — 自动区分主图/SKU图/描述图
- ✅ **异步并发下载** — 自动转 JPG，压缩优化
- ✅ **SKC/SKU 自动生成** — 采集数据一键转正式产品

### 🏪 Ozon 品类管理
- ✅ **品类树拉取与缓存** — 全量 7998 个品类带本地缓存
- ✅ **俄→中批量翻译** — DeepSeek 分批翻译，缓存复用
- ✅ **AI 品类匹配** — 根据产品信息自动匹配 Ozon 品类
- ✅ **品类属性获取** — 叶子节点属性 + 字典值加载
- ⏳ **品类刷新翻译** — 异步后台分批翻译（待验证）

### 📝 Ozon 上架
- ✅ **属性自动填充** — DeepSeek 分析产品数据后填充属性
- ✅ **上架草稿持久化** — 每个产品×店铺独立 JSON 存储
- ✅ **店小秘自动填充** — 油猴脚本 + API 联动

---

## 项目结构

```
sERP/
├── main.py                  # ★ 项目唯一入口
├── app.py                   # Flask 后端（所有 API 逻辑）
├── collector.py             # 产品采集引擎
├── requirements.txt         # Python 依赖
├── .env                     # 环境变量（API Key 等）
│
├── templates/
│   ├── index.html           # 主页面（图片处理+采集+产品管理）
│   └── ozon_listing.html    # Ozon 上架页面
│
├── data/                    # 数据存储（自动创建）
│   ├── products.json        # 正式产品数据
│   ├── stores.json          # 店铺列表及 Ozon 凭证
│   ├── tasks.json           # 图片处理任务列表
│   ├── collect_tasks.json   # 采集任务持久化
│   ├── ozon_cache/          # Ozon 品类树/翻译缓存
│   └── task_*/collect_*/    # 任务数据目录
│
├── docs/
│   ├── 交接文档.md           # 项目交接文档
│   ├── 需求文档.md           # 详细需求文档
│   ├── SKC-SKU规范.md        # 编码规范
│   └── Ozon_Seller_API知识库.md  # Ozon API 参考
│
├── reference/               # 第三方页面参考
├── scripts/                 # 浏览器油猴脚本
└── test_images/             # 测试图片
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
# 关键依赖: Flask, requests, aiohttp, Pillow, BeautifulSoup4, python-dotenv
# Playwright（可选，采集动态页面需要）:
pip install playwright
playwright install chromium
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 API Key
```

### 3. 启动服务

```bash
python main.py
# 访问 http://localhost:5000
```

---

## API 接口概览

| 模块 | 方法 | 路由 | 功能 |
|------|------|------|------|
| 图片 | `GET/POST/PUT` | `/api/tasks/*` | 任务 CRUD + 图片生成/压缩 |
| 采集 | `POST` | `/api/collect` | 启动产品采集 |
| 采集 | `GET` | `/api/collect/<id>/status` | 查询采集进度 |
| 采集 | `GET` | `/api/collect/<id>/result` | 获取采集结果 |
| 产品 | `GET/PUT` | `/api/products/*` | 产品管理 |
| Ozon | `GET` | `/api/ozon/<id>/category-tree` | 品类树 |
| Ozon | `POST` | `/api/ozon/<id>/match-category` | AI 品类匹配 |
| Ozon | `POST` | `/api/ozon/<id>/category-attributes` | 品类属性 |
| Ozon | `POST` | `/api/ozon/<id>/translate-categories` | 品类翻译 |
| 上架 | `GET/PUT/DELETE` | `/api/listings/<skc>/<store>` | 上架草稿 |
| 填充 | `POST` | `/api/auto-fill/analyze` | 店小秘填充分析 |
| 填充 | `POST` | `/api/auto-fill/ozon-fields` | Ozon 属性填充 |

---

## 技术栈

- **后端**: Python 3.10+ / Flask
- **前端**: 原生 HTML/CSS/JavaScript
- **AI API**: DeepSeek (品类翻译/匹配/填充) + Gemini (图片生成)
- **采集**: Playwright / requests + BeautifulSoup
- **图片处理**: Pillow
- **存储**: JSON 文件持久化
- **并发**: aiohttp + asyncio

---

## 日志系统

所有模块统一使用 Python `logging` 模块，格式：

```
HH:MM:SS | INFO | app | 消息内容
HH:MM:SS | WARN | collector | 警告内容
HH:MM:SS | ERROR | app | 错误内容
```

- **开发模式**：`python main.py`（默认 DEBUG 级别）
- **生产模式**：修改 `main.py` 中的 `level=logging.INFO`

---

## 更新日志

### v1.3.0 (2026-04-27)
- ✨ 新增 `main.py` 统一入口，规范日志系统
- ✨ `app.py` / `collector.py` 所有 `print()` 改为 `logger`
- ✨ 更新交接文档，补充模块架构和日志说明
- 🔧 修复 `collector.py` 文件结构损坏问题

### v1.2.0 (2026-04-25)
- ✨ Ozon 品类树缓存 + 逐批翻译
- ✨ AI 品类匹配（全量发送，修复截断问题）
- ✨ 品类属性 + 字典值加载
- ✨ 上架草稿持久化 API
- ✨ 店小秘自动填充 API

### v1.1.0 (2026-04-25)
- ✨ 新增左侧导航栏，支持多模块切换
- ✨ 新增"采集产品"模块
- ✨ 新增"产品管理"模块

### v1.0.0 (2026-04-24)
- 初始版本：图片批量处理工作台
