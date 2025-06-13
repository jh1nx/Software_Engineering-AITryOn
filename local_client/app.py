from flask import Flask, request, jsonify, render_template, send_file, url_for, session
import os
import json
import base64
import uuid
import datetime
from pathlib import Path
import sqlite3
from werkzeug.utils import secure_filename
import requests
from urllib.parse import urlparse
import threading
import time
import hashlib
import secrets
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=7)  # 会话保持7天

# 配置
BASE_SAVE_DIR = Path("saved_images")
DB_PATH = "image_database.db"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
CLOUD_SERVER_URL = "https://your-cloud-server.com/api"  # 云端服务器地址
ENABLE_CLOUD_SYNC = False  # 禁用云端同步

# 确保保存目录存在
BASE_SAVE_DIR.mkdir(exist_ok=True)

class ImageDatabase:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 检查是否需要迁移数据库
        cursor.execute("PRAGMA table_info(images)")
        columns = [column[1] for column in cursor.fetchall()]
        needs_migration = 'user_id' not in columns
        
        if needs_migration:
            print("检测到旧版数据库，开始迁移...")
            self.migrate_database(cursor)
        
        # 创建用户表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                cloud_sync_enabled BOOLEAN DEFAULT 0,
                cloud_user_id TEXT
            )
        ''')
        
        # 创建新的图片表结构
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS images_new (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                original_url TEXT,
                page_url TEXT,
                page_title TEXT,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                file_size INTEGER,
                image_width INTEGER,
                image_height INTEGER,
                context_info TEXT,
                status TEXT DEFAULT 'saved',
                cloud_synced BOOLEAN DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # 如果需要迁移，复制数据并重命名表
        if needs_migration and cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='images'").fetchone()[0] > 0:
            # 创建默认用户用于旧数据
            default_user_id = self.create_default_user(cursor)
            
            # 迁移旧数据
            cursor.execute("SELECT * FROM images")
            old_images = cursor.fetchall()
            
            for row in old_images:
                if len(row) >= 11:  # 确保有足够的列
                    cursor.execute('''
                        INSERT OR IGNORE INTO images_new 
                        (id, user_id, filename, original_url, page_url, page_title, 
                         saved_at, file_size, image_width, image_height, context_info, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (row[0], default_user_id, row[1], row[2], row[3], row[4], 
                          row[5], row[6], row[7], row[8], row[9], row[10]))
            
            # 删除旧表，重命名新表
            cursor.execute("DROP TABLE IF EXISTS images")
            cursor.execute("ALTER TABLE images_new RENAME TO images")
            print("数据库迁移完成")
        else:
            # 如果表不存在或已经是新结构，删除临时表
            cursor.execute("DROP TABLE IF EXISTS images_new")
            # 确保images表存在
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    original_url TEXT,
                    page_url TEXT,
                    page_title TEXT,
                    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    file_size INTEGER,
                    image_width INTEGER,
                    image_height INTEGER,
                    context_info TEXT,
                    status TEXT DEFAULT 'saved',
                    cloud_synced BOOLEAN DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                status TEXT DEFAULT 'processing',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                image_id TEXT,
                FOREIGN KEY (image_id) REFERENCES images (id),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        conn.commit()
        conn.close()
    
    def migrate_database(self, cursor):
        """迁移旧数据库结构"""
        try:
            # 检查旧表结构
            cursor.execute("PRAGMA table_info(images)")
            print("旧表结构:", cursor.fetchall())
        except Exception as e:
            print(f"检查旧表结构失败: {e}")
    
    def create_default_user(self, cursor):
        """为旧数据创建默认用户"""
        default_user_id = "default-user-" + str(uuid.uuid4())[:8]
        default_password_hash = hashlib.sha256("admin123".encode()).hexdigest()
        
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, email, password_hash)
            VALUES (?, ?, ?, ?)
        ''', (default_user_id, "admin", "admin@local.com", default_password_hash))
        
        # 创建默认用户目录
        user_dir = BASE_SAVE_DIR / default_user_id
        user_dir.mkdir(exist_ok=True)
        
        # 移动旧图片到用户目录
        try:
            for file in BASE_SAVE_DIR.iterdir():
                if file.is_file() and file.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
                    new_path = user_dir / file.name
                    if not new_path.exists():
                        file.rename(new_path)
        except Exception as e:
            print(f"移动旧图片失败: {e}")
        
        print(f"创建默认用户: admin/admin123, ID: {default_user_id}")
        return default_user_id
    
    def create_user(self, username, email, password):
        """创建新用户"""
        user_id = str(uuid.uuid4())
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO users (user_id, username, email, password_hash)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, email, password_hash))
            conn.commit()
            
            # 创建用户专属目录
            user_dir = BASE_SAVE_DIR / user_id
            user_dir.mkdir(exist_ok=True)
            
            return user_id
        except sqlite3.IntegrityError as e:
            return None
        finally:
            conn.close()
    
    def verify_user(self, username, password):
        """验证用户登录"""
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_id, username, email FROM users 
            WHERE username = ? AND password_hash = ? AND is_active = 1
        ''', (username, password_hash))
        result = cursor.fetchone()
        
        if result:
            # 更新最后登录时间
            cursor.execute('''
                UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE user_id = ?
            ''', (result[0],))
            conn.commit()
        
        conn.close()
        return result
    
    def get_user_info(self, user_id):
        """获取用户信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_id, username, email, created_at, last_login, cloud_sync_enabled
            FROM users WHERE user_id = ?
        ''', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'user_id': result[0],
                'username': result[1],
                'email': result[2],
                'created_at': result[3],
                'last_login': result[4],
                'cloud_sync_enabled': bool(result[5])
            }
        return None
    
    def save_image_record(self, image_id, user_id, filename, original_url, page_info, file_size, width, height, context_info):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO images (id, user_id, filename, original_url, page_url, page_title, file_size, image_width, image_height, context_info)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (image_id, user_id, filename, original_url, page_info.get('url'), page_info.get('title'), file_size, width, height, json.dumps(context_info)))
        conn.commit()
        conn.close()
    
    def create_task(self, task_id, user_id, image_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO tasks (task_id, user_id, image_id) VALUES (?, ?, ?)
        ''', (task_id, user_id, image_id))
        conn.commit()
        conn.close()
    
    def update_task_status(self, task_id, status):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE tasks SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE task_id = ?
        ''', (status, task_id))
        conn.commit()
        conn.close()
    
    def get_task_status(self, task_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM tasks WHERE task_id = ?', (task_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                'task_id': result[0],
                'status': result[1],
                'created_at': result[2],
                'updated_at': result[3],
                'image_id': result[4]
            }
        return None
    
    def get_all_images(self, limit=50, offset=0):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM images ORDER BY saved_at DESC LIMIT ? OFFSET ?
        ''', (limit, offset))
        results = cursor.fetchall()
        conn.close()
        
        images = []
        for row in results:
            images.append({
                'id': row[0],
                'filename': row[1],
                'original_url': row[2],
                'page_url': row[3],
                'page_title': row[4],
                'saved_at': row[5],
                'file_size': row[6],
                'image_width': row[7],
                'image_height': row[8],
                'context_info': json.loads(row[9]) if row[9] else {},
                'status': row[10]
            })
        return images
    
    def get_user_images(self, user_id, limit=50, offset=0):
        """获取用户的图片列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM images WHERE user_id = ? ORDER BY saved_at DESC LIMIT ? OFFSET ?
        ''', (user_id, limit, offset))
        results = cursor.fetchall()
        conn.close()
        
        images = []
        for row in results:
            images.append({
                'id': row[0],
                'user_id': row[1],
                'filename': row[2],
                'original_url': row[3],
                'page_url': row[4],
                'page_title': row[5],
                'saved_at': row[6],
                'file_size': row[7],
                'image_width': row[8],
                'image_height': row[9],
                'context_info': json.loads(row[10]) if row[10] else {},
                'status': row[11],
                'cloud_synced': bool(row[12]) if len(row) > 12 else False
            })
        return images
    
    def get_image_count(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM images')
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    def get_user_image_count(self, user_id):
        """获取用户图片数量"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM images WHERE user_id = ?', (user_id,))
        count = cursor.fetchone()[0]
        conn.close()
        return count

# 初始化数据库
db = ImageDatabase(DB_PATH)

# 云端服务器通信类
class CloudServerClient:
    def __init__(self, server_url, enabled=True):
        self.server_url = server_url
        self.enabled = enabled
        self.session = requests.Session() if enabled else None
    
    def register_user(self, username, email, password):
        """在云端注册用户"""
        if not self.enabled:
            return {'success': True, 'message': '云端同步已禁用'}
        
        try:
            response = self.session.post(f"{self.server_url}/register", json={
                'username': username,
                'email': email,
                'password': password
            }, timeout=10)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"云端注册失败: {e}")
            return None
    
    def login_user(self, username, password):
        """云端用户登录"""
        if not self.enabled:
            return {'success': True, 'message': '云端同步已禁用'}
        
        try:
            response = self.session.post(f"{self.server_url}/login", json={
                'username': username,
                'password': password
            }, timeout=10)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"云端登录失败: {e}")
            return None
    
    def sync_user_data(self, user_id, user_data):
        """同步用户数据到云端"""
        if not self.enabled:
            return {'success': True, 'message': '云端同步已禁用'}
        
        try:
            response = self.session.post(f"{self.server_url}/sync/user/{user_id}", 
                                       json=user_data, timeout=30)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"数据同步失败: {e}")
            return None

cloud_client = CloudServerClient(CLOUD_SERVER_URL, ENABLE_CLOUD_SYNC)

# 登录验证装饰器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': '需要登录'}), 401
        return f(*args, **kwargs)
    return decorated_function

# 检查登录状态的API
@app.route('/api/auth/check', methods=['GET'])
def check_auth():
    """检查登录状态"""
    if 'user_id' in session:
        user_info = db.get_user_info(session['user_id'])
        if user_info:
            return jsonify({
                'authenticated': True,
                'user': user_info
            })
    
    return jsonify({'authenticated': False})

def get_user_save_dir(user_id):
    """获取用户专属保存目录"""
    user_dir = BASE_SAVE_DIR / user_id
    user_dir.mkdir(exist_ok=True)
    return user_dir

def save_image_from_data(image_data, original_url, page_info, user_id):
    """保存图片数据到用户目录"""
    try:
        image_id = str(uuid.uuid4())
        user_save_dir = get_user_save_dir(user_id)
        
        # 处理base64图片数据
        if image_data.startswith('data:image'):
            header, data = image_data.split(',', 1)
            image_bytes = base64.b64decode(data)
            # 从header中获取图片格式
            if 'png' in header:
                ext = 'png'
            elif 'jpeg' in header or 'jpg' in header:
                ext = 'jpg'
            elif 'gif' in header:
                ext = 'gif'
            else:
                ext = 'png'
        else:
            # 如果是URL，尝试下载
            try:
                response = requests.get(image_data, timeout=10)
                image_bytes = response.content
                # 从URL或Content-Type推断格式
                content_type = response.headers.get('content-type', '')
                if 'png' in content_type:
                    ext = 'png'
                elif 'jpeg' in content_type or 'jpg' in content_type:
                    ext = 'jpg'
                elif 'gif' in content_type:
                    ext = 'gif'
                else:
                    ext = 'png'
            except Exception as e:
                print(f"下载图片失败: {e}")
                return None
        
        # 生成文件名
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{image_id[:8]}.{ext}"
        filepath = user_save_dir / filename
        
        # 保存文件
        with open(filepath, 'wb') as f:
            f.write(image_bytes)
        
        # 获取图片尺寸
        try:
            from PIL import Image
            with Image.open(filepath) as img:
                width, height = img.size
        except Exception:
            width, height = 0, 0
        
        # 保存到数据库
        file_size = len(image_bytes)
        context_info = page_info.get('imageContext', {}) if page_info else {}
        
        db.save_image_record(
            image_id, user_id, filename, original_url, page_info or {}, 
            file_size, width, height, context_info
        )
        
        return {
            'image_id': image_id,
            'filename': filename,
            'filepath': str(filepath),
            'file_size': file_size,
            'dimensions': (width, height)
        }
        
    except Exception as e:
        print(f"保存图片失败: {e}")
        return None

# API路由
@app.route('/api/status', methods=['GET'])
def get_status():
    """获取服务器状态"""
    return jsonify({
        'status': 'running',
        'timestamp': datetime.datetime.now().isoformat(),
        'total_images': db.get_image_count()
    })

@app.route('/api/receive-image', methods=['POST'])
@login_required
def receive_image():
    """接收浏览器插件发送的图片"""
    try:
        data = request.get_json()
        user_id = session['user_id']
        
        image_data = data.get('imageData')
        original_url = data.get('originalUrl')
        page_info = data.get('pageInfo', {})
        
        if not image_data:
            return jsonify({'success': False, 'error': '缺少图片数据'}), 400
        
        # 保存图片
        result = save_image_from_data(image_data, original_url, page_info, user_id)
        
        if result:
            # 创建任务
            task_id = str(uuid.uuid4())
            db.create_task(task_id, user_id, result['image_id'])
            
            # 模拟异步处理
            def process_task():
                db.update_task_status(task_id, 'completed')
            
            thread = threading.Thread(target=process_task)
            thread.start()
            
            return jsonify({
                'success': True,
                'taskId': task_id,
                'imageId': result['image_id'],
                'filename': result['filename'],
                'fileSize': result['file_size']
            })
        else:
            return jsonify({'success': False, 'error': '保存图片失败'}), 500
            
    except Exception as e:
        print(f"处理请求失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/task/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """获取任务状态"""
    task = db.get_task_status(task_id)
    if task:
        return jsonify({'status': task})
    else:
        return jsonify({'error': '任务不存在'}), 404

@app.route('/api/images', methods=['GET'])
def get_images():
    """获取图片列表"""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    offset = (page - 1) * per_page
    
    images = db.get_all_images(per_page, offset)
    total = db.get_image_count()
    
    # 为每个图片添加预览URL
    for image in images:
        image['preview_url'] = url_for('serve_image', filename=image['filename'])
        image['thumbnail_url'] = url_for('serve_thumbnail', filename=image['filename'])
    
    return jsonify({
        'images': images,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page
    })

@app.route('/api/user/images', methods=['GET'])
@login_required
def get_user_images():
    """获取用户图片列表"""
    user_id = session['user_id']
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    offset = (page - 1) * per_page
    
    images = db.get_user_images(user_id, per_page, offset)
    total = db.get_user_image_count(user_id)
    
    # 为每个图片添加预览URL
    for image in images:
        image['preview_url'] = url_for('serve_user_image', user_id=user_id, filename=image['filename'])
        image['thumbnail_url'] = url_for('serve_user_thumbnail', user_id=user_id, filename=image['filename'])
    
    return jsonify({
        'images': images,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page
    })

@app.route('/api/images/<filename>')
def serve_image(filename):
    """提供图片文件"""
    filepath = SAVE_DIR / filename
    if filepath.exists():
        return send_file(filepath)
    else:
        return "图片不存在", 404

@app.route('/api/thumbnails/<filename>')
def serve_thumbnail(filename):
    """提供缩略图"""
    # 简单实现：直接返回原图，实际可以生成缩略图
    return serve_image(filename)

@app.route('/api/user/<user_id>/images/<filename>')
@login_required
def serve_user_image(user_id, filename):
    """提供用户图片文件"""
    # 验证用户只能访问自己的图片
    if session['user_id'] != user_id:
        return jsonify({'error': '权限不足'}), 403
    
    user_save_dir = get_user_save_dir(user_id)
    filepath = user_save_dir / filename
    if filepath.exists():
        return send_file(filepath)
    else:
        return "图片不存在", 404

@app.route('/api/user/<user_id>/thumbnails/<filename>')
@login_required
def serve_user_thumbnail(user_id, filename):
    """提供用户缩略图"""
    return serve_user_image(user_id, filename)

# Web界面路由
@app.route('/')
def index():
    """主页面"""
    return render_template('index.html')

@app.route('/images')
def images_page():
    """图片展示页面"""
    return render_template('images.html')

# 用户认证API
@app.route('/api/register', methods=['POST'])
def register():
    """用户注册"""
    try:
        data = request.get_json()
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        
        if not all([username, email, password]):
            return jsonify({'success': False, 'error': '用户名、邮箱和密码不能为空'}), 400
        
        # 本地注册
        user_id = db.create_user(username, email, password)
        if not user_id:
            return jsonify({'success': False, 'error': '用户名或邮箱已存在'}), 400
        
        # 尝试云端注册（仅在启用时）
        if ENABLE_CLOUD_SYNC:
            def cloud_register():
                cloud_result = cloud_client.register_user(username, email, password)
                if cloud_result:
                    print(f"用户 {username} 已同步到云端")
            
            threading.Thread(target=cloud_register).start()
        
        return jsonify({
            'success': True,
            'user_id': user_id,
            'message': '注册成功'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/login', methods=['POST'])
def login():
    """用户登录"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        remember_me = data.get('remember_me', False)
        
        if not all([username, password]):
            return jsonify({'success': False, 'error': '用户名和密码不能为空'}), 400
        
        # 本地验证
        user_result = db.verify_user(username, password)
        if not user_result:
            return jsonify({'success': False, 'error': '用户名或密码错误'}), 401
        
        user_id, username, email = user_result
        
        # 设置会话
        session.permanent = remember_me
        session['user_id'] = user_id
        session['username'] = username
        
        # 尝试云端登录（仅在启用时）
        if ENABLE_CLOUD_SYNC:
            def cloud_login():
                cloud_result = cloud_client.login_user(username, password)
                if cloud_result:
                    print(f"用户 {username} 云端登录成功")
            
            threading.Thread(target=cloud_login).start()
        
        return jsonify({
            'success': True,
            'user': {
                'user_id': user_id,
                'username': username,
                'email': email
            },
            'message': '登录成功'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    """用户登出"""
    session.clear()
    return jsonify({'success': True, 'message': '登出成功'})

@app.route('/api/user/profile', methods=['GET'])
@login_required
def get_user_profile():
    """获取用户信息"""
    user_id = session['user_id']
    user_info = db.get_user_info(user_id)
    if user_info:
        user_info['image_count'] = db.get_user_image_count(user_id)
        return jsonify({'success': True, 'user': user_info})
    else:
        return jsonify({'success': False, 'error': '用户不存在'}), 404

# 云端同步API
@app.route('/api/cloud/sync', methods=['POST'])
@login_required
def sync_to_cloud():
    """同步数据到云端"""
    if not ENABLE_CLOUD_SYNC:
        return jsonify({'success': False, 'error': '云端同步功能已禁用'}), 400
    
    try:
        user_id = session['user_id']
        user_info = db.get_user_info(user_id)
        user_images = db.get_user_images(user_id, limit=1000)  # 获取所有图片
        
        sync_data = {
            'user_info': user_info,
            'images': user_images,
            'sync_timestamp': datetime.datetime.now().isoformat()
        }
        
        def sync_task():
            result = cloud_client.sync_user_data(user_id, sync_data)
            if result:
                print(f"用户 {user_id} 数据同步成功")
        
        threading.Thread(target=sync_task).start()
        
        return jsonify({'success': True, 'message': '同步任务已启动'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    print("启动图片处理服务器...")
    print(f"保存目录: {BASE_SAVE_DIR.absolute()}")
    print(f"数据库: {DB_PATH}")
    print(f"云端同步: {'启用' if ENABLE_CLOUD_SYNC else '禁用'}")
    print("WebUI地址: http://localhost:8080")
    app.run(host='localhost', port=8080, debug=True)
