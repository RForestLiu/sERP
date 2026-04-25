# sERP - AI 图像批量处理工具

> 基于 Flask + AI API 的图像批量生成/编辑工具 + 电商产品数据采集工具

---

## 功能特性

### 图片批量处理模块
- ✅ **任务管理** - 创建、切换、重命名、删除任务
- ✅ **批量上传** - 拖拽或点击上传多张图片
- ✅ **JSON 导入** - 批量导入 Prompt 配置
- ✅ **图片生成** - 调用 AI API 生成图片
- ✅ **数据持久化** - 每个任务独立 JSON 文件存储
- ✅ **实时保存** - 操作自动保存，刷新不丢失
- ✅ **图片压缩** - 自动/手动压缩图片到 1.5MB 以下

### 采集产品模块（开发中）
- 🔄 **多平台支持** - Ozon、Wildberries、Amazon、Yandex
- 🔄 **Crawl4AI 智能抓取** - 自动识别主图、SKU图、描述图
- 🔄 **DeepSeek AI 分类** - 智能分类图片并重命名
- 🔄 **异步并发下载** - 多线程下载 + Pillow 转 JPG
- 🔄 **数据持久化** - 产品数据 JSON + 图片映射表

---

## 项目结构

```
sERP/
├── app.py              # Flask 后端主文件
├── collector.py        # 采集产品模块（开发中）
├── .env                # 环境变量（API Key 等）
├── .env.example        # 环境变量示例
├── README.md           # 项目说明
├── requirements.txt    # Python 依赖
├── templates/
│   └── index.html      # 前端页面（含导航栏 + 多模块）
├── data/               # 数据存储（自动创建）
│   ├── tasks.json      # 图片处理任务列表
│   ├── task_*/         # 图片处理任务数据
│   ├── collect_tasks.json  # 采集任务列表（开发中）
│   └── collect_*/      # 采集任务数据（开发中）
├── docs/
│   └── 需求文档.md     # 详细需求文档
└── test_images/        # 测试图片
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install flask flask-cors openai python-dotenv requests Pillow
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 API Key
```

### 3. 启动服务

```bash
python app.py
```

### 4. 访问页面

打开浏览器访问：`http://127.0.0.1:5000`

---

## 使用说明

### 模块切换
页面左侧导航栏支持模块切换：
- 📦 **采集产品** - 电商产品数据采集
- 📷 **图片批量处理** - AI 图片生成

### 图片批量处理

#### 新建任务
点击左侧边栏的 **"+ 新建任务"** 按钮

#### 批量上传图片
将多张图片拖拽到右上角的 **"拖拽图片到此处"** 区域

#### 导入 Prompt
在 JSON 输入框中粘贴配置，点击 **"拆分提示词"**：
```json
[
  {"image_name": "product1.jpg", "prompt": "生成一个红色钱包的产品图"},
  {"image_name": "product2.jpg", "prompt": "生成一个蓝色钱包的产品图"}
]
```

#### 生成图片
点击卡片上的 **"执行生图"** 按钮生成图片

#### 图片压缩
- **自动压缩**（默认开启）：勾选工具栏的 **"自动压缩"** 复选框后，每次生成图片时自动压缩到 **1.5MB 以下**
- **手动压缩**：点击工具栏的 **"🔽 压缩到1.5MB以下"** 按钮，批量压缩当前任务 `generated/` 目录中所有大于 1.5MB 的图片
- 压缩算法：PNG/WebP 自动转为 JPEG，自适应质量（85→30），仍超标则降分辨率

> ⚠️ **注意事项**
> - 压缩功能依赖 `Pillow` 库，首次使用前请执行 `pip install Pillow`
> - 自动压缩仅在生成图片时生效，对已存在的图片需点击手动压缩按钮
> - 压缩后图片统一转为 `.jpg` 格式（原 PNG/WebP 的透明通道会丢失）
> - 如果图片本身小于 1.5MB，不会进行压缩

---

## API 接口

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/tasks` | 获取任务列表 |
| POST | `/api/tasks` | 创建任务 |
| GET | `/api/tasks/<id>` | 获取任务详情 |
| PUT | `/api/tasks/<id>` | 更新任务 |
| POST | `/api/tasks/<id>/upload_source_images` | 上传源图片 |
| POST | `/api/generate` | 生成图片 |
| POST | `/api/tasks/<id>/save_images` | 保存生成图片 |
| POST | `/api/tasks/<id>/compress_images` | 压缩图片 |
| POST | `/api/tasks/<id>/open_folder` | 打开文件夹 |

---

## 技术栈

- **后端**: Python 3.10+ / Flask
- **前端**: 原生 HTML/CSS/JavaScript
- **AI API**: Gemini / 通义系列（兼容 OpenAI 接口）
- **存储**: JSON 文件持久化
- **采集**: Crawl4AI / BeautifulSoup（开发中）
- **图片处理**: Pillow

---

## 更新日志

### v1.1.0 (2026-04-25)
- ✨ 新增左侧导航栏，支持多模块切换
- ✨ 新增"采集产品"模块（UI 框架）
- ✨ 新增"图片批量处理"模块定义
- 📝 更新项目文档

### v1.0.0 (2026-04-24)
- 初始版本
- 支持任务管理、批量上传、图片生成
- 实现数据持久化（每任务独立 JSON 文件）
