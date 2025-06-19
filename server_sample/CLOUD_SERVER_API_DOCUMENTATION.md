# 云端同步服务器 API 文档

## 概述
本文档描述了云端同步服务器的所有API接口，基于 `server.py` 中实际实现的路由和处理方法。该服务器用于处理本地客户端的数据同步请求，包括用户管理、数据同步、状态查询等功能。

## 基础信息
- **服务器地址**: `http://localhost:8081`
- **数据格式**: JSON
- **认证方式**: 基于本地用户ID关联
- **字符编码**: UTF-8
- **超时设置**: 5分钟（300秒）

## 目录
1. [系统状态接口](#系统状态接口)
2. [用户管理接口](#用户管理接口)
3. [数据同步接口](#数据同步接口)
4. [状态查询接口](#状态查询接口)
5. [错误码说明](#错误码说明)
6. [数据存储说明](#数据存储说明)

---

## 系统状态接口

### 1. 获取云端服务器状态
获取云端服务器运行状态和基本信息。

**接口地址**：`GET /api/status`

**实现方法**：`cloud_status()`

**请求参数**：无

**请求示例**：
```http
GET /api/status HTTP/1.1
Host: localhost:8081
Content-Type: application/json
```

**响应示例**：
```json
{
  "status": "running",
  "service": "cloud_sync_server",
  "timestamp": "2025-06-25T10:30:45.123456",
  "version": "1.0.0"
}
```

**字段说明**：
- `status`: 服务器状态，固定值 "running"
- `service`: 服务名称，固定值 "cloud_sync_server"
- `timestamp`: 当前服务器时间（ISO格式）
- `version`: 服务器版本号

---

## 用户管理接口

### 2. 云端用户注册
在云端注册用户账户，关联本地用户ID。

**接口地址**：`POST /api/register`

**实现方法**：`cloud_register()`

**请求参数**：
```json
{
  "username": "string",        // 必填，用户名
  "email": "string",           // 必填，邮箱地址
  "password": "string",        // 必填，密码
  "local_user_id": "string"    // 可选，本地用户ID
}
```

**请求示例**：
```json
{
  "username": "testuser",
  "email": "test@example.com",
  "password": "password123",
  "local_user_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"
}
```

**响应示例**：
```json
{
  "success": true,
  "cloud_user_id": "c-12345678-90ab-cdef-1234-567890abcdef",
  "message": "云端注册成功"
}
```

**错误响应**：
```json
{
  "success": false,
  "error": "用户名或邮箱已存在"
}
```

**处理逻辑**：
1. 验证请求参数 `username`、`email`、`password` 的完整性
2. 调用 `cloud_db.create_user()` 检查用户名和邮箱是否已存在
3. 生成唯一的云端用户ID和密码哈希（SHA256）
4. 创建用户记录到 `cloud_users` 表
5. 创建用户云端存储目录结构：`cloud_data/users/{user_id}/{clothes,char}/`
6. 返回注册结果和云端用户ID

### 3. 云端用户登录验证
验证用户登录凭据。

**接口地址**：`POST /api/login`

**实现方法**：`cloud_login()`

**请求参数**：
```json
{
  "username": "string",    // 必填，用户名
  "password": "string"     // 必填，密码
}
```

**请求示例**：
```json
{
  "username": "testuser",
  "password": "password123"
}
```

**响应示例**：
```json
{
  "success": true,
  "cloud_user": {
    "user_id": "c-12345678-90ab-cdef-1234-567890abcdef",
    "username": "testuser",
    "email": "test@example.com",
    "local_user_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"
  },
  "message": "云端登录成功"
}
```

**错误响应**：
```json
{
  "success": false,
  "error": "用户名或密码错误"
}
```

**处理逻辑**：
1. 验证 `username` 和 `password` 参数
2. 计算密码的 SHA256 哈希值
3. 调用 `cloud_db.verify_user()` 查询数据库验证凭据
4. 返回用户信息（包括云端用户ID和关联的本地用户ID）

---

## 数据同步接口

### 4. 用户数据同步
接收并处理来自本地客户端的完整用户数据同步请求。这是核心同步接口。

**接口地址**：`POST /api/sync/user/{user_id}`

**实现方法**：`sync_user_data(user_id)`

**路径参数**：
- `user_id`: 本地用户ID（用于查找对应的云端用户）

**请求头**：
```http
Content-Type: application/json
```

**请求参数**：
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
```json
{
  "user_info": {
    "user_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "username": "testuser",
    "email": "test@example.com",
    "created_at": "2025-06-25 10:00:00",
    "last_login": "2025-06-25 14:30:00",
    "cloud_sync_enabled": true
  },
  "images_metadata": [
    {
      "id": "i-87654321-fedc-ba09-8765-432109876543",
      "user_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
      "filename": "clothes_20250625_143000_12345678.png",
      "original_url": "https://example.com/image.png",
      "page_url": "https://example.com/page",
      "page_title": "示例页面",
      "saved_at": "2025-06-25 14:30:00",
      "file_size": 245760,
      "image_width": 800,
      "image_height": 600,
      "context_info": {
        "category": "clothes",
        "alt": "示例图片"
      },
      "status": "saved",
      "cloud_synced": false
    }
  ],
  "image_files": {
    "clothes_20250625_143000_12345678.png": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."
  },
  "sync_timestamp": "2025-06-25T14:35:00.123456",
  "sync_statistics": {
    "total_metadata_records": 1,
    "total_files_found": 1,
    "total_files_missing": 0,
    "total_size": 245760,
    "categories": ["clothes"]
  }
}
```

**响应示例**：
```json
{
  "success": true,
  "message": "数据同步完成",
  "sync_result": {
    "sync_id": "s-abcdef12-3456-7890-abcd-ef1234567890",
    "cloud_user_id": "c-12345678-90ab-cdef-1234-567890abcdef",
    "total_images": 1,
    "saved_files": 1,
    "failed_files": 0,
    "total_size": 245760,
    "sync_timestamp": "2025-06-25T14:35:00.123456",
    "server_timestamp": "2025-06-25T14:35:05.987654",
    "status": "completed"
  }
}
```

**错误响应**：
```json
{
  "success": false,
  "error": "用户未在云端注册，请先注册",
  "timestamp": "2025-06-25T14:35:05.987654"
}
```

**详细处理逻辑**：

1. **用户验证**：
   - 调用 `cloud_db.get_user_by_local_id(user_id)` 查找对应的云端用户
   - 如果未找到，返回404错误要求先注册

2. **数据解析**：
   - 提取 `user_info`、`images_metadata`、`image_files`、`sync_statistics`
   - 记录同步数据的基本统计信息

3. **文件处理循环**：
   ```python
   for image_meta in images_metadata:
       filename = image_meta.get('filename')
       
       # 获取对应的图片文件数据
       image_file_data = image_files.get(filename)
       
       # 确定分类
       category = image_meta.get('context_info', {}).get('category', 'clothes')
       if filename.startswith('char_'):
           category = 'char'
       elif filename.startswith('clothes_'):
           category = 'clothes'
       
       # 保存图片文件
       if save_cloud_image_file(filename, image_file_data, cloud_user_id, category):
           # 保存图片元数据
           cloud_db.save_cloud_image(image_meta, cloud_user_id)
           saved_files += 1
   ```

4. **文件保存** (`save_cloud_image_file` 函数)：
   - 解析 base64 数据：`header, data = image_data_url.split(',', 1)`
   - 解码：`image_bytes = base64.b64decode(data)`
   - 保存到：`cloud_data/users/{cloud_user_id}/{category}/{filename}`

5. **元数据保存** (`cloud_db.save_cloud_image` 方法)：
   - 插入或替换 `cloud_images` 表记录
   - 包含图片ID、文件名、尺寸、分类等信息

6. **统计更新**：
   - 调用 `cloud_db.update_user_stats()` 更新用户的总图片数和存储大小
   - 更新 `cloud_users` 表的 `last_sync` 时间戳

7. **同步记录**：
   - 调用 `cloud_db.save_sync_record()` 记录本次同步结果
   - 状态：`completed`（全部成功）或 `partial`（部分失败）

**错误处理机制**：
- 单个文件失败不影响整体同步
- 详细的错误日志记录
- 失败统计包含在同步结果中

---

## 状态查询接口

### 5. 获取用户同步状态
查询用户的同步历史记录和状态信息。

**接口地址**：`GET /api/user/{user_id}/sync/status`

**实现方法**：`get_sync_status(user_id)`

**路径参数**：
- `user_id`: 本地用户ID

**请求参数**：无

**请求示例**：
```http
GET /api/user/f47ac10b-58cc-4372-a567-0e02b2c3d479/sync/status HTTP/1.1
Host: localhost:8081
```

**响应示例**：
```json
{
  "success": true,
  "cloud_user_id": "c-12345678-90ab-cdef-1234-567890abcdef",
  "sync_history": [
    {
      "sync_id": "s-abcdef12-3456-7890-abcd-ef1234567890",
      "sync_type": "full",
      "sync_timestamp": "2025-06-25 14:35:05",
      "images_count": 25,
      "total_size": 5242880,
      "status": "completed",
      "error_message": null
    },
    {
      "sync_id": "s-fedcba98-7654-3210-fedc-ba9876543210",
      "sync_type": "full",
      "sync_timestamp": "2025-06-24 10:20:30",
      "images_count": 20,
      "total_size": 4194304,
      "status": "partial",
      "error_message": "3 个文件同步失败"
    }
  ]
}
```

**错误响应**：
```json
{
  "success": false,
  "error": "用户未找到"
}
```

**处理逻辑**：
1. 通过 `cloud_db.get_user_by_local_id(user_id)` 查找云端用户
2. 查询 `sync_records` 表获取最近5条同步记录：
   ```sql
   SELECT sync_id, sync_type, sync_timestamp, images_count, total_size, status, error_message
   FROM sync_records 
   WHERE user_id = ? 
   ORDER BY sync_timestamp DESC 
   LIMIT 5
   ```
3. 格式化并返回同步历史数据

---

## 错误码说明

### HTTP状态码
- `200`: 请求成功
- `400`: 请求参数错误
- `401`: 用户认证失败
- `404`: 用户或资源不存在
- `500`: 服务器内部错误

### 业务错误码
响应JSON中的`error`字段包含具体错误信息：

#### 用户注册相关
- `"用户名、邮箱和密码不能为空"`: 注册时必填字段缺失
- `"用户名或邮箱已存在"`: 注册时用户名或邮箱冲突

#### 用户登录相关  
- `"用户名和密码不能为空"`: 登录时必填字段缺失
- `"用户名或密码错误"`: 登录凭据验证失败

#### 数据同步相关
- `"用户未在云端注册，请先注册"`: 同步时本地用户ID在云端不存在
- `"没有接收到同步数据"`: 同步请求体为空
- `"同步处理失败"`: 同步过程中发生异常

#### 状态查询相关
- `"用户未找到"`: 查询的用户不存在

#### 系统级错误
- `"无效的图片数据格式"`: 图片base64数据格式错误
- `"文件保存失败"`: 图片文件写入磁盘失败
- `"数据库操作失败"`: SQLite操作异常

---

## 数据存储说明

### 数据库结构

基于 `CloudDatabase` 类的实际实现：

#### 云端用户表 (cloud_users)
```sql
CREATE TABLE cloud_users (
    user_id TEXT PRIMARY KEY,           -- 云端用户ID (UUID)
    username TEXT UNIQUE NOT NULL,      -- 用户名
    email TEXT UNIQUE NOT NULL,         -- 邮箱
    password_hash TEXT NOT NULL,        -- 密码哈希(SHA256)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- 创建时间
    last_sync TIMESTAMP,                -- 最后同步时间
    is_active BOOLEAN DEFAULT 1,        -- 是否激活
    local_user_id TEXT,                 -- 关联的本地用户ID
    total_images INTEGER DEFAULT 0,     -- 图片总数
    total_storage_size INTEGER DEFAULT 0 -- 存储总大小(字节)
);
```

#### 云端图片表 (cloud_images)
```sql
CREATE TABLE cloud_images (
    id TEXT PRIMARY KEY,                -- 图片ID（与本地保持一致）
    user_id TEXT NOT NULL,              -- 云端用户ID
    filename TEXT NOT NULL,             -- 文件名
    original_url TEXT,                  -- 原始URL
    page_url TEXT,                      -- 页面URL
    page_title TEXT,                    -- 页面标题
    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,    -- 本地保存时间
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,   -- 云端同步时间
    file_size INTEGER,                  -- 文件大小
    image_width INTEGER,                -- 图片宽度
    image_height INTEGER,               -- 图片高度
    context_info TEXT,                  -- 上下文信息（JSON格式）
    category TEXT DEFAULT 'clothes',    -- 图片分类
    status TEXT DEFAULT 'synced',       -- 状态
    FOREIGN KEY (user_id) REFERENCES cloud_users (user_id)
);
```

#### 同步记录表 (sync_records)
```sql
CREATE TABLE sync_records (
    sync_id TEXT PRIMARY KEY,           -- 同步ID (UUID)
    user_id TEXT NOT NULL,              -- 云端用户ID
    sync_type TEXT DEFAULT 'full',      -- 同步类型
    sync_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- 同步时间
    images_count INTEGER DEFAULT 0,     -- 图片数量
    total_size INTEGER DEFAULT 0,       -- 总大小
    status TEXT DEFAULT 'completed',    -- 状态 (completed/partial/failed)
    error_message TEXT,                 -- 错误信息
    FOREIGN KEY (user_id) REFERENCES cloud_users (user_id)
);
```

### 文件存储结构

基于 `get_user_cloud_dir` 函数的实际实现：

```
cloud_data/
├── users/
│   ├── {cloud_user_id}/
│   │   ├── clothes/                    # 服装类图片
│   │   │   ├── clothes_20250625_143000_12345678.png
│   │   │   └── clothes_20250625_143001_87654321.jpg
│   │   └── char/                       # 角色类图片
│   │       ├── char_20250625_143002_abcdefgh.png
│   │       └── char_20250625_143003_ijklmnop.webp
├── cloud_database.db                   # SQLite数据库文件
└── logs/                              # 日志文件目录
```

### 核心处理函数

#### 用户目录管理
```python
def get_user_cloud_dir(user_id, category='clothes'):
    """获取用户云端存储目录"""
    user_dir = CLOUD_USERS_DIR / user_id
    user_dir.mkdir(exist_ok=True)
    
    category_dir = user_dir / category
    category_dir.mkdir(exist_ok=True)
    
    return category_dir
```

#### 图片文件保存
```python
def save_cloud_image_file(image_filename, image_data_url, user_id, category='clothes'):
    """保存图片文件到云端存储"""
    # 解析base64数据
    header, data = image_data_url.split(',', 1)
    image_bytes = base64.b64decode(data)
    
    # 获取云端存储目录并保存文件
    cloud_dir = get_user_cloud_dir(user_id, category)
    filepath = cloud_dir / image_filename
    
    with open(filepath, 'wb') as f:
        f.write(image_bytes)
```

---

## 部署说明

### 环境要求
- Python 3.7+
- Flask 2.0+
- SQLite 3.x
- 足够的磁盘存储空间

### 依赖安装
```bash
pip install flask pathlib logging hashlib secrets
```

### 启动命令
```bash
python server.py
```

### 配置项
```python
# 云端服务器配置
CLOUD_DATA_DIR = Path("cloud_data")           # 数据存储目录
CLOUD_DB_PATH = "cloud_database.db"           # 数据库文件路径
CLOUD_USERS_DIR = CLOUD_DATA_DIR / "users"    # 用户文件目录
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}  # 支持的文件格式

# 服务器配置
HOST = "localhost"    # 绑定地址
PORT = 8081          # 监听端口
DEBUG = True         # 调试模式
```

### 日志配置
```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
```

---

## 性能和限制

### 性能指标
- **单次同步容量**: 支持数百张图片
- **单个文件大小**: 建议不超过10MB
- **并发处理**: 单进程处理，适合小规模使用
- **数据库**: SQLite，适合中小型数据量

### 系统限制
- **存储空间**: 依赖服务器磁盘容量
- **内存使用**: base64解码时需要2-3倍文件大小的内存
- **网络传输**: 5分钟超时限制
- **文件格式**: 仅支持图片格式

### 扩展建议
- 使用更强大的数据库（PostgreSQL/MySQL）
- 实现文件分块上传
- 添加Redis缓存
- 支持多进程/多线程处理

---

## 安全考虑

### 已实现的安全措施
- 密码SHA256哈希存储
- 用户隔离的文件目录
- SQL参数化查询防注入

### 建议增强
- HTTPS支持
- API访问频率限制
- 文件类型严格验证
- 用户权限管理

---

## 测试验证

### 单元测试建议
```python
def test_cloud_register():
    # 测试用户注册功能
    
def test_sync_user_data():
    # 测试数据同步功能
    
def test_get_sync_status():
    # 测试状态查询功能
```

### 集成测试
使用提供的 `test_server.py` 进行完整测试：
```bash
python test_server.py
```

---

## 故障排除

### 常见问题

1. **数据库连接失败**
   - 检查 `cloud_database.db` 文件权限
   - 确认SQLite版本兼容性

2. **文件保存失败**
   - 检查 `cloud_data/users/` 目录权限
   - 验证磁盘剩余空间

3. **同步超时**
   - 检查网络连接稳定性
   - 减少单次同步的文件数量

4. **用户未找到错误**
   - 确认本地用户已在云端注册
   - 检查 `local_user_id` 关联关系

### 日志查看
服务器运行时会输出详细日志，包括：
- 同步请求处理过程
- 文件保存结果
- 错误异常信息
- 性能统计数据

---

## 版本更新

### v1.0.0 (当前版本)
- 实现基础的用户注册和登录
- 支持完整数据同步功能
- 提供同步状态查询
- 支持clothes和char分类
- 基于SQLite的数据存储

### 计划功能
- 增量同步支持
- 文件去重机制
- 压缩存储优化
- 多用户并发优化
- 管理员API接口
