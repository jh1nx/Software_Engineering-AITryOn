# 图片处理服务器 API 文档

## 概述
本文档描述了图片处理服务器的所有API接口，包括用户认证、图片管理、系统状态等功能。

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

**认证要求**：需要登录

**请求参数**：
```json
{
  "imageData": "string",     // 必填，图片数据（base64或URL）
  "originalUrl": "string",   // 可选，图片原始URL
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
  "filename": "20250613_184530_87654321.png",
  "fileSize": 245760
}
```

### 8. 获取用户图片列表
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
      "filename": "20250613_184530_87654321.png",
      "original_url": "https://example.com/image.png",
      "page_url": "https://example.com/page",
      "page_title": "示例页面",
      "saved_at": "2025-06-13 18:45:30",
      "file_size": 245760,
      "image_width": 800,
      "image_height": 600,
      "context_info": {
        "alt": "示例图片",
        "caption": "这是一张示例图片"
      },
      "status": "saved",
      "cloud_synced": false,
      "preview_url": "/api/user/default-user-12345678/images/20250613_184530_87654321.png",
      "thumbnail_url": "/api/user/default-user-12345678/thumbnails/20250613_184530_87654321.png"
    }
  ],
  "total": 25,
  "page": 1,
  "per_page": 10,
  "pages": 3
}
```

### 9. 获取用户图片文件
获取用户的具体图片文件。

**接口地址**：`GET /api/user/{user_id}/images/{filename}`

**认证要求**：需要登录（只能访问自己的图片）

**请求示例**：
```http
GET /api/user/default-user-12345678/images/20250613_184530_87654321.png HTTP/1.1
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

### 10. 获取用户缩略图
获取用户图片的缩略图。

**接口地址**：`GET /api/user/{user_id}/thumbnails/{filename}`

**认证要求**：需要登录（只能访问自己的图片）

**请求示例**：
```http
GET /api/user/default-user-12345678/thumbnails/20250613_184530_87654321.png HTTP/1.1
Host: localhost:8080
Cookie: session=...
```

**响应**：返回缩略图文件二进制数据（当前实现返回原图）

---

## 任务管理接口

### 11. 获取任务状态
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

### 12. 同步数据到云端
将用户数据同步到云端服务器（当前已禁用）。

**接口地址**：`POST /api/cloud/sync`

**认证要求**：需要登录

**请求参数**：无

**响应示例**：
```json
{
  "success": false,
  "error": "云端同步功能已禁用"
}
```

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
- `"保存图片失败"`: 图片保存过程中出错
- `"任务不存在"`: 查询的任务ID不存在
- `"图片不存在"`: 请求的图片文件不存在
- `"云端同步功能已禁用"`: 云端同步功能未启用

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

4. **获取用户资料**
```bash
curl -X GET http://localhost:8080/api/user/profile \
  -b cookies.txt
```

5. **获取图片列表**
```bash
curl -X GET "http://localhost:8080/api/user/images?per_page=5" \
  -b cookies.txt
```

6. **上传图片**
```bash
curl -X POST http://localhost:8080/api/receive-image \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "imageData": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "originalUrl": "https://example.com/test.png",
    "pageInfo": {
      "url": "https://example.com",
      "title": "测试页面"
    }
  }'
```

7. **下载图片**
```bash
curl -X GET "http://localhost:8080/api/user/{user_id}/images/{filename}" \
  -b cookies.txt \
  -o downloaded_image.png
```

8. **用户登出**
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
  "filename": "string",          // 文件名
  "original_url": "string",      // 原始URL
  "page_url": "string",          // 来源页面URL
  "page_title": "string",        // 来源页面标题
  "saved_at": "datetime",        // 保存时间
  "file_size": "integer",        // 文件大小（字节）
  "image_width": "integer",      // 图片宽度
  "image_height": "integer",     // 图片高度
  "context_info": "object",      // 上下文信息
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
  "status": "string",            // 任务状态（processing/completed）
  "created_at": "datetime",      // 创建时间
  "updated_at": "datetime",      // 更新时间
  "image_id": "string"           // 关联图片ID
}
```

---

## 注意事项

1. **会话管理**: 使用Cookie进行会话管理，登录后需要在后续请求中携带Cookie
2. **权限控制**: 用户只能访问自己的图片和数据
3. **文件存储**: 每个用户的图片存储在独立的目录中
4. **数据库迁移**: 系统会自动检测并迁移旧版本的数据库结构
5. **云端同步**: 当前版本云端同步功能已禁用
6. **图片格式**: 支持PNG、JPG、JPEG、GIF、WEBP格式
7. **文件大小**: 目前无文件大小限制，建议合理使用

---

## 更新日志

### v1.0.0 (2025-06-13)
- 初始版本发布
- 实现用户认证系统
- 实现图片上传和管理功能
- 实现任务状态跟踪
- 支持数据库自动迁移
- 预留云端同步接口
