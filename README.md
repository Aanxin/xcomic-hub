# XComic Hub

一个简洁高效的自托管漫画库管理系统，支持漫画管理、在线阅读、下载、采集和标签翻译。

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![Docker](https://img.shields.io/badge/Docker-anxina%2Fxcomic--hub-blue.svg)

## 功能特性

### 核心功能
- **多格式支持** - 支持 CBZ、CBR、ZIP、RAR、7Z、PDF 等常见漫画压缩格式
- **在线阅读** - 内置漫画阅读器，支持多种阅读模式
- **合集管理** - 将多本漫画组织成合集/系列
- **标签系统** - 支持标签分类、自动翻译（英文→中文）
- **收藏与历史** - 收藏喜欢的漫画，记录阅读进度

### 采集功能
- **网页采集** - 支持 E-Hentai、Nhentai 等网站的信息自动采集
- **种子下载** - 集成 qBittorrent，支持磁力链接和种子文件下载
- **批量导入** - 支持文件夹批量导入漫画

### 系统特性
- **RESTful API** - 提供完整的 API 接口，支持客户端集成
- **设备认证** - 设备令牌认证，安卓/iOS 客户端即插即用
- **Docker 部署** - 一键部署，开箱即用
- **响应式 UI** - 深色主题，适配桌面和移动端

## 系统要求

- Python 3.10+
- Windows / Linux / macOS
- Docker (可选)

## 快速开始

### 方式一：直接运行

```bash
# 克隆项目
git clone https://github.com/Aanxin/xcomic-hub.git
cd xcomic-hub

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或 .\.venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 运行应用
python run.py
```

访问 `http://localhost:8724`

### 方式二：Docker 部署

```bash
# 拉取镜像并启动
docker run -d \
  --name xcomic-hub \
  -p 8724:8724 \
  -v xcomic-data:/app/data \
  -v xcomic-downloads:/download \
  -e SECRET_KEY=your-secret-key \
  -e DOWNLOAD_DIR=/download \
  --restart unless-stopped \
  anxina/xcomic-hub
```

访问 `http://localhost:8724`

### 方式三：Docker Compose

```yaml
services:
  xcomic:
    image: anxina/xcomic-hub
    container_name: xcomic-hub
    ports:
      - "8724:8724"
    volumes:
      - xcomic-data:/app/data
      - xcomic-downloads:/download
    environment:
      - SECRET_KEY=change-this-to-a-random-secret
      - DOWNLOAD_DIR=/download
    restart: unless-stopped

volumes:
  xcomic-data:
  xcomic-downloads:
```

## 目录结构

```
xcomic-hub/
├── app/
│   ├── api/            # API 接口
│   ├── clients/        # 第三方客户端适配
│   ├── scrapers/       # 网页采集器
│   ├── services/       # 业务逻辑服务
│   ├── templates/      # 网页模板
│   ├── utils/          # 工具函数
│   ├── models.py       # 数据模型
│   ├── reader.py       # 阅读器核心
│   └── routes.py       # 页面路由
├── data/               # 本地数据存储目录
│   ├── comics/         # 漫画文件
│   ├── covers/         # 封面图片
│   ├── nfo/            # NFO 元数据
│   └── pages/          # 漫画页面缓存
├── config.py           # 配置文件
├── run.py              # 启动入口
├── requirements.txt    # Python 依赖
├── Dockerfile          # Docker 配置
└── docker-compose.yml  # Docker Compose 配置
```

## Docker 存储说明

| 容器路径 | 说明 | 宿主机建议挂载 |
|----------|------|----------------|
| `/app/data` | 数据库、封面、NFO 等数据 | `xcomic-data:/app/data` |
| `/download` | 下载任务目录（种子/磁力下载） | `xcomic-downloads:/download` |

## 配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `SECRET_KEY` | manhua-dev-secret-key | Flask 密钥（生产环境请修改） |
| `DOWNLOAD_DIR` | /download | 下载任务目录 |
| `DATA_DIR` | /app/data | 数据存储目录 |
| `COMICS_DIR` | /app/data/comics | 漫画文件目录 |
| `DB_PATH` | /app/data/manhua.db | 数据库路径 |
| `FLASK_ENV` | production | 运行环境 |

### 代理设置

在设置页面配置：
- 支持 HTTP/HTTPS/SOCKS5 代理
- 支持代理认证
- 可测试连接状态

### qBittorrent 集成

1. 在设置页面填写 qBittorrent 连接信息
2. 启用后可通过采集接口自动添加下载任务

## API 文档

完整 API 文档请参考 [API_DOC.md](API_DOC.md)

### 认证方式

系统使用设备令牌认证，客户端连接流程：

```bash
# 1. 设备连接（任何设备均可直接连接）
POST /api/v1/auth/connect
{
    "device_id": "your-device-id",
    "device_name": "My Phone",
    "device_type": "android"
}

# 2. 获取响应中的 access_token
# 3. 后续请求携带令牌
Authorization: Bearer <access_token>
```

### 主要接口

| 模块 | 说明 |
|------|------|
| `/api/v1/comics` | 漫画管理（列表、详情、CRUD） |
| `/api/v1/collections` | 合集管理 |
| `/api/v1/uploads` | 文件上传（支持分片、断点续传） |
| `/api/v1/downloads` | 下载任务管理 |
| `/api/v1/scraper` | 采集接口 |
| `/api/v1/tags` | 标签管理 |
| `/api/v1/history` | 阅读历史 |
| `/api/v1/settings` | 系统设置 |

## 标签映射

系统支持将英文标签自动翻译为中文显示：

```json
{
    "big breasts": "巨乳",
    "parody:original work": "戏仿:原创",
    "sole female": "单女"
}
```

可在设置页面管理映射规则。

## 数据导入

### 支持格式

| 格式 | 说明 |
|------|------|
| `.cbz` | ZIP 压缩漫画 |
| `.cbr` | RAR 压缩漫画 |
| `.zip` | 标准 ZIP 压缩包 |
| `.rar` | RAR 压缩包 |
| `.7z` | 7-Zip 压缩包 |
| `.pdf` | PDF 文档 |
| 文件夹 | 包含图片的文件夹 |

### NFO 支持

支持导入 Kobo 格式 NFO 元数据文件，自动提取：
- 标题、作者、简介
- 标签、分类
- 评分、出版日期

## 常见问题

### Q: 如何上传漫画？

1. **网页上传** - 点击「上传漫画」按钮，选择文件上传
2. **API 上传** - 使用分片上传接口，支持大文件

### Q: 如何采集漫画信息？

1. 访问设置页面，配置代理（如果需要）
2. 在下载页面输入 E-Hentai/Nhentai 页面 URL
3. 系统自动采集信息并下载种子

### Q: 如何连接安卓客户端？

1. 确保服务器可访问（公网或内网）
2. 在客户端输入服务器地址
3. 应用会自动进行设备认证

## 开发

### 添加新的采集器

```python
# app/scrapers/my_scraper.py
from app.scrapers.base_scraper import BaseScraper

class MyScraper(BaseScraper):
    name = "mysite"
    base_url = "https://example.com"

    def parse_gallery(self, html):
        # 解析画廊页面
        pass

    def get_image_urls(self, html):
        # 获取图片 URL
        pass
```

### 注册采集器

```python
# app/scrapers/scraper_factory.py
from app.scrapers.my_scraper import MyScraper

SCRAPER_REGISTRY = {
    "mysite": MyScraper,
    # ...
}
```

## License

MIT License - 详见 [license.txt](license.txt)
