# 图片处理服务器 API 文档

## 概述
本文档描述了图片处理服务器的所有API接口，包括用户认证、图片管理、系统状态、云端同步等功能。

## 基础信息
- **服务器地址**: `http://localhost:8080`
- **数据格式**: JSON
- **认证方式**: Session认证
- **字符编码**: UTF-8

## 目录
1. [系统状态接口](#系统状态接口)
2. [用户认证接口](#用户认证接口)
3. [图片管理接口](#图片管理接口)
4. [任务管理接口](#任务管理接口)
5. [云端同步接口](#云端同步接口)
6. [错误码说明](#错误码说明)

---

## 系统状态接口

### 1. 获取服务器状态
获取服务器运行状态和基本信息。

**接口地址**：`GET /api/status`

**请求参数**：无

**请求示例**：
```http
GET /api/status HTTP/1.1
Host: localhost:8080
Content-Type: application/json
```

**响应示例**：
```json
{
  "status": "running",
  "timestamp": "2025-06-13T18:45:30.123456",
  "total_images": 125
}
```

**字段说明**：
- `status`: 服务器状态，固定值 "running"
- `timestamp`: 当前服务器时间（ISO格式）
- `total_images`: 系统中图片总数

---

## 用户认证接口

### 2. 用户注册
注册新用户账户。

**接口地址**：`POST /api/register`

**请求参数**：
```json
{
  "username": "string",    // 必填，用户名，3-20位
  "email": "string",       // 必填，邮箱地址
  "password": "string"     // 必填，密码，6位以上
}
```

**请求示例**：
```json
{
  "username": "testuser",
  "email": "test@example.com",
  "password": "password123"
}
```

**响应示例**：
```json
{
  "success": true,
  "user_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "message": "注册成功"
}
```

**错误响应**：
```json
{
  "success": false,
  "error": "用户名或邮箱已存在"
}
```

**说明**：
- 注册成功后，如果启用云端同步，系统会自动尝试在云端注册用户
- 云端注册失败不影响本地注册结果

### 3. 用户登录
用户登录系统。

**接口地址**：`POST /api/login`

**请求参数**：
```json
{
  "username": "string",      // 必填，用户名
  "password": "string",      // 必填，密码
  "remember_me": "boolean"   // 可选，是否记住登录状态，默认false
}
```

**请求示例**：
```json
{
  "username": "admin",
  "password": "admin123",
  "remember_me": true
}
```

**响应示例**：
```json
{
  "success": true,
  "user": {
    "user_id": "default-user-12345678",
    "username": "admin",
    "email": "admin@local.com"
  },
  "message": "登录成功"
}
```

**错误响应**：
```json
{
  "success": false,
  "error": "用户名或密码错误"
}
```

**说明**：
- 登录成功后，如果启用云端同步，系统会自动尝试云端登录
- 会话有效期：记住登录为7天，普通登录为浏览器会话期间

### 4. 检查登录状态
检查当前用户的登录状态。

**接口地址**：`GET /api/auth/check`

**请求参数**：无

**请求示例**：
```http
GET /api/auth/check HTTP/1.1
Host: localhost:8080
Cookie: session=...
```

**响应示例（已登录）**：
```json
{
  "authenticated": true,
  "user": {
    "user_id": "default-user-12345678",
    "username": "admin",
    "email": "admin@local.com",
    "created_at": "2025-06-13 10:30:00",
    "last_login": "2025-06-13 18:45:00",
    "cloud_sync_enabled": false
  }
}
```

**响应示例（未登录）**：
```json
{
  "authenticated": false
}
```

### 5. 用户登出
用户退出登录。

**接口地址**：`POST /api/logout`

**请求参数**：无

**认证要求**：需要登录

**响应示例**：
```json
{
  "success": true,
  "message": "登出成功"
}
```

### 6. 获取用户资料
获取当前登录用户的详细信息。

**接口地址**：`GET /api/user/profile`

**请求参数**：无

**认证要求**：需要登录

**响应示例**：
```json
{
  "success": true,
  "user": {
    "user_id": "default-user-12345678",
    "username": "admin",
    "email": "admin@local.com",
    "created_at": "2025-06-13 10:30:00",
    "last_login": "2025-06-13 18:45:00",
    "cloud_sync_enabled": false,
    "image_count": 25
  }
}
```

---

## 图片管理接口

### 7. 接收图片数据
接收浏览器插件发送的图片数据并保存。

**接口地址**：`POST /api/receive-image`

**认证要求**：无（支持未登录用户）

**请求参数**：
```json
{
  "imageData": "string",     // 必填，图片数据（base64或URL）
  "originalUrl": "string",   // 可选，图片原始URL
  "category": "string",      // 可选，保存分类（clothes/char），默认clothes
  "pageInfo": {              // 可选，页面信息
    "url": "string",         // 页面URL
    "title": "string",       // 页面标题
    "imageContext": {}       // 图片上下文信息
  }
}
```

**请求示例**：
```json
{
  "imageData": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
  "originalUrl": "https://example.com/image.png",
  "category": "clothes",
  "pageInfo": {
    "url": "https://example.com/page",
    "title": "示例页面",
    "imageContext": {
      "alt": "示例图片",
      "caption": "这是一张示例图片"
    }
  }
}
```

**响应示例**：
```json
{
  "success": true,
  "taskId": "t-12345678-90ab-cdef-1234-567890abcdef",
  "imageId": "i-87654321-fedc-ba09-8765-432109876543",
  "filename": "clothes_20250613_184530_87654321.png",
  "fileSize": 245760,
  "category": "clothes",
  "isLoggedIn": false,
  "message": "图片已保存到默认目录的clothes文件夹，建议登录以便管理您的图片"
}
```

### 8. 剪切板图片上传
从用户剪切板读取图片数据并保存到指定分类。

**接口地址**：`POST /api/upload-clipboard`

**认证要求**：无（支持未登录用户）

**请求参数**：
```json
{
  "imageData": "string",     // 必填，剪切板图片数据（base64格式）
  "category": "string"       // 可选，保存分类（clothes/char），默认clothes
}
```

**请求示例**：
```json
{
  "imageData": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
  "category": "char"
}
```

**响应示例**：
```json
{
  "success": true,
  "taskId": "t-12345678-90ab-cdef-1234-567890abcdef",
  "imageId": "i-87654321-fedc-ba09-8765-432109876543",
  "filename": "char_20250613_184530_87654321.png",
  "fileSize": 245760,
  "category": "char",
  "isLoggedIn": true,
  "message": "剪切板图片已保存到 char 文件夹"
}
```

**错误响应**：
```json
{
  "success": false,
  "error": "剪切板中没有图片数据"
}
```

### 9. 文件上传
上传本地图片文件到服务器。

**接口地址**：`POST /api/upload-file`

**认证要求**：无（支持未登录用户）

**Content-Type**: `multipart/form-data`

**请求参数**：
- `file`: 图片文件（必填）
- `category`: 保存分类，可选值 "clothes" 或 "char"，默认 "clothes"

**请求示例**：
```http
POST /api/upload-file HTTP/1.1
Host: localhost:8080
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary7MA4YWxkTrZu0gW

------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="file"; filename="example.png"
Content-Type: image/png

[图片二进制数据]
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="category"

clothes
------WebKitFormBoundary7MA4YWxkTrZu0gW--
```

**支持的文件格式**：
- PNG (.png)
- JPEG (.jpg, .jpeg)
- GIF (.gif)
- WebP (.webp)

**文件大小限制**：最大 10MB

**响应示例**：
```json
{
  "success": true,
  "taskId": "t-12345678-90ab-cdef-1234-567890abcdef",
  "imageId": "i-87654321-fedc-ba09-8765-432109876543",
  "filename": "clothes_20250613_184530_87654321.png",
  "fileSize": 245760,
  "category": "clothes",
  "originalFilename": "example.png",
  "isLoggedIn": true,
  "message": "文件已上传到 clothes 文件夹"
}
```

**错误响应**：
```json
{
  "success": false,
  "error": "不支持的文件格式，请上传 PNG、JPG、JPEG、GIF 或 WebP 格式的图片"
}
```

### 10. 获取用户图片列表
获取当前用户的图片列表。

**接口地址**：`GET /api/user/images`

**认证要求**：需要登录

**请求参数**：
- `page`: 页码，默认1
- `per_page`: 每页数量，默认20

**请求示例**：
```http
GET /api/user/images?page=1&per_page=10 HTTP/1.1
Host: localhost:8080
Cookie: session=...
```

**响应示例**：
```json
{
  "images": [
    {
      "id": "i-87654321-fedc-ba09-8765-432109876543",
      "user_id": "default-user-12345678",
      "filename": "clothes_20250613_184530_87654321.png",
      "original_url": "https://example.com/image.png",
      "page_url": "https://example.com/page",
      "page_title": "示例页面",
      "saved_at": "2025-06-13 18:45:30",
      "file_size": 245760,
      "image_width": 800,
      "image_height": 600,
      "context_info": {
        "alt": "示例图片",
        "caption": "这是一张示例图片",
        "category": "clothes"
      },
      "status": "saved",
      "cloud_synced": false,
      "preview_url": "/api/user/default-user-12345678/images/clothes_20250613_184530_87654321.png",
      "thumbnail_url": "/api/user/default-user-12345678/thumbnails/clothes_20250613_184530_87654321.png"
    }
  ],
  "total": 25,
  "page": 1,
  "per_page": 10,
  "pages": 3
}
```

### 11. 获取用户图片文件
获取用户的具体图片文件。

**接口地址**：`GET /api/user/{user_id}/images/{filename}`

**认证要求**：需要登录（只能访问自己的图片）

**请求示例**：
```http
GET /api/user/default-user-12345678/images/clothes_20250613_184530_87654321.png HTTP/1.1
Host: localhost:8080
Cookie: session=...
```

**响应**：返回图片文件二进制数据

**错误响应**：
```json
{
  "error": "权限不足"
}
```

### 12. 按分类获取用户图片文件
按指定分类获取用户图片文件。

**接口地址**：`GET /api/user/{user_id}/images/{category}/{filename}`

**认证要求**：需要登录（只能访问自己的图片）

**请求参数**：
- `user_id`: 用户ID
- `category`: 图片分类（clothes 或 char）
- `filename`: 文件名

**请求示例**：
```http
GET /api/user/default-user-12345678/images/char/char_20250613_184530_87654321.png HTTP/1.1
Host: localhost:8080
Cookie: session=...
```

**响应**：返回图片文件二进制数据

### 13. 获取用户缩略图
获取用户图片的缩略图。

**接口地址**：`GET /api/user/{user_id}/thumbnails/{filename}`

**认证要求**：需要登录（只能访问自己的图片）

**请求示例**：
```http
GET /api/user/default-user-12345678/thumbnails/clothes_20250613_184530_87654321.png HTTP/1.1
Host: localhost:8080
Cookie: session=...
```

**响应**：返回缩略图文件二进制数据（当前实现返回原图）

---

## 任务管理接口

### 14. 获取任务状态
获取图片处理任务的状态。

**接口地址**：`GET /api/task/{task_id}`

**请求参数**：无

**请求示例**：
```http
GET /api/task/t-12345678-90ab-cdef-1234-567890abcdef HTTP/1.1
Host: localhost:8080
```

**响应示例**：
```json
{
  "status": {
    "task_id": "t-12345678-90ab-cdef-1234-567890abcdef",
    "user_id": "default-user-12345678",
    "status": "completed",
    "created_at": "2025-06-13 18:45:30",
    "updated_at": "2025-06-13 18:45:31",
    "image_id": "i-87654321-fedc-ba09-8765-432109876543"
  }
}
```

**错误响应**：
```json
{
  "error": "任务不存在"
}
```

---

## 云端同步接口

### 15. 同步数据到云端
将用户数据和图片文件同步到云端服务器。

**接口地址**：`POST /api/cloud/sync`

**认证要求**：需要登录

**请求参数**：无

**功能说明**：
- 获取用户信息和所有图片元数据
- 读取本地图片文件并转换为base64格式
- 构造完整的同步数据包
- 将数据和文件上传到云端服务器
- 更新本地同步状态标记

**同步数据结构**：
```json
{
  "user_info": {
    "user_id": "string",
    "username": "string", 
    "email": "string",
    "created_at": "datetime",
    "last_login": "datetime",
    "cloud_sync_enabled": "boolean"
  },
  "images_metadata": [
    {
      "id": "string",
      "user_id": "string",
      "filename": "string",
      "original_url": "string",
      "page_url": "string",
      "page_title": "string",
      "saved_at": "datetime",
      "file_size": "integer",
      "image_width": "integer",
      "image_height": "integer",
      "context_info": "object",
      "status": "string",
      "cloud_synced": "boolean"
    }
  ],
  "image_files": {
    "filename1.png": "data:image/png;base64,iVBORw0KGgoAAAA...",
    "filename2.jpg": "data:image/jpeg;base64,/9j/4AAQSkZJRg..."
  },
  "sync_timestamp": "datetime",
  "sync_statistics": {
    "total_metadata_records": "integer",
    "total_files_found": "integer", 
    "total_files_missing": "integer",
    "total_size": "integer",
    "categories": ["clothes", "char"]
  }
}
```

**请求示例**：
```http
POST /api/cloud/sync HTTP/1.1
Host: localhost:8080
Cookie: session=...
Content-Type: application/json
```

**响应示例（启用云端同步）**：
```json
{
  "success": true,
  "message": "同步任务已启动",
  "sync_info": {
    "user_id": "default-user-12345678",
    "image_count": 25,
    "estimated_time": "2.5秒"
  }
}
```

**响应示例（禁用云端同步）**：
```json
{
  "success": false,
  "error": "云端同步功能已禁用"
}
```

**同步过程说明**：
1. 获取用户信息和图片元数据列表
2. 遍历每个图片记录，按分类查找对应文件
3. 读取图片文件并转换为base64格式
4. 构造同步数据包，包含元数据和文件数据
5. 异步上传到云端服务器的 `/sync/user/{user_id}` 接口
6. 更新本地数据库中的 `cloud_synced` 标记

**错误处理**：
- 文件不存在：记录警告，继续处理其他文件
- 网络超时：5分钟超时限制
- 云端错误：返回详细错误信息
- 同步失败：不影响本地数据

**性能优化**：
- 异步处理，不阻塞接口响应
- 批量上传，减少网络请求次数
- 断点续传（计划功能）
- 增量同步（计划功能）

---

## 错误码说明

### HTTP状态码
- `200`: 请求成功
- `400`: 请求参数错误
- `401`: 未登录或认证失败
- `403`: 权限不足
- `404`: 资源不存在
- `500`: 服务器内部错误

### 业务错误码
响应JSON中的`error`字段包含具体错误信息：

- `"需要登录"`: 接口需要用户登录才能访问
- `"权限不足"`: 用户无权访问该资源
- `"用户名、邮箱和密码不能为空"`: 注册时必填字段缺失
- `"用户名或邮箱已存在"`: 注册时用户名或邮箱已被占用
- `"用户名或密码错误"`: 登录时凭据错误
- `"用户不存在"`: 查询的用户不存在
- `"缺少图片数据"`: 上传图片时缺少图片数据
- `"剪切板中没有图片数据"`: 剪切板上传时无有效图片数据
- `"没有选择文件"`: 文件上传时未选择文件
- `"文件名为空"`: 文件上传时文件名为空
- `"不支持的文件格式"`: 上传的文件格式不在支持列表中
- `"文件大小不能超过10MB"`: 上传文件超过大小限制
- `"无效的分类"`: 指定的分类参数无效
- `"保存图片失败"`: 图片保存过程中出错
- `"保存剪切板图片失败"`: 剪切板图片保存失败
- `"保存上传文件失败"`: 文件上传保存失败
- `"任务不存在"`: 查询的任务ID不存在
- `"图片不存在"`: 请求的图片文件不存在
- `"云端同步功能已禁用"`: 云端同步功能未启用
- `"用户目录不存在"`: 用户存储目录不存在
- `"同步请求超时"`: 云端同步请求超时
- `"网络请求失败"`: 网络连接问题
- `"云端响应错误"`: 云端服务器返回错误

---

## 配置说明

### 云端同步配置
在 `app.py` 中修改以下配置：

```python
# 云端服务器配置
CLOUD_SERVER_URL = "http://localhost:8081/api"  # 云端服务器地址
ENABLE_CLOUD_SYNC = True  # 启用云端同步

# 文件存储配置
BASE_SAVE_DIR = Path("saved_images")  # 本地存储目录
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}  # 支持的文件格式
```

### 数据库配置
- **数据库文件**: `image_database.db`
- **自动迁移**: 支持从旧版本数据库自动迁移
- **连接池**: 使用SQLite连接池
- **事务处理**: 支持事务回滚

### 文件存储结构
```
saved_images/
├── {user_id}/
│   ├── clothes/           # 服装类图片
│   │   ├── clothes_20250613_184530_12345678.png
│   │   └── clothes_20250613_184531_87654321.jpg
│   └── char/             # 角色类图片
│       ├── char_20250613_184532_abcdefgh.png
│       └── char_20250613_184533_ijklmnop.webp
└── default-user-{id}/    # 未登录用户的默认目录
    ├── clothes/
    └── char/
```

---

## 使用示例

### 完整的使用流程示例

1. **检查系统状态**
```bash
curl -X GET http://localhost:8080/api/status
```

2. **用户登录**
```bash
curl -X POST http://localhost:8080/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123","remember_me":true}' \
  -c cookies.txt
```

3. **检查登录状态**
```bash
curl -X GET http://localhost:8080/api/auth/check \
  -b cookies.txt
```

4. **剪切板图片上传**
```bash
curl -X POST http://localhost:8080/api/upload-clipboard \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "imageData": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "category": "char"
  }'
```

5. **文件上传**
```bash
curl -X POST http://localhost:8080/api/upload-file \
  -b cookies.txt \
  -F "file=@/path/to/image.png" \
  -F "category=clothes"
```

6. **云端同步**
```bash
curl -X POST http://localhost:8080/api/cloud/sync \
  -b cookies.txt
```

7. **获取用户资料**
```bash
curl -X GET http://localhost:8080/api/user/profile \
  -b cookies.txt
```

8. **获取图片列表**
```bash
curl -X GET "http://localhost:8080/api/user/images?per_page=5" \
  -b cookies.txt
```

9. **下载图片**
```bash
curl -X GET "http://localhost:8080/api/user/{user_id}/images/{filename}" \
  -b cookies.txt \
  -o downloaded_image.png
```

10. **用户登出**
```bash
curl -X POST http://localhost:8080/api/logout \
  -b cookies.txt
```

---

## 数据结构说明

### 用户对象 (User)
```json
{
  "user_id": "string",           // 用户唯一ID
  "username": "string",          // 用户名
  "email": "string",             // 邮箱
  "created_at": "datetime",      // 创建时间
  "last_login": "datetime",      // 最后登录时间
  "cloud_sync_enabled": "boolean", // 是否启用云端同步
  "image_count": "integer"       // 图片数量（仅在profile接口中包含）
}
```

### 图片对象 (Image)
```json
{
  "id": "string",                // 图片唯一ID
  "user_id": "string",           // 所属用户ID
  "filename": "string",          // 文件名（包含分类前缀）
  "original_url": "string",      // 原始URL
  "page_url": "string",          // 来源页面URL
  "page_title": "string",        // 来源页面标题
  "saved_at": "datetime",        // 保存时间
  "file_size": "integer",        // 文件大小（字节）
  "image_width": "integer",      // 图片宽度
  "image_height": "integer",     // 图片高度
  "context_info": "object",      // 上下文信息（包含分类等）
  "status": "string",            // 状态（saved等）
  "cloud_synced": "boolean",     // 是否已云端同步
  "preview_url": "string",       // 预览URL
  "thumbnail_url": "string"      // 缩略图URL
}
```

### 任务对象 (Task)
```json
{
  "task_id": "string",           // 任务唯一ID
  "user_id": "string",           // 所属用户ID
  "status": "string",            // 任务状态（processing/completed）
  "created_at": "datetime",      // 创建时间
  "updated_at": "datetime",      // 更新时间
  "image_id": "string"           // 关联图片ID
}
```

### 云端同步数据结构 (SyncData)
```json
{
  "user_info": "User",           // 用户信息对象
  "images_metadata": ["Image"],  // 图片元数据数组
  "image_files": {               // 图片文件数据字典
    "filename": "base64_data"    // 文件名: base64数据
  },
  "sync_timestamp": "datetime",  // 同步时间戳
  "sync_statistics": {           // 同步统计信息
    "total_metadata_records": "integer",
    "total_files_found": "integer",
    "total_files_missing": "integer", 
    "total_size": "integer",
    "categories": ["string"]
  }
}
```

---

## 分类管理说明

### 分类定义
系统支持两种图片分类：

1. **clothes（服装类）**
   - 用途：服装、配饰等可穿戴物品
   - 应用场景：虚拟试衣、服装搭配等
   - 文件名前缀：`clothes_`

2. **char（角色类）**
   - 用途：人物角色、模特等
   - 应用场景：人物建模、角色设计等
   - 文件名前缀：`char_`

### 分类规则
- 如果不指定分类，默认保存到 `clothes` 分类
- 无效的分类参数会自动降级为 `clothes`
- 每个用户目录下自动创建分类子目录
- 文件名包含分类前缀便于识别

### 目录结构
```
saved_images/
├── {user_id}/
│   ├── clothes/
│   │   ├── clothes_20250613_184530_12345678.png
│   │   └── clothes_20250613_184531_87654321.jpg
│   └── char/
│       ├── char_20250613_184532_abcdefgh.png
│       └── char_20250613_184533_ijklmnop.webp
```

---

## 注意事项

1. **会话管理**: 使用Cookie进行会话管理，登录后需要在后续请求中携带Cookie
2. **权限控制**: 用户只能访问自己的图片和数据
3. **文件存储**: 每个用户的图片存储在独立的目录中，按分类组织
4. **数据库迁移**: 系统会自动检测并迁移旧版本的数据库结构
5. **云端同步**: 需要云端服务器配合，支持异步处理
6. **图片格式**: 支持PNG、JPG、JPEG、GIF、WEBP格式
7. **文件大小**: 单个文件最大10MB
8. **分类验证**: 系统会验证分类参数，无效分类自动降级为 `clothes`
9. **剪切板权限**: 剪切板功能需要用户授权，某些浏览器可能有限制
10. **批量上传**: 建议单次上传文件数量不超过 20 个
11. **目录自动创建**: 系统会自动创建所需的分类目录
12. **默认用户**: 未登录用户的图片保存到默认用户目录，建议登录管理
13. **同步超时**: 云端同步超时时间为5分钟
14. **网络要求**: 云端同步需要稳定的网络连接

---

## 更新日志

### v1.0.0 (2025-06-13)
- 初始版本发布
- 实现用户认证系统
- 实现图片上传和管理功能
- 实现任务状态跟踪
- 支持数据库自动迁移
- 预留云端同步接口

### v1.1.0 (2025-06-20)
- 添加剪切板图片上传功能
- 添加文件上传功能
- 支持按分类保存图片（clothes/char）
- 优化图片接收接口，支持未登录用户
- 添加按分类获取图片文件的接口
- 增强错误处理和验证机制
- 更新API文档，添加新功能详细说明

### v1.2.0 (2025-06-25)
- 实现完整的云端同步功能
- 支持图片文件和元数据同步
- 添加同步状态跟踪和错误处理
- 优化异步处理机制
- 支持大文件上传和超时处理
- 更新云端同步相关API文档

### v1.3.0 (计划中)
- 添加图片编辑功能
- 支持批量操作
- 添加图片标签系统
- 优化缩略图生成
- 增强搜索和过滤功能
- 支持增量同步

---

## 测试与开发

### API测试工具
推荐使用以下工具进行API测试：
- **Postman**: 图形化接口测试
- **curl**: 命令行测试
- **Python requests**: 脚本化测试

### 开发环境设置
1. 确保Python 3.7+已安装
2. 安装依赖：`pip install flask requests pillow`
3. 启动服务器：`python app.py`
4. 访问WebUI：`http://localhost:8080`

### 调试技巧
- 查看服务器日志获取详细错误信息
- 使用浏览器开发者工具检查请求和响应
- 验证文件权限和目录结构
- 检查数据库状态和记录
- 监控云端同步日志
- 测试网络连接和超时处理
