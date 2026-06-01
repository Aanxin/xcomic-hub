# xcomic API 接口文档 v1

> 基础URL: `http://{host}:8724/api/v1`
> 所有接口均返回 JSON 格式数据
> 需要认证的接口需在请求头中携带 `Authorization: Bearer <device_token>`

---

## 目录

1. [通用说明](#1-通用说明)
2. [认证模块（设备标识认证）](#2-认证模块设备标识认证)
3. [漫画模块](#3-漫画模块)
4. [合集模块](#4-合集模块)
5. [文件上传模块](#5-文件上传模块)
6. [下载模块](#6-下载模块)
7. [采集模块](#7-采集模块)
8. [设置模块](#8-设置模块)
9. [阅读历史模块](#9-阅读历史模块)
10. [统计模块](#10-统计模块)
11. [标签模块](#11-标签模块)
12. [封面模块](#12-封面模块)
13. [错误码说明](#13-错误码说明)
14. [附录：安卓端集成指南](#14-附录安卓端集成指南)

---

## 1. 通用说明

### 1.1 响应格式

所有接口统一返回以下 JSON 格式：

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| code | int | 状态码，0 表示成功，非0表示错误 |
| message | string | 响应消息 |
| data | object/array/null | 响应数据，错误时可能不存在 |

### 1.2 分页格式

分页接口的 data 字段格式：

```json
{
  "items": [],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 100,
    "pages": 5,
    "has_prev": false,
    "has_next": true
  }
}
```

### 1.3 认证方式

本系统采用**基于设备标识的连接机制**，无需登录、无需验证：

- 客户端发送唯一的 `device_id` 即可直接连接，所有设备均自动通过
- 无需用户名/密码，无需审批流程，无需验证IP地址
- 连接后在请求头中携带设备 Token：

```
Authorization: Bearer <device_token>
```

- 设备 Token 有效期：30天
- 任何设备均可直接连接，无限制

**认证级别说明**：

| 标注 | 含义 |
|------|------|
| 无需认证 | 任何客户端均可直接访问 |
| 可选设备认证 | 不带Token可访问，带Token可获取额外数据（如阅读历史） |
| 需要设备认证 | 必须携带有效的设备Token才能访问 |

### 1.4 安卓端优化建议

- 所有列表接口支持分页，建议每页 20 条
- 分片上传支持断点续传，网络中断后可恢复
- 图片接口支持直接加载（返回图片二进制流）
- 建议使用 OkHttp/Retrofit 的拦截器统一添加设备 Token
- 安卓端使用 `Settings.Secure.ANDROID_ID` 作为 device_id
- 建议在应用启动时调用 `/auth/connect` 自动连接
- Token过期时自动调用 `/auth/reconnect` 或 `/auth/connect` 重新获取

---

## 2. 认证模块（设备连接）

> 所有设备均可直接连接，无需审批、无需验证IP。客户端仅需提供唯一设备标识即可获取Token。

### 2.1 设备连接

- **接口名称**: 设备连接（核心接口）
- **请求URL**: `POST /auth/connect`
- **认证级别**: 无需认证
- **说明**: 任何设备均可直接连接，自动获取Token，无审批流程

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| device_id | string | 是 | 设备唯一标识（1-128字符），建议使用ANDROID_ID |
| device_name | string | 否 | 设备名称，如"Pixel 8 Pro" |
| device_type | string | 否 | 设备类型，如"android"、"ios" |

**请求示例**:

```json
{
  "device_id": "a1b2c3d4e5f6",
  "device_name": "Pixel 8 Pro",
  "device_type": "android"
}
```

**响应示例（首次连接）**:

```json
{
  "code": 0,
  "message": "设备注册并连接成功",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "Bearer",
    "expires_in": 2592000,
    "device_id": "a1b2c3d4e5f6",
    "device_name": "Pixel 8 Pro",
    "is_new_device": true,
    "tag_mapping": [
      { "original": "big breasts", "display": "巨乳" },
      { "original": "sole female", "display": "单女" },
      { "original": "parody:original work", "display": "戏仿:原创" }
    ],
    "tag_mapping_version": "3"
  }
}
```

**响应示例（再次连接）**:

```json
{
  "code": 0,
  "message": "设备连接成功",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "Bearer",
    "expires_in": 2592000,
    "device_id": "a1b2c3d4e5f6",
    "device_name": "Pixel 8 Pro",
    "is_new_device": false,
    "tag_mapping": [
      { "original": "big breasts", "display": "巨乳" },
      { "original": "sole female", "display": "单女" },
      { "original": "parody:original work", "display": "戏仿:原创" }
    ],
    "tag_mapping_version": "3"
  }
}
```

> **同步说明**：每次设备连接时，服务器会返回完整的 `tag_mapping` 数组和 `tag_mapping_version` 版本号。安卓端应将映射保存到本地（如 Room/SharedPreferences），并在本地记录 `tag_mapping_version`。当 `tag_mapping_version` 与本地不一致时，用服务器返回的数据替换本地映射。

### 2.2 重新连接

- **接口名称**: 使用已有Token重新连接
- **请求URL**: `POST /auth/reconnect`
- **认证级别**: 需要设备认证（携带旧Token）
- **说明**: Token即将过期时使用旧Token获取新Token

**响应示例**:

```json
{
  "code": 0,
  "message": "重新连接成功",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "Bearer",
    "expires_in": 2592000,
    "device_id": "a1b2c3d4e5f6",
    "device_name": "Pixel 8 Pro",
    "tag_mapping": [
      { "original": "big breasts", "display": "巨乳" },
      { "original": "sole female", "display": "单女" },
      { "original": "parody:original work", "display": "戏仿:原创" }
    ],
    "tag_mapping_version": "3"
  }
}
```

### 2.3 获取同步数据

- **接口名称**: 获取标签映射同步数据
- **请求URL**: `GET /auth/sync`
- **认证级别**: 无需认证
- **说明**: 安卓端可随时调用此接口获取最新的标签映射数据，用于增量同步

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "tag_mapping": [
      { "original": "big breasts", "display": "巨乳" },
      { "original": "sole female", "display": "单女" },
      { "original": "parody:original work", "display": "戏仿:原创" }
    ],
    "tag_mapping_version": "3"
  }
}
```

### 2.4 获取连接状态

- **接口名称**: 获取系统连接状态
- **请求URL**: `GET /auth/status`
- **认证级别**: 无需认证

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "total_devices": 3
  }
}
```

### 2.5 验证设备

- **接口名称**: 检查设备是否已注册
- **请求URL**: `POST /auth/verify-device`
- **认证级别**: 无需认证
- **说明**: 用于应用启动时检查设备状态

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| device_id | string | 是 | 设备标识 |

**响应示例（已注册）**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "registered": true,
    "device_name": "Pixel 8 Pro",
    "last_active_at": "2024-01-15T12:00:00"
  }
}
```

**响应示例（未注册）**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "registered": false
  }
}
```

### 2.6 获取设备列表

- **接口名称**: 获取所有已注册设备
- **请求URL**: `GET /auth/devices`
- **认证级别**: 需要设备认证

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": [
    {
      "id": 1,
      "device_id": "a1b2c3d4e5f6",
      "device_name": "Pixel 8 Pro",
      "device_type": "android",
      "connect_count": 15,
      "last_active_at": "2024-01-15T12:00:00",
      "created_at": "2024-01-01T00:00:00"
    }
  ]
}
```

### 2.7 删除设备

- **接口名称**: 删除设备
- **请求URL**: `DELETE /auth/devices/{device_db_id}`
- **认证级别**: 需要设备认证
- **说明**: 不能删除当前使用的设备

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| device_db_id | int | 是 | 设备数据库ID |

**响应示例**:

```json
{
  "code": 0,
  "message": "设备已删除"
}
```

### 2.8 更新设备信息

- **接口名称**: 更新设备名称
- **请求URL**: `PUT /auth/devices/{device_db_id}`
- **认证级别**: 需要设备认证

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| device_db_id | int | 是 | 设备数据库ID |

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| device_name | string | 否 | 新设备名称 |

**请求示例**:

```json
{
  "device_name": "我的 Pixel 8 Pro"
}
```

**响应示例**:

```json
{
  "code": 0,
  "message": "设备信息已更新",
  "data": {
    "id": 1,
    "device_id": "a1b2c3d4e5f6",
    "device_name": "我的 Pixel 8 Pro",
    ...
  }
}
```

---

## 3. 漫画模块

### 3.1 获取漫画列表

- **接口名称**: 获取漫画列表（分页）
- **请求URL**: `GET /comics`
- **认证级别**: 可选设备认证（带Token可获取阅读历史）

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| page | int | 否 | 页码，默认1 |
| per_page | int | 否 | 每页数量，默认20，最大100 |
| search | string | 否 | 搜索关键词，支持前缀搜索 |
| sort | string | 否 | 排序方式：updated/created/title/rating/size，默认updated |
| filter | string | 否 | 筛选条件：favorite/standalone |
| collection_id | int | 否 | 按合集ID筛选 |

**搜索语法**:
- 普通关键词：搜索标题、作者、标签
- `author:xxx` - 按作者搜索
- `genre:xxx` - 按类型搜索
- `tag:xxx` - 按标签搜索
- `category:xxx` - 按分类搜索
- `publisher:xxx` - 按出版商搜索
- `language:xxx` - 按语言搜索

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "items": [
      {
        "id": 1,
        "title": "漫画标题",
        "title_jp": "日本語タイトル",
        "author": "作者名",
        "genre": "类型",
        "category": "分类",
        "date": "2024-01-01",
        "plot": "简介",
        "rating": 4.5,
        "rating_count": 100,
        "tags": "标签1,标签2,戏仿:xxx",
        "raw_tags": "tag1,tag2,parody:xxx",
        "status": "已完成",
        "publisher": "出版社",
        "language": "中文",
        "is_translated": true,
        "uploader": "上传者",
        "page_count": 24,
        "favorited": 50,
        "source_url": "https://...",
        "torrent_urls": "",
        "cover": "subdir/cover.jpg",
        "filename": "subdir/comic.zip",
        "nfo_file": "subdir/comic.nfo",
        "file_size": 10485760,
        "collection_id": 1,
        "volume": "第1卷",
        "is_favorite": false,
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
        "reading_history": {
          "comic_id": 1,
          "last_page": 10,
          "total_pages": 24,
          "read_count": 3,
          "last_read_at": "2024-01-15T12:00:00"
        }
      }
    ],
    "pagination": {
      "page": 1,
      "per_page": 20,
      "total": 100,
      "pages": 5,
      "has_prev": false,
      "has_next": true
    }
  }
}
```

> **tags 字段说明**：所有漫画接口返回的 `tags` 字段为映射后的显示名（中文），`raw_tags` 为原始英文标签。安卓端显示标签时使用 `tags`，搜索/写入时使用 `raw_tags`。

### 3.2 获取随机漫画

- **接口名称**: 获取随机漫画
- **请求URL**: `GET /comics/random`
- **认证级别**: 可选设备认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| count | int | 否 | 数量，默认10，最大50 |

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": [
    { "id": 1, "title": "漫画A", ... },
    { "id": 2, "title": "漫画B", ... }
  ]
}
```

### 3.3 获取漫画详情

- **接口名称**: 获取漫画详情
- **请求URL**: `GET /comics/{comic_id}`
- **认证级别**: 可选设备认证

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| comic_id | int | 是 | 漫画ID |

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "id": 1,
    "title": "漫画标题",
    "readable": true,
    "reading_history": {
      "comic_id": 1,
      "last_page": 10,
      "total_pages": 24,
      "read_count": 3,
      "last_read_at": "2024-01-15T12:00:00"
    },
    "grouped_tags": {
      "parody": ["xxx"],
      "character": ["yyy"]
    },
    "uncategorized_tags": ["tag1", "tag2"],
    "collection_comics": [
      { "id": 1, "title": "第1卷", ... },
      { "id": 2, "title": "第2卷", ... }
    ],
    ...其他漫画字段
  }
}
```

### 3.4 创建漫画

- **接口名称**: 创建漫画
- **请求URL**: `POST /comics`
- **认证级别**: 无需认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| title | string | 是 | 漫画标题 |
| title_jp | string | 否 | 日文标题 |
| author | string | 否 | 作者 |
| genre | string | 否 | 类型 |
| category | string | 否 | 分类 |
| date | string | 否 | 日期 |
| plot | string | 否 | 简介 |
| rating | float | 否 | 评分 |
| tags | string | 否 | 标签，逗号分隔 |
| status | string | 否 | 状态 |
| publisher | string | 否 | 出版商 |
| language | string | 否 | 语言 |
| is_translated | boolean | 否 | 是否翻译 |
| uploader | string | 否 | 上传者 |
| source_url | string | 否 | 来源URL |
| volume | string | 否 | 卷号 |
| collection_name | string | 否 | 合集名称，不存在则自动创建 |

**请求示例**:

```json
{
  "title": "新漫画标题",
  "author": "作者名",
  "tags": "tag1,tag2,parody:xxx",
  "collection_name": "合集名称",
  "volume": "第1卷"
}
```

**响应示例**:

```json
{
  "code": 0,
  "message": "创建成功",
  "data": { "id": 1, "title": "新漫画标题", ... }
}
```

### 3.5 更新漫画

- **接口名称**: 更新漫画信息
- **请求URL**: `PUT /comics/{comic_id}`
- **认证级别**: 无需认证

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| comic_id | int | 是 | 漫画ID |

**请求参数**: 同创建漫画，所有字段可选

**请求示例**:

```json
{
  "title": "更新后的标题",
  "rating": 4.8,
  "tags": "new_tag1,new_tag2"
}
```

### 3.6 删除漫画

- **接口名称**: 删除漫画
- **请求URL**: `DELETE /comics/{comic_id}`
- **认证级别**: 无需认证

**响应示例**:

```json
{
  "code": 0,
  "message": "删除成功"
}
```

### 3.7 切换收藏

- **接口名称**: 切换漫画收藏状态
- **请求URL**: `POST /comics/{comic_id}/favorite`
- **认证级别**: 无需认证

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": { "is_favorite": true }
}
```

### 3.8 获取漫画页面列表

- **接口名称**: 获取漫画阅读页面
- **请求URL**: `GET /comics/{comic_id}/pages`
- **认证级别**: 无需认证

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "comic_id": 1,
    "pages": ["0001.jpg", "0002.jpg", "0003.jpg"],
    "total_pages": 24,
    "last_page": 10
  }
}
```

### 3.9 获取漫画页面图片

- **接口名称**: 获取漫画单页图片
- **请求URL**: `GET /comics/{comic_id}/page/{page_filename}`
- **认证级别**: 无需认证
- **说明**: 直接返回图片二进制流，安卓端可用 Glide/Coil 直接加载

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| comic_id | int | 是 | 漫画ID |
| page_filename | string | 是 | 页面文件名（从pages接口获取） |

**安卓端使用示例**:

```kotlin
val pageUrl = "${baseUrl}/api/v1/comics/${comicId}/page/${pageFilename}"
Glide.with(context).load(pageUrl).into(imageView)
```

### 3.10 获取阅读进度

- **接口名称**: 获取漫画阅读进度
- **请求URL**: `GET /comics/{comic_id}/progress`
- **认证级别**: 无需认证

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "comic_id": 1,
    "last_page": 10,
    "total_pages": 24,
    "read_count": 3,
    "last_read_at": "2024-01-15T12:00:00"
  }
}
```

### 3.11 更新阅读进度

- **接口名称**: 更新漫画阅读进度
- **请求URL**: `POST /comics/{comic_id}/progress`
- **认证级别**: 无需认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| last_page | int | 否 | 当前页码 |
| total_pages | int | 否 | 总页数 |

**请求示例**:

```json
{
  "last_page": 15,
  "total_pages": 24
}
```

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "comic_id": 1,
    "last_page": 15,
    "total_pages": 24,
    "read_count": 4,
    "last_read_at": "2024-01-16T08:00:00"
  }
}
```

### 3.12 下载漫画文件

- **接口名称**: 下载漫画文件
- **请求URL**: `GET /comics/{comic_id}/download`
- **认证级别**: 无需认证
- **说明**: 返回文件下载流，Content-Disposition为attachment

### 3.13 导出NFO

- **接口名称**: 导出漫画NFO文件
- **请求URL**: `GET /comics/{comic_id}/nfo`
- **认证级别**: 无需认证
- **说明**: 返回XML格式NFO文件

### 3.14 更新漫画封面

- **接口名称**: 上传更新漫画封面
- **请求URL**: `PUT /comics/{comic_id}/cover`
- **认证级别**: 无需认证
- **Content-Type**: `multipart/form-data`

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| cover | file | 是 | 封面图片文件（支持jpg/png/webp） |

**响应示例**:

```json
{
  "code": 0,
  "message": "封面更新成功",
  "data": { "id": 1, "cover": "subdir/new_cover.jpg", ... }
}
```

### 3.15 批量替换标签

- **接口名称**: 批量替换所有漫画中的指定标签
- **请求URL**: `POST /comics/batch/replace-tag`
- **认证级别**: 无需认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| old_tag | string | 是 | 原标签 |
| new_tag | string | 是 | 新标签 |

**请求示例**:

```json
{
  "old_tag": "big breasts",
  "new_tag": "巨乳"
}
```

**响应示例**:

```json
{
  "code": 0,
  "message": "标签替换成功",
  "data": {
    "total_matched": 50,
    "updated_count": 30
  }
}
```

### 3.16 检查标题重复

- **接口名称**: 批量检查标题是否已存在
- **请求URL**: `POST /comics/check-titles`
- **认证级别**: 无需认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| titles | string[] | 是 | 待检查的标题列表 |

**请求示例**:

```json
{
  "titles": ["漫画A", "漫画B", "漫画C"]
}
```

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "found": ["漫画A"],
    "not_found": ["漫画B", "漫画C"]
  }
}
```

---

## 4. 合集模块

### 4.1 获取合集列表

- **接口名称**: 获取合集列表（分页）
- **请求URL**: `GET /collections`
- **认证级别**: 可选设备认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| page | int | 否 | 页码，默认1 |
| per_page | int | 否 | 每页数量，默认20 |
| search | string | 否 | 搜索关键词 |
| sort | string | 否 | 排序：updated/created/name，默认updated |
| filter | string | 否 | 筛选：favorite |

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "items": [
      {
        "id": 1,
        "name": "合集名称",
        "cover": "subdir/cover.jpg",
        "description": "合集描述",
        "nfo_file": "subdir/collection.nfo",
        "is_favorite": false,
        "comic_count": 5,
        "created_at": "2024-01-01T00:00:00"
      }
    ],
    "pagination": { ... }
  }
}
```

### 4.2 获取合集详情

- **接口名称**: 获取合集详情（含漫画列表）
- **请求URL**: `GET /collections/{collection_id}`
- **认证级别**: 可选设备认证

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| collection_id | int | 是 | 合集ID |

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "id": 1,
    "name": "合集名称",
    "comic_count": 5,
    "comics": [
      {
        "id": 1,
        "title": "第1卷",
        "reading_history": { ... },
        ...
      }
    ],
    ...
  }
}
```

### 4.3 创建合集

- **接口名称**: 创建合集
- **请求URL**: `POST /collections`
- **认证级别**: 无需认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | string | 是 | 合集名称（唯一） |
| description | string | 否 | 合集描述 |

**请求示例**:

```json
{
  "name": "新合集",
  "description": "合集描述信息"
}
```

**响应示例**:

```json
{
  "code": 0,
  "message": "创建成功",
  "data": { "id": 1, "name": "新合集", "comic_count": 0, ... }
}
```

### 4.4 更新合集

- **接口名称**: 更新合集信息
- **请求URL**: `PUT /collections/{collection_id}`
- **认证级别**: 无需认证
- **Content-Type**: `application/json` 或 `multipart/form-data`

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| collection_id | int | 是 | 合集ID |

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | string | 否 | 合集名称 |
| description | string | 否 | 合集描述 |
| cover | file | 否 | 封面图片（仅multipart/form-data） |

**响应示例**:

```json
{
  "code": 0,
  "message": "更新成功",
  "data": { "id": 1, "name": "更新后的合集", ... }
}
```

### 4.5 删除合集

- **接口名称**: 删除合集
- **请求URL**: `DELETE /collections/{collection_id}`
- **认证级别**: 无需认证
- **说明**: 仅可删除空合集（不含漫画的合集），合集中有漫画时返回409

**响应示例**:

```json
{
  "code": 0,
  "message": "删除成功"
}
```

### 4.6 切换合集收藏

- **接口名称**: 切换合集收藏状态
- **请求URL**: `POST /collections/{collection_id}/favorite`
- **认证级别**: 无需认证

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": { "is_favorite": true }
}
```

### 4.7 导出合集NFO

- **接口名称**: 导出合集NFO文件
- **请求URL**: `GET /collections/{collection_id}/nfo`
- **认证级别**: 无需认证
- **说明**: 返回XML格式NFO文件

### 4.8 获取合集漫画列表

- **接口名称**: 获取合集中的漫画列表
- **请求URL**: `GET /collections/{collection_id}/comics`
- **认证级别**: 无需认证
- **说明**: 按卷号和ID排序返回合集中的所有漫画

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": [
    {
      "id": 1,
      "title": "第1卷",
      "volume": "1",
      "reading_history": { ... },
      ...
    }
  ]
}
```

---

## 5. 文件上传模块

### 5.1 初始化分片上传

- **接口名称**: 初始化分片上传任务
- **请求URL**: `POST /uploads/init`
- **认证级别**: 无需认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| filename | string | 是 | 文件名（需含扩展名） |
| file_size | int | 是 | 文件大小（字节） |
| chunk_size | int | 否 | 分片大小（字节），默认5MB |
| collection_name | string | 否 | 合集名称 |
| volume | string | 否 | 卷号 |
| nfo_filename | string | 否 | NFO文件名（先通过上传NFO接口获取） |
| cover_filename | string | 否 | 封面文件名（先通过上传封面接口获取） |
| manual_title | string | 否 | 手动指定标题 |
| manual_author | string | 否 | 手动指定作者 |

**请求示例**:

```json
{
  "filename": "comic.zip",
  "file_size": 52428800,
  "collection_name": "合集名",
  "volume": "第1卷"
}
```

**响应示例**:

```json
{
  "code": 0,
  "message": "上传任务已创建",
  "data": {
    "id": "abc123def456",
    "original_filename": "comic.zip",
    "file_size": 52428800,
    "chunk_size": 5242880,
    "total_chunks": 10,
    "uploaded_chunks": [],
    "uploaded_count": 0,
    "status": "pending",
    "comic_id": null,
    "progress": 0
  }
}
```

### 5.2 上传分片

- **接口名称**: 上传单个分片
- **请求URL**: `POST /uploads/chunk`
- **认证级别**: 无需认证
- **Content-Type**: `multipart/form-data`

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| upload_id | string | 是 | 上传任务ID |
| chunk_index | int | 是 | 分片索引（从0开始） |
| chunk | file | 是 | 分片数据 |

**安卓端上传流程**:
1. 调用 `/uploads/init` 获取 upload_id 和 total_chunks
2. 循环上传每个分片：`/uploads/chunk`
3. 所有分片上传完成后调用 `/uploads/complete`
4. 轮询 `/uploads/{upload_id}/status` 查看合并进度

**断点续传**:
- 网络中断后，先调用 `/uploads/{upload_id}/status` 获取已上传的分片列表
- 仅上传 `uploaded_chunks` 中不存在的分片索引

### 5.3 完成上传

- **接口名称**: 完成分片上传，触发合并
- **请求URL**: `POST /uploads/complete`
- **认证级别**: 无需认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| upload_id | string | 是 | 上传任务ID |

**请求示例**:

```json
{
  "upload_id": "abc123def456"
}
```

**响应示例**:

```json
{
  "code": 0,
  "message": "文件正在合并处理中",
  "data": {
    "id": "abc123def456",
    "status": "assembling",
    ...
  }
}
```

### 5.4 取消上传

- **接口名称**: 取消上传任务
- **请求URL**: `POST /uploads/cancel`
- **认证级别**: 无需认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| upload_id | string | 是 | 上传任务ID |

**响应示例**:

```json
{
  "code": 0,
  "message": "上传已取消"
}
```

### 5.5 暂停上传

- **接口名称**: 暂停上传任务
- **请求URL**: `POST /uploads/pause`
- **认证级别**: 无需认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| upload_id | string | 是 | 上传任务ID |

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "id": "abc123def456",
    "status": "paused",
    ...
  }
}
```

### 5.6 查询上传状态

- **接口名称**: 查询上传任务状态
- **请求URL**: `GET /uploads/{upload_id}/status`
- **认证级别**: 无需认证

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| upload_id | string | 是 | 上传任务ID |

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "id": "abc123def456",
    "original_filename": "comic.zip",
    "file_size": 52428800,
    "chunk_size": 5242880,
    "total_chunks": 10,
    "uploaded_chunks": [0, 1, 2, 3, 4],
    "uploaded_count": 5,
    "status": "uploading",
    "comic_id": null,
    "progress": 50
  }
}
```

**status 可能值**:

| 状态 | 说明 |
|------|------|
| pending | 待上传 |
| uploading | 上传中 |
| paused | 已暂停 |
| assembling | 合并中 |
| completed | 已完成 |
| failed | 失败 |
| cancelled | 已取消 |

### 5.7 上传NFO文件

- **接口名称**: 上传NFO元数据文件
- **请求URL**: `POST /uploads/nfo`
- **认证级别**: 无需认证
- **Content-Type**: `multipart/form-data`

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| nfo_file | file | 是 | NFO文件 |

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "nfo_id": "nfo123",
    "nfo_filename": "comic.nfo",
    "original_name": "漫画.nfo"
  }
}
```

### 5.8 上传封面文件

- **接口名称**: 上传封面图片
- **请求URL**: `POST /uploads/cover`
- **认证级别**: 无需认证
- **Content-Type**: `multipart/form-data`

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| cover_file | file | 是 | 封面图片文件 |

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "cover_id": "cover123",
    "cover_filename": "cover.jpg",
    "original_name": "封面.jpg"
  }
}
```

### 5.9 获取上传任务列表

- **接口名称**: 获取所有上传任务
- **请求URL**: `GET /uploads/tasks`
- **认证级别**: 无需认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| status | string | 否 | 按状态筛选 |

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": [
    {
      "id": "abc123def456",
      "original_filename": "comic.zip",
      "status": "completed",
      "progress": 100
    }
  ]
}
```

---

## 6. 下载模块

### 6.1 创建下载任务

- **接口名称**: 通过URL创建下载任务
- **请求URL**: `POST /downloads/start`
- **认证级别**: 无需认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| url | string | 是 | 下载页面URL（需以http://或https://开头） |

**请求示例**:

```json
{
  "url": "https://e-hentai.org/g/12345/abcdef"
}
```

**响应示例**:

```json
{
  "code": 0,
  "message": "下载任务已创建",
  "data": {
    "id": "a1b2c3d4",
    "url": "https://e-hentai.org/g/12345/abcdef",
    "title": "",
    "status": "pending",
    "message": "等待队列中...",
    "torrent_urls": [],
    "torrent_file": "",
    "nfo_path": "",
    "qb_progress": 0.0,
    "qb_state": "",
    "comic_id": null,
    "queue": "waiting",
    "time": "12:00:00"
  }
}
```

### 6.2 上传种子文件

- **接口名称**: 通过种子文件创建下载任务
- **请求URL**: `POST /downloads/torrent`
- **认证级别**: 无需认证
- **Content-Type**: `multipart/form-data`

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| torrent_file | file | 是 | .torrent 文件 |
| url | string | 否 | 来源URL |
| title | string | 否 | 标题 |

**响应示例**:

```json
{
  "code": 0,
  "message": "种子文件已上传",
  "data": {
    "id": "e5f6g7h8",
    "url": "",
    "title": "漫画标题",
    "status": "pending",
    "message": "等待队列中...",
    "torrent_urls": [],
    "torrent_file": "filename.torrent",
    "nfo_path": "",
    "qb_progress": 0.0,
    "qb_state": "",
    "comic_id": null,
    "queue": "waiting",
    "time": "12:00:00"
  }
}
```

### 6.3 获取下载任务列表

- **接口名称**: 获取所有下载任务
- **请求URL**: `GET /downloads/tasks`
- **认证级别**: 无需认证

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "waiting": [
      {
        "id": "a1b2c3d4",
        "url": "https://...",
        "title": "",
        "status": "pending",
        "message": "等待队列中...",
        "torrent_urls": [],
        "torrent_file": "",
        "nfo_path": "",
        "qb_progress": 0.0,
        "qb_state": "",
        "comic_id": null,
        "queue": "waiting",
        "time": "12:00:00"
      }
    ],
    "downloading": [
      {
        "id": "e5f6g7h8",
        "url": "https://...",
        "title": "漫画标题",
        "status": "downloading",
        "message": "下载中",
        "torrent_urls": ["magnet:?xt=..."],
        "torrent_file": "",
        "nfo_path": "",
        "qb_progress": 45.2,
        "qb_state": "downloading",
        "comic_id": null,
        "queue": "downloading",
        "time": "12:05:00"
      }
    ],
    "done": [
      {
        "id": "i9j0k1l2",
        "url": "https://...",
        "title": "已完成漫画",
        "status": "done",
        "message": "导入完成",
        "torrent_urls": [],
        "torrent_file": "",
        "nfo_path": "",
        "qb_progress": 100.0,
        "qb_state": "",
        "comic_id": 5,
        "queue": "downloading",
        "time": "11:30:00"
      }
    ]
  }
}
```

### 6.4 获取下载进度

- **接口名称**: 获取正在下载的任务进度
- **请求URL**: `GET /downloads/progress`
- **认证级别**: 无需认证

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": [
    {
      "id": "e5f6g7h8",
      "url": "https://...",
      "title": "漫画标题",
      "status": "downloading",
      "message": "下载中",
      "torrent_urls": ["magnet:?xt=..."],
      "torrent_file": "",
      "nfo_path": "",
      "qb_progress": 45.2,
      "qb_state": "downloading",
      "comic_id": null,
      "queue": "downloading",
      "time": "12:05:30"
    }
  ]
}
```

### 6.5 获取单个下载任务

- **接口名称**: 获取下载任务详情
- **请求URL**: `GET /downloads/{task_id}`
- **认证级别**: 无需认证

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| task_id | string | 是 | 下载任务ID |

### 6.6 删除下载任务

- **接口名称**: 删除下载任务
- **请求URL**: `DELETE /downloads/{task_id}`
- **认证级别**: 无需认证

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| task_id | string | 是 | 下载任务ID |

**响应示例**:

```json
{
  "code": 0,
  "message": "下载任务已删除"
}
```

**task status 可能值**:

| 状态 | 说明 |
|------|------|
| pending | 等待中 |
| scraping | 正在采集信息 |
| saving_nfo | 保存NFO中 |
| adding_torrent | 添加种子中 |
| matching | 匹配已有漫画中 |
| downloading | 下载中 |
| importing | 导入中 |
| done | 已完成 |
| error | 出错 |
| duplicate | 重复跳过 |

### 6.7 保存下载NFO信息

- **接口名称**: 保存下载过程中采集到的NFO信息
- **请求URL**: `POST /downloads/nfo`
- **认证级别**: 无需认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| source_url | string | 否 | 来源URL |
| title | string | 否 | 标题 |

**请求示例**:

```json
{
  "source_url": "https://e-hentai.org/g/12345/abcdef",
  "title": "漫画标题"
}
```

**响应示例**:

```json
{
  "code": 0,
  "message": "NFO信息已保存",
  "data": { "nfo_path": "path/to/saved.nfo" }
}
```

---

## 7. 采集模块

### 7.1 通过URL采集信息

- **接口名称**: 从URL采集漫画信息
- **请求URL**: `POST /scraper/scrape`
- **认证级别**: 无需认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| url | string | 是 | 目标页面URL（需以http://或https://开头） |

**请求示例**:

```json
{
  "url": "https://e-hentai.org/g/12345/abcdef"
}
```

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "title": "采集到的标题",
    "author": "作者",
    "tags": "tag1,tag2",
    "torrent_urls": "magnet:?xt=...",
    "source_url": "https://...",
    ...
  }
}
```

### 7.2 通过HTML采集信息

- **接口名称**: 从HTML内容采集漫画信息
- **请求URL**: `POST /scraper/scrape-html`
- **认证级别**: 无需认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| html | string | 是 | HTML内容 |
| url | string | 否 | 来源URL（用于识别采集器类型） |

**请求示例**:

```json
{
  "html": "<html>...</html>",
  "url": "https://e-hentai.org/g/12345/abcdef"
}
```

---

## 8. 设置模块

> 设置模块所有接口均需要设备认证

### 8.1 获取设置

- **接口名称**: 获取所有系统设置
- **请求URL**: `GET /settings`
- **认证级别**: 需要设备认证

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "site_name": "xcomic",
    "per_page": "12",
    "max_content_length": "2048",
    "chunk_size": "5",
    "upload_interval": "1",
    "auto_cover": "1",
    "cover_width": "300",
    "cover_quality": "85",
    "proxy_enabled": "0",
    "proxy_type": "http",
    "proxy_host": "",
    "proxy_port": "",
    "proxy_user": "",
    "proxy_pass": "******",
    "cookie_ehentai": "",
    "cookie_exhentai": "",
    "cookie_nhentai": "",
    "qb_enabled": "0",
    "qb_host": "",
    "qb_port": "8080",
    "qb_user": "admin",
    "qb_pass": "******",
    "qb_category": "",
    "qb_download_path": "",
    "tag_mapping": ""
  }
}
```

**说明**: 密码类字段返回 `******` 表示有值但不显示

### 8.2 更新设置

- **接口名称**: 更新系统设置
- **请求URL**: `PUT /settings`
- **认证级别**: 需要设备认证

**请求参数**: 需要更新的设置字段，密码字段传 `******` 表示不修改

**请求示例**:

```json
{
  "site_name": "我的漫画库",
  "per_page": "20",
  "proxy_enabled": "1",
  "proxy_type": "http",
  "proxy_host": "127.0.0.1",
  "proxy_port": "7890"
}
```

**参数范围限制**:

| 参数 | 范围 |
|------|------|
| per_page | 1-100 |
| max_content_length | 100-51200 (MB) |
| chunk_size | 1-100 (MB) |
| cover_width | 100-1000 (px) |
| cover_quality | 10-100 (%) |
| upload_interval | 0-30 (秒) |

### 8.3 备份设置

- **接口名称**: 导出设置备份
- **请求URL**: `GET /settings/backup`
- **认证级别**: 需要设备认证
- **说明**: 返回JSON文件下载

### 8.4 导入设置

- **接口名称**: 导入设置
- **请求URL**: `POST /settings/import`
- **认证级别**: 需要设备认证
- **Content-Type**: `multipart/form-data` 或 `application/json`

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| file | file | 否 | JSON设置文件（form-data方式） |
| - | object | 否 | JSON设置数据（json方式） |

**响应示例**:

```json
{
  "code": 0,
  "message": "导入成功，已更新 15 项设置"
}
```

### 8.5 测试代理

- **接口名称**: 测试代理连接
- **请求URL**: `POST /settings/test-proxy`
- **认证级别**: 需要设备认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| proxy_enabled | string | 否 | 是否启用代理（1/0） |
| proxy_type | string | 否 | 代理类型：http/https/socks5 |
| proxy_host | string | 否 | 代理地址 |
| proxy_port | string | 否 | 代理端口 |
| proxy_user | string | 否 | 代理用户名 |
| proxy_pass | string | 否 | 代理密码 |

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "success": true,
    "message": "连接成功（耗时 1234ms）"
  }
}
```

### 8.6 测试qBittorrent

- **接口名称**: 测试qBittorrent连接
- **请求URL**: `POST /settings/test-qbittorrent`
- **认证级别**: 需要设备认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| qb_host | string | 否 | qBittorrent地址 |
| qb_port | string | 否 | qBittorrent端口 |
| qb_user | string | 否 | 用户名 |
| qb_pass | string | 否 | 密码 |

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "success": true,
    "message": "连接成功 v4.6.3（耗时 567ms）"
  }
}
```

---

## 9. 阅读历史模块

### 9.1 获取阅读历史列表

- **接口名称**: 获取阅读历史（分页）
- **请求URL**: `GET /history`
- **认证级别**: 可选设备认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| page | int | 否 | 页码，默认1 |
| per_page | int | 否 | 每页数量，默认20 |
| sort | string | 否 | 排序：last_read/read_count/progress，默认last_read |

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "items": [
      {
        "comic_id": 1,
        "last_page": 10,
        "total_pages": 24,
        "read_count": 3,
        "last_read_at": "2024-01-15T12:00:00",
        "comic": {
          "id": 1,
          "title": "漫画标题",
          "cover": "subdir/cover.jpg",
          ...
        }
      }
    ],
    "pagination": { ... }
  }
}
```

### 9.2 获取单本漫画阅读历史

- **接口名称**: 获取指定漫画的阅读历史
- **请求URL**: `GET /history/{comic_id}`
- **认证级别**: 无需认证

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| comic_id | int | 是 | 漫画ID |

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "comic_id": 1,
    "last_page": 10,
    "total_pages": 24,
    "read_count": 3,
    "last_read_at": "2024-01-15T12:00:00",
    "comic": {
      "id": 1,
      "title": "漫画标题",
      ...
    }
  }
}
```

### 9.3 删除阅读历史

- **接口名称**: 删除指定漫画的阅读历史
- **请求URL**: `DELETE /history/{comic_id}`
- **认证级别**: 无需认证

**响应示例**:

```json
{
  "code": 0,
  "message": "阅读记录已删除"
}
```

### 9.4 清空阅读历史

- **接口名称**: 清空所有阅读历史
- **请求URL**: `POST /history/clear`
- **认证级别**: 无需认证

**响应示例**:

```json
{
  "code": 0,
  "message": "所有阅读记录已清除"
}
```

### 9.5 获取最近阅读

- **接口名称**: 获取最近阅读的漫画
- **请求URL**: `GET /history/recent`
- **认证级别**: 可选设备认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| count | int | 否 | 数量，默认10，最大50 |

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": [
    {
      "comic_id": 1,
      "last_page": 10,
      "total_pages": 24,
      "last_read_at": "2024-01-15T12:00:00",
      "comic": {
        "id": 1,
        "title": "漫画标题",
        "cover": "subdir/cover.jpg",
        ...
      }
    }
  ]
}
```

---

## 10. 统计模块

### 10.1 获取系统统计

- **接口名称**: 获取系统统计数据
- **请求URL**: `GET /stats`
- **认证级别**: 无需认证

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "site_name": "xcomic",
    "comics": {
      "total": 100,
      "total_size": 10737418240,
      "total_pages": 5000,
      "favorites": 10
    },
    "collections": {
      "total": 20,
      "favorites": 3
    },
    "reading": {
      "total_records": 50,
      "total_read_count": 200,
      "finished_count": 15
    },
    "tasks": {
      "downloading": 2,
      "uploading": 1
    }
  }
}
```

### 10.2 获取标签统计

- **接口名称**: 获取标签使用统计（Top 100）
- **请求URL**: `GET /stats/tags`
- **认证级别**: 无需认证

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": [
    { "tag": "parody:xxx", "count": 15 },
    { "tag": "big breasts", "count": 12 }
  ]
}
```

### 10.3 获取作者统计

- **接口名称**: 获取作者作品统计（Top 50）
- **请求URL**: `GET /stats/authors`
- **认证级别**: 无需认证

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": [
    { "author": "作者A", "count": 25 },
    { "author": "作者B", "count": 18 }
  ]
}
```

---

## 11. 标签模块

### 11.1 获取标签列表

- **接口名称**: 获取所有标签（分页）
- **请求URL**: `GET /tags`
- **认证级别**: 无需认证
- **说明**: 从所有漫画中提取标签，按使用次数降序排列

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| page | int | 否 | 页码，默认1 |
| per_page | int | 否 | 每页数量，默认100 |
| category | string | 否 | 按标签分类筛选，如"parody"、"character" |
| search | string | 否 | 搜索关键词（同时搜索原始标签和映射后的显示名） |

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "items": [
      {
        "tag": "戏仿:原创",
        "raw_tag": "parody:original work",
        "category": "戏仿",
        "raw_category": "parody",
        "value": "原创",
        "raw_value": "original work",
        "count": 25
      },
      {
        "tag": "巨乳",
        "raw_tag": "big breasts",
        "category": "",
        "raw_category": "",
        "value": "巨乳",
        "raw_value": "big breasts",
        "count": 18
      }
    ],
    "pagination": {
      "page": 1,
      "per_page": 100,
      "total": 150,
      "pages": 2
    }
  }
}
```

> **字段说明**：`tag`/`category`/`value` 为映射后的显示名（中文），`raw_tag`/`raw_category`/`raw_value` 为原始英文标签。安卓端显示时使用映射后字段，搜索/查询时使用原始字段。

### 11.2 获取标签分类列表

- **接口名称**: 获取所有标签分类及统计
- **请求URL**: `GET /tags/categories`
- **认证级别**: 无需认证

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": [
    {
      "category": "戏仿",
      "raw_category": "parody",
      "tag_count": 45,
      "comic_count": 30
    },
    {
      "category": "(未分类)",
      "raw_category": "",
      "tag_count": 120,
      "comic_count": 50
    }
  ]
}
```

### 11.3 获取标签映射

- **接口名称**: 获取所有标签映射规则
- **请求URL**: `GET /tags/mapping`
- **认证级别**: 无需认证
- **说明**: 标签映射用于将英文标签显示为中文，如 "big breasts" → "巨乳"

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": [
    { "original": "big breasts", "display": "巨乳" },
    { "original": "parody:original work", "display": "原创" }
  ]
}
```

### 11.4 批量更新标签映射

- **接口名称**: 批量替换标签映射规则
- **请求URL**: `PUT /tags/mapping`
- **认证级别**: 无需认证
- **说明**: 整体替换所有映射规则

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| mappings | array | 是 | 映射规则数组 |

**请求示例**:

```json
{
  "mappings": [
    { "original": "big breasts", "display": "巨乳" },
    { "original": "parody:original work", "display": "原创" },
    { "original": "sole female", "display": "单女" }
  ]
}
```

### 11.5 添加单条标签映射

- **接口名称**: 添加一条标签映射规则
- **请求URL**: `POST /tags/mapping`
- **认证级别**: 无需认证

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| original | string | 是 | 原始标签名 |
| display | string | 是 | 显示名称 |

**请求示例**:

```json
{
  "original": "big breasts",
  "display": "巨乳"
}
```

**响应示例**:

```json
{
  "code": 0,
  "message": "标签映射已添加",
  "data": {
    "original": "big breasts",
    "display": "巨乳"
  }
}
```

### 11.6 删除标签映射

- **接口名称**: 删除一条标签映射规则
- **请求URL**: `DELETE /tags/mapping/{original}`
- **认证级别**: 无需认证

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| original | string | 是 | 原始标签名（URL编码） |

**响应示例**:

```json
{
  "code": 0,
  "message": "标签映射已删除"
}
```

### 11.7 搜索标签

- **接口名称**: 搜索标签（自动补全）
- **请求URL**: `GET /tags/search`
- **认证级别**: 无需认证
- **说明**: 同时搜索原始标签和映射后的显示名，适用于安卓端标签输入自动补全

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| q | string | 是 | 搜索关键词 |
| limit | int | 否 | 返回数量，默认20，最大100 |

**请求示例**:

```
GET /tags/search?q=big&limit=10
```

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": [
    { "tag": "巨乳", "raw_tag": "big breasts", "count": 18 },
    { "tag": "大屁股", "raw_tag": "big ass", "count": 5 }
  ]
}
```

### 11.8 获取标签下的漫画

- **接口名称**: 获取指定标签下的漫画列表
- **请求URL**: `GET /tags/{tag_path}/comics`
- **认证级别**: 无需认证
- **说明**: tag_path 为标签完整路径，如 `parody:original%20work` 或 `big%20breasts`

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| tag_path | string | 是 | 标签路径（URL编码） |

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| page | int | 否 | 页码，默认1 |
| per_page | int | 否 | 每页数量，默认20 |

**请求示例**:

```
GET /tags/big%20breasts/comics?page=1&per_page=20
```

**响应示例**:

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "items": [
      { "id": 1, "title": "漫画标题", "tags": "巨乳,...", "raw_tags": "big breasts,...", ... }
    ],
    "pagination": {
      "page": 1,
      "per_page": 20,
      "total": 18,
      "pages": 1
    }
  }
}
```

---

## 12. 封面模块

### 12.1 获取封面图片

- **接口名称**: 获取封面图片
- **请求URL**: `GET /covers/{filename}`
- **认证级别**: 无需认证
- **说明**: 直接返回图片二进制流，安卓端可用 Glide/Coil 直接加载

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| filename | string | 是 | 封面文件路径（从漫画/合集数据中的cover字段获取） |

**安卓端使用示例**:

```kotlin
val coverUrl = "${baseUrl}/api/v1/covers/${comic.cover}"
Glide.with(context).load(coverUrl).into(imageView)
```

---

## 13. 错误码说明

| 错误码 | 说明 |
|--------|------|
| 0 | 成功 |
| 400 | 请求参数错误 |
| 401 | 未授权，Token过期或无效 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 405 | 请求方法不允许 |
| 409 | 资源冲突（如重复创建、非空删除） |
| 413 | 请求体过大 |
| 422 | 数据验证失败 |
| 500 | 服务器内部错误 |
| 503 | 服务暂不可用 |

**错误响应示例**:

```json
{
  "code": 401,
  "message": "Token已过期"
}
```

```json
{
  "code": 409,
  "message": "合集中还有 3 本漫画，请先移除"
}
```

---

## 14. 附录：安卓端集成指南

### 1. 设备连接与认证

```kotlin
import android.provider.Settings
import android.os.Build

// 获取设备唯一标识
val deviceId = Settings.Secure.getString(
    context.contentResolver,
    Settings.Secure.ANDROID_ID
)

// 连接设备（所有设备均可直接连接，无需审批）
suspend fun connectDevice() {
    val savedToken = tokenStore.getAccessToken()
    if (savedToken != null) {
        // 尝试使用旧Token重新连接
        try {
            val result = api.reconnect()
            tokenStore.saveAccessToken(result.access_token)
            syncTagMapping(result.tag_mapping, result.tag_mapping_version)
            return
        } catch (e: HttpException) {
            if (e.code() != 401) throw e
        }
    }
    // 使用设备ID连接（任何设备均可直接连接）
    val result = api.connect(
        deviceId = deviceId,
        deviceName = Build.MODEL,
        deviceType = "android"
    )
    tokenStore.saveAccessToken(result.access_token)
    syncTagMapping(result.tag_mapping, result.tag_mapping_version)
}

// 同步标签映射到本地
fun syncTagMapping(mapping: List<TagMapping>, version: String) {
    val localVersion = prefs.getString("tag_mapping_version", "") ?: ""
    if (version != localVersion) {
        // 版本不一致，更新本地映射
        val json = Gson().toJson(mapping)
        prefs.edit()
            .putString("tag_mapping", json)
            .putString("tag_mapping_version", version)
            .apply()
    }
}

// 使用本地映射转换标签
fun mapTag(original: String): String {
    val mappingJson = prefs.getString("tag_mapping", null) ?: return original
    val mappings = Gson().fromJson(mappingJson, Array<TagMapping>::class.java)
    return mappings.find { it.original.equals(original, ignoreCase = true) }
        ?.display ?: original
}
```

### 2. 网络配置

```kotlin
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import java.util.concurrent.TimeUnit

// Retrofit 配置示例
val okHttpClient = OkHttpClient.Builder()
    .addInterceptor { chain ->
        val token = tokenStore.getAccessToken()
        val request = if (token != null) {
            chain.request().newBuilder()
                .addHeader("Authorization", "Bearer $token")
                .build()
        } else {
            chain.request()
        }
        chain.proceed(request)
    }
    .addInterceptor { chain ->
        val response = chain.proceed(chain.request())
        if (response.code == 401) {
            // Token过期，重新连接设备
            val newToken = reconnectDevice()
            if (newToken != null) {
                val newRequest = chain.request().newBuilder()
                    .header("Authorization", "Bearer $newToken")
                    .build()
                chain.proceed(newRequest)
            } else {
                response
            }
        } else {
            response
        }
    }
    .connectTimeout(30, TimeUnit.SECONDS)
    .readTimeout(60, TimeUnit.SECONDS)
    .writeTimeout(120, TimeUnit.SECONDS)
    .build()

val retrofit = Retrofit.Builder()
    .baseUrl("http://${serverIp}:8724/api/v1/")
    .client(okHttpClient)
    .addConverterFactory(GsonConverterFactory.create())
    .build()
```

### 3. 分片上传示例

```kotlin
suspend fun uploadFile(file: File, collectionName: String = "") {
    // 1. 初始化上传
    val initResult = api.initUpload(
        filename = file.name,
        fileSize = file.length(),
        collectionName = collectionName
    )
    val uploadId = initResult.id
    val chunkSize = initResult.chunkSize
    val totalChunks = initResult.totalChunks

    // 2. 上传分片
    for (i in 0 until totalChunks) {
        val start = i * chunkSize.toLong()
        val end = minOf(start + chunkSize.toLong(), file.length())
        val chunkData = file.readBytes(start.toInt(), (end - start).toInt())

        api.uploadChunk(
            uploadId = uploadId,
            chunkIndex = i,
            chunkData = chunkData
        )

        // 更新进度
        val progress = (i + 1) * 100 / totalChunks
        updateProgress(progress)
    }

    // 3. 完成上传
    api.completeUpload(uploadId)

    // 4. 轮询状态
    while (true) {
        val status = api.getUploadStatus(uploadId)
        if (status.status == "completed") break
        if (status.status == "failed") throw Exception("上传失败")
        delay(2000)
    }
}
```

### 4. 断点续传示例

```kotlin
suspend fun resumeUpload(uploadId: String, file: File) {
    val status = api.getUploadStatus(uploadId)
    val uploadedChunks = status.uploadedChunks.toSet()

    for (i in 0 until status.totalChunks) {
        if (i in uploadedChunks) continue  // 跳过已上传分片

        val start = i * status.chunkSize.toLong()
        val end = minOf(start + status.chunkSize.toLong(), file.length())
        val chunkData = file.readBytes(start.toInt(), (end - start).toInt())

        api.uploadChunk(
            uploadId = uploadId,
            chunkIndex = i,
            chunkData = chunkData
        )
    }

    api.completeUpload(uploadId)
}
```

### 5. 阅读器页面加载

```kotlin
import coil.compose.AsyncImage
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.Modifier

// 页面URL拼接
val pageUrl = "${baseUrl}/api/v1/comics/${comicId}/page/${pageFilename}"

// Coil加载（Jetpack Compose）
AsyncImage(
    model = pageUrl,
    contentDescription = "Page $pageNum",
    modifier = Modifier.fillMaxSize()
)

// Glide加载（传统View）
Glide.with(context)
    .load(pageUrl)
    .into(imageView)
```

### 6. 封面图片加载

```kotlin
// 封面URL拼接
val coverUrl = "${baseUrl}/api/v1/covers/${comic.cover}"

// Coil + 占位图
AsyncImage(
    model = coverUrl,
    contentDescription = comic.title,
    placeholder = painterResource(R.drawable.placeholder),
    error = painterResource(R.drawable.error),
    modifier = Modifier.size(120.dp, 160.dp)
)
```

### 7. 完整接口调用流程

```
应用启动
  ↓
检查本地Token → 无Token → POST /auth/connect (传入device_id)
  ↓ 有Token                          ↓ 直接获取Token
POST /auth/reconnect                 保存Token
  ↓ 成功                             ↓
正常使用API                    正常使用API
  ↓ 401错误
POST /auth/connect (重新连接)
  ↓
保存新Token → 继续使用API

注意：所有设备均可直接连接，无需任何审批或验证流程
```
