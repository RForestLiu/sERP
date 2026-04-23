# sERP - AI 图像批量处理工具

> 基于 Flask + OpenAI API 的图像批量生成/编辑工具

---

## 功能特性

- ✅ **任务管理** - 创建、切换、重命名、删除任务
- ✅ **批量上传** - 拖拽或点击上传多张图片
- ✅ **JSON 导入** - 批量导入 Prompt 配置
- ✅ **图片生成** - 调用 AI API 生成图片
- ✅ **数据持久化** - 每个任务独立 JSON 文件存储
- ✅ **实时保存** - 操作自动保存，刷新不丢失

---

## 项目结构

```
sERP/
├── app.py              # Flask 后端主文件
├── .env                # 环境变量（API Key 等）
├── .env.example        # 环境变量示例
├── README.md           # 项目说明
├── templates/
│   └── index.html      # 前端页面
├── tasks/              # 任务数据存储（自动创建）
├── uploads/            # 上传图片存储（自动创建）
└── outputs/            # 生成图片存储（自动创建）
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install flask flask-cors openai python-dotenv requests
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

### 新建任务
点击左侧边栏的 **"+ New Task"** 按钮

### 批量上传图片
将多张图片拖拽到右上角的 **"Batch Drop Images"** 区域

### 导入 Prompt
在 JSON 输入框中粘贴配置，点击 **"Split Prompts"**：
```json
[
  {"image_name": "product1.jpg", "prompt": "生成一个红色钱包的产品图"},
  {"image_name": "product2.jpg", "prompt": "生成一个蓝色钱包的产品图"}
]
```

### 生成图片
点击卡片上的 **"Generate"** 按钮生成图片

---

## API 接口

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/tasks` | 获取任务列表 |
| POST | `/api/tasks` | 创建任务 |
| GET | `/api/tasks/<id>` | 获取任务详情 |
| PATCH | `/api/tasks/<id>` | 更新任务 |
| DELETE | `/api/tasks/<id>` | 删除任务 |
| POST | `/api/upload` | 上传图片 |
| POST | `/api/generate` | 生成图片 |

---

## 技术栈

- **后端**: Python 3.10+ / Flask
- **前端**: 原生 HTML/CSS/JavaScript
- **AI API**: OpenAI / 通义系列（兼容 OpenAI 接口）
- **存储**: JSON 文件持久化

---

## 更新日志

### v1.0.0 (2026-04-24)
- 初始版本
- 支持任务管理、批量上传、图片生成
- 实现数据持久化（每任务独立 JSON 文件）
