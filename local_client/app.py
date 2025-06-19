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
CLOUD_SERVER_URL = "http://localhost:8081/api"  # 修改为本地测试服务器
ENABLE_CLOUD_SYNC = True  # 启用云端同步进行测试

# 确保保存目录存在
BASE_SAVE_DIR.mkdir(exist_ok=True)

class ImageDatabase:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
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
        
        # 创建图片表
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
        
        # 创建任务表
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
        try:
            cursor.execute('''
                INSERT INTO tasks (task_id, user_id, image_id, status, created_at, updated_at) 
                VALUES (?, ?, ?, 'processing', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ''', (task_id, user_id, image_id))
            conn.commit()
        except Exception as e:
            print(f"创建任务失败: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def update_task_status(self, task_id, status):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                UPDATE tasks SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE task_id = ?
            ''', (status, task_id))
            if cursor.rowcount == 0:
                print(f"警告: 任务 {task_id} 不存在")
            conn.commit()
        except Exception as e:
            print(f"更新任务状态失败: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def get_task_status(self, task_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT task_id, user_id, status, created_at, updated_at, image_id FROM tasks WHERE task_id = ?', (task_id,))
            result = cursor.fetchone()
            if result:
                return {
                    'task_id': result[0],
                    'user_id': result[1],
                    'status': result[2],
                    'created_at': result[3],
                    'updated_at': result[4],
                    'image_id': result[5]
                }
            return None
        except Exception as e:
            print(f"获取任务状态失败: {e}")
            return None
        finally:
            conn.close()

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
    
    def register_user(self, username, email, password, local_user_id=None):
        """在云端注册用户"""
        if not self.enabled:
            return {'success': True, 'message': '云端同步已禁用'}
        
        try:
            response = self.session.post(f"{self.server_url}/register", json={
                'username': username,
                'email': email,
                'password': password,
                'local_user_id': local_user_id  # 添加本地用户ID
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
        """同步用户数据到云端，包括所有图片文件"""
        if not self.enabled:
            return {'success': True, 'message': '云端同步已禁用'}
        
        try:
            print(f"开始同步用户 {user_id} 的数据和图片...")
            
            # 获取用户目录路径
            user_dir = BASE_SAVE_DIR / user_id
            if not user_dir.exists():
                print(f"用户目录不存在: {user_dir}")
                return {'success': False, 'error': '用户目录不存在'}
            
            # 从user_data中获取图片列表
            images_metadata = user_data.get('images', [])
            print(f"从数据库获取到 {len(images_metadata)} 个图片记录")
            
            # 收集所有图片文件的base64数据
            image_files = {}
            total_files = 0
            total_size = 0
            processed_files = 0
            failed_files = 0
            
            for image_meta in images_metadata:
                filename = image_meta.get('filename')
                if not filename:
                    print(f"跳过无文件名的图片记录: {image_meta.get('id', 'unknown')}")
                    continue
                
                # 从文件名推断分类
                category = 'clothes'  # 默认分类
                if filename.startswith('char_'):
                    category = 'char'
                elif filename.startswith('clothes_'):
                    category = 'clothes'
                
                # 构造文件路径
                category_dir = user_dir / category
                filepath = category_dir / filename
                
                # 如果在推断的分类目录中找不到，尝试另一个分类目录
                if not filepath.exists():
                    other_category = 'char' if category == 'clothes' else 'clothes'
                    other_category_dir = user_dir / other_category
                    alt_filepath = other_category_dir / filename
                    if alt_filepath.exists():
                        filepath = alt_filepath
                        category = other_category
                        print(f"在 {other_category} 目录中找到文件: {filename}")
                
                # 检查文件是否存在
                if not filepath.exists():
                    print(f"警告: 图片文件不存在: {filepath}")
                    failed_files += 1
                    continue
                
                try:
                    # 读取图片文件并转换为base64
                    with open(filepath, 'rb') as f:
                        file_content = f.read()
                    
                    # 转换为base64
                    file_base64 = base64.b64encode(file_content).decode('utf-8')
                    
                    # 确定MIME类型
                    file_ext = filepath.suffix.lower()
                    mime_types = {
                        '.png': 'image/png',
                        '.jpg': 'image/jpeg',
                        '.jpeg': 'image/jpeg',
                        '.gif': 'image/gif',
                        '.webp': 'image/webp'
                    }
                    mime_type = mime_types.get(file_ext, 'image/jpeg')
                    
                    # 构造完整的data URL
                    image_data_url = f"data:{mime_type};base64,{file_base64}"
                    
                    # 只存储base64数据，使用filename作为key
                    image_files[filename] = image_data_url
                    
                    total_files += 1
                    total_size += len(file_content)
                    processed_files += 1
                    
                    print(f"已处理图片: {filename} ({len(file_content)} bytes)")
                    
                except Exception as e:
                    print(f"处理图片文件失败 {filepath}: {e}")
                    failed_files += 1
                    continue
            
            print(f"图片处理完成: 成功 {processed_files} 个，失败 {failed_files} 个，总大小: {total_size / 1024 / 1024:.2f} MB")
            
            # 构造完整的同步数据
            sync_payload = {
                'user_info': user_data.get('user_info', {}),
                'images_metadata': images_metadata,
                'image_files': image_files,
                'sync_timestamp': datetime.datetime.now().isoformat(),
                'sync_statistics': {
                    'total_metadata_records': len(images_metadata),
                    'total_files_found': processed_files,
                    'total_files_missing': failed_files,
                    'total_size': total_size,
                    'categories': list(set([
                        'char' if img.get('filename', '').startswith('char_') else 'clothes' 
                        for img in images_metadata if img.get('filename')
                    ])) if images_metadata else []
                }
            }
            
            print(f"开始上传到云端服务器: {self.server_url}/sync/user/{user_id}")
            
            # 由于数据可能很大，增加超时时间
            response = self.session.post(
                f"{self.server_url}/sync/user/{user_id}", 
                json=sync_payload, 
                timeout=300,  # 5分钟超时
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"同步成功: {result}")
                return result
            else:
                print(f"同步失败，状态码: {response.status_code}, 响应: {response.text}")
                return {
                    'success': False, 
                    'error': f'云端响应错误: {response.status_code}',
                    'response_text': response.text[:500]  # 只返回前500字符避免日志过长
                }
                
        except requests.exceptions.Timeout:
            print("同步超时")
            return {'success': False, 'error': '同步请求超时'}
        except requests.exceptions.RequestException as e:
            print(f"网络请求失败: {e}")
            return {'success': False, 'error': f'网络请求失败: {str(e)}'}
        except Exception as e:
            print(f"数据同步失败: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': f'同步过程中发生错误: {str(e)}'}

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

def get_user_save_dir(user_id, category='clothes'):
    """获取用户专属保存目录，支持分类"""
    user_dir = BASE_SAVE_DIR / user_id
    user_dir.mkdir(exist_ok=True)
    
    # 创建分类子目录
    category_dir = user_dir / category
    category_dir.mkdir(exist_ok=True)
    
    return category_dir

def get_or_create_default_user():
    """获取或创建默认用户，用于未登录用户"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 查找默认用户
    cursor.execute("SELECT user_id FROM users WHERE username = 'default_user' LIMIT 1")
    result = cursor.fetchone()
    
    if result:
        conn.close()
        return result[0]
    
    # 创建默认用户
    default_user_id = "default-user-" + str(uuid.uuid4())[:8]
    cursor.execute('''
        INSERT INTO users (user_id, username, email, password_hash, is_active)
        VALUES (?, ?, ?, ?, ?)
    ''', (default_user_id, 'default_user', 'default@local.app', 'default_hash', 1))
    
    conn.commit()
    conn.close()
    
    # 创建默认用户目录
    default_dir = BASE_SAVE_DIR / default_user_id
    default_dir.mkdir(exist_ok=True)
    (default_dir / "clothes").mkdir(exist_ok=True)
    
    return default_user_id

def save_image_from_data(image_data, original_url, page_info, user_id, category='clothes'):
    """保存图片数据到用户目录的指定分类文件夹"""
    try:
        print(f"开始保存图片: 用户ID={user_id}, 分类={category}")
        
        image_id = str(uuid.uuid4())
        user_save_dir = get_user_save_dir(user_id, category)
        
        print(f"保存目录: {user_save_dir}")
        
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
            elif 'webp' in header:
                ext = 'webp'
            else:
                ext = 'png'
            print(f"Base64图片格式: {ext}, 数据大小: {len(image_bytes)} bytes")
        else:
            # 如果是URL，尝试下载
            try:
                print(f"从URL下载图片: {image_data}")
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
                elif 'webp' in content_type:
                    ext = 'webp'
                else:
                    ext = 'png'
                print(f"下载完成: {ext}, 数据大小: {len(image_bytes)} bytes")
            except Exception as e:
                print(f"下载图片失败: {e}")
                return None
        
        # 生成文件名
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{category}_{timestamp}_{image_id[:8]}.{ext}"
        filepath = user_save_dir / filename
        
        print(f"生成文件名: {filename}")
        
        # 保存文件
        with open(filepath, 'wb') as f:
            f.write(image_bytes)
        
        print(f"文件保存成功: {filepath}")
        
        # 获取图片尺寸
        try:
            from PIL import Image
            with Image.open(filepath) as img:
                width, height = img.size
            print(f"图片尺寸: {width}x{height}")
        except Exception as e:
            print(f"获取图片尺寸失败: {e}")
            width, height = 0, 0
        
        # 保存到数据库，添加分类信息
        file_size = len(image_bytes)
        context_info = page_info.get('imageContext', {}) if page_info else {}
        context_info['category'] = category  # 添加分类信息
        
        print(f"保存数据库记录: ID={image_id}, 文件名={filename}")
        
        db.save_image_record(
            image_id, user_id, filename, original_url, page_info or {}, 
            file_size, width, height, context_info
        )
        
        result = {
            'image_id': image_id,
            'filename': filename,
            'filepath': str(filepath),
            'file_size': file_size,
            'dimensions': (width, height),
            'category': category
        }
        
        print(f"保存完成: {result}")
        return result
        
    except Exception as e:
        print(f"保存图片失败: {e}")
        import traceback
        traceback.print_exc()
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
def receive_image():
    """接收浏览器插件发送的图片（支持未登录用户）"""
    try:
        data = request.get_json()
        
        # 检查用户是否登录，如果没有登录则使用默认用户
        user_id = session.get('user_id')
        if not user_id:
            user_id = get_or_create_default_user()
            print(f"未登录用户，使用默认用户ID: {user_id}")
        
        image_data = data.get('imageData')
        original_url = data.get('originalUrl')
        page_info = data.get('pageInfo', {})
        category = data.get('category', 'clothes')  # 默认保存到clothes文件夹
        
        if not image_data:
            return jsonify({'success': False, 'error': '缺少图片数据'}), 400
        
        # 验证分类参数
        if category not in ['clothes', 'char']:
            category = 'clothes'
        
        # 保存图片到指定分类文件夹
        result = save_image_from_data(image_data, original_url, page_info, user_id, category)
        
        if result:
            # 创建任务
            task_id = str(uuid.uuid4())
            db.create_task(task_id, user_id, result['image_id'])
            
            # 模拟异步处理
            def process_task():
                db.update_task_status(task_id, 'completed')
            
            thread = threading.Thread(target=process_task)
            thread.start()
            
            response_data = {
                'success': True,
                'taskId': task_id,
                'imageId': result['image_id'],
                'filename': result['filename'],
                'fileSize': result['file_size'],
                'category': result['category'],
                'isLoggedIn': 'user_id' in session
            }
            
            if 'user_id' not in session:
                response_data['message'] = f'图片已保存到默认目录的{category}文件夹，建议登录以便管理您的图片'
            
            return jsonify(response_data)
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

@app.route('/api/user/<user_id>/images/<filename>')
def serve_user_image(user_id, filename):
    """提供用户图片文件（移除登录要求以支持默认用户）"""
    # 如果是登录用户，验证权限
    if 'user_id' in session and session['user_id'] != user_id:
        return jsonify({'error': '权限不足'}), 403
    
    # 从文件名推断分类
    category = 'clothes'  # 默认分类
    if filename.startswith('char_'):
        category = 'char'
    elif filename.startswith('clothes_'):
        category = 'clothes'
    
    user_save_dir = get_user_save_dir(user_id, category)
    filepath = user_save_dir / filename
    
    # 如果在默认分类中找不到，尝试在另一个分类中查找
    if not filepath.exists():
        other_category = 'char' if category == 'clothes' else 'clothes'
        user_save_dir = get_user_save_dir(user_id, other_category)
        filepath = user_save_dir / filename
    
    if filepath.exists():
        return send_file(filepath)
    else:
        return "图片不存在", 404

@app.route('/api/thumbnails/<filename>')
def serve_thumbnail(filename):
    """提供缩略图"""
    # 简单实现：直接返回原图，实际可以生成缩略图
    return serve_image(filename)

@app.route('/api/user/<user_id>/thumbnails/<filename>')
def serve_user_thumbnail(user_id, filename):
    """提供用户缩略图（移除登录要求以支持默认用户）"""
    return serve_user_image(user_id, filename)

@app.route('/api/user/<user_id>/images/<category>/<filename>')
def serve_user_image_by_category(user_id, category, filename):
    """按分类提供用户图片文件"""
    # 如果是登录用户，验证权限
    if 'user_id' in session and session['user_id'] != user_id:
        return jsonify({'error': '权限不足'}), 403
    
    # 验证分类参数
    if category not in ['clothes', 'char']:
        return jsonify({'error': '无效的分类'}), 400
    
    user_save_dir = get_user_save_dir(user_id, category)
    filepath = user_save_dir / filename
    if filepath.exists():
        return send_file(filepath)
    else:
        return "图片不存在", 404

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
        
        # 尝试云端注册（仅在启用时），传递本地用户ID
        if ENABLE_CLOUD_SYNC:
            def cloud_register():
                cloud_result = cloud_client.register_user(username, email, password, user_id)
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
                cloud_client.login_user(username, password)
            
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
        print(f"开始同步用户 {user_id} 的数据...")
        
        # 获取用户信息和图片元数据
        user_info = db.get_user_info(user_id)
        user_images = db.get_user_images(user_id, limit=10000)  # 获取所有图片元数据
        
        sync_data = {
            'user_info': user_info,
            'images': user_images,
            'sync_timestamp': datetime.datetime.now().isoformat()
        }
        
        print(f"准备同步: 用户信息={bool(user_info)}, 图片数量={len(user_images)}")
        
        def sync_task():
            try:
                print("开始异步同步任务...")
                result = cloud_client.sync_user_data(user_id, sync_data)
                if result and result.get('success'):
                    print(f"用户 {user_id} 数据同步成功: {result}")
                    
                    # 可选：更新本地数据库标记为已同步
                    # 这里可以添加更新图片cloud_synced状态的逻辑
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    try:
                        cursor.execute('''
                            UPDATE images SET cloud_synced = 1 
                            WHERE user_id = ? AND cloud_synced = 0
                        ''', (user_id,))
                        conn.commit()
                        print(f"已标记用户 {user_id} 的图片为云端已同步")
                    except Exception as e:
                        print(f"更新同步状态失败: {e}")
                    finally:
                        conn.close()
                        
                else:
                    print(f"用户 {user_id} 数据同步失败: {result}")
                    
            except Exception as e:
                print(f"同步任务执行失败: {e}")
                import traceback
                traceback.print_exc()
        
        # 启动异步同步任务
        threading.Thread(target=sync_task, daemon=True).start()
        
        return jsonify({
            'success': True, 
            'message': '同步任务已启动',
            'sync_info': {
                'user_id': user_id,
                'image_count': len(user_images),
                'estimated_time': f"{len(user_images) * 0.1:.1f}秒"  # 估算时间
            }
        })
        
    except Exception as e:
        print(f"启动同步任务失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/upload-clipboard', methods=['POST'])
def upload_clipboard():
    """从剪切板上传图片"""
    try:
        print("收到剪切板上传请求")
        data = request.get_json()
        
        if not data:
            print("错误: 没有接收到JSON数据")
            return jsonify({'success': False, 'error': '没有接收到数据'}), 400
        
        # 检查用户是否登录，如果没有登录则使用默认用户
        user_id = session.get('user_id')
        if not user_id:
            user_id = get_or_create_default_user()
            print(f"未登录用户，使用默认用户ID: {user_id}")
        else:
            print(f"登录用户ID: {user_id}")
        
        image_data = data.get('imageData')
        category = data.get('category', 'clothes')
        
        print(f"接收到参数: category={category}, imageData长度={len(image_data) if image_data else 0}")
        
        if not image_data:
            print("错误: 剪切板中没有图片数据")
            return jsonify({'success': False, 'error': '剪切板中没有图片数据'}), 400
        
        # 验证分类参数
        if category not in ['clothes', 'char']:
            category = 'clothes'
            print(f"无效分类，使用默认分类: {category}")
        
        # 构造页面信息
        page_info = {
            'url': 'clipboard',
            'title': f'剪切板图片 - {category}',
            'source': 'clipboard'
        }
        
        print(f"开始保存图片到分类: {category}")
        
        # 保存图片
        result = save_image_from_data(image_data, 'clipboard', page_info, user_id, category)
        
        if result:
            print(f"图片保存成功: {result['filename']}")
            
            # 创建任务
            task_id = str(uuid.uuid4())
            db.create_task(task_id, user_id, result['image_id'])
            print(f"任务创建成功: {task_id}")
            
            # 模拟异步处理
            def process_task():
                try:
                    time.sleep(1)  # 模拟处理时间
                    db.update_task_status(task_id, 'completed')
                    print(f"任务完成: {task_id}")
                except Exception as e:
                    print(f"任务处理失败: {e}")
            
            thread = threading.Thread(target=process_task)
            thread.start()
            
            response_data = {
                'success': True,
                'taskId': task_id,
                'imageId': result['image_id'],
                'filename': result['filename'],
                'fileSize': result['file_size'],
                'category': result['category'],
                'isLoggedIn': 'user_id' in session,
                'message': f'剪切板图片已保存到 {category} 文件夹'
            }
            
            print(f"返回成功响应: {response_data}")
            return jsonify(response_data)
        else:
            print("错误: 保存剪切板图片失败")
            return jsonify({'success': False, 'error': '保存剪切板图片失败'}), 500
            
    except Exception as e:
        print(f"处理剪切板图片失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'服务器错误: {str(e)}'}), 500

@app.route('/api/upload-file', methods=['POST'])
def upload_file():
    """文件上传接口"""
    try:
        print("收到文件上传请求")
        
        # 检查用户是否登录，如果没有登录则使用默认用户
        user_id = session.get('user_id')
        if not user_id:
            user_id = get_or_create_default_user()
            print(f"未登录用户，使用默认用户ID: {user_id}")
        else:
            print(f"登录用户ID: {user_id}")
        
        # 检查是否有文件上传
        if 'file' not in request.files:
            print("错误: 没有选择文件")
            return jsonify({'success': False, 'error': '没有选择文件'}), 400
        
        file = request.files['file']
        category = request.form.get('category', 'clothes')
        
        print(f"接收到文件: {file.filename}, 分类: {category}")
        
        if file.filename == '':
            print("错误: 文件名为空")
            return jsonify({'success': False, 'error': '没有选择文件'}), 400
        
        # 验证文件类型
        allowed_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
        if not file.filename.lower().endswith(allowed_extensions):
            print(f"错误: 不支持的文件格式: {file.filename}")
            return jsonify({'success': False, 'error': '不支持的文件格式，请上传 PNG、JPG、JPEG、GIF 或 WebP 格式的图片'}), 400
        
        # 验证分类参数
        if category not in ['clothes', 'char']:
            category = 'clothes'
            print(f"无效分类，使用默认分类: {category}")
        
        # 检查文件大小 (10MB限制)
        file.seek(0, 2)  # 移动到文件末尾
        file_size = file.tell()
        file.seek(0)  # 重置文件指针
        
        if file_size > 10 * 1024 * 1024:  # 10MB
            print(f"错误: 文件过大 ({file_size} bytes)")
            return jsonify({'success': False, 'error': '文件大小不能超过10MB'}), 400
        
        # 读取文件内容并转换为base64
        file_content = file.read()
        file_ext = file.filename.lower().split('.')[-1]
        
        # 确定MIME类型
        mime_types = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'gif': 'image/gif',
            'webp': 'image/webp'
        }
        mime_type = mime_types.get(file_ext, 'image/jpeg')
        
        # 转换为base64格式
        image_data = f"data:{mime_type};base64," + base64.b64encode(file_content).decode('utf-8')
        
        print(f"文件转换完成, MIME类型: {mime_type}, 数据长度: {len(image_data)}")
        
        # 构造页面信息
        page_info = {
            'url': 'file_upload',
            'title': f'上传文件 - {file.filename}',
            'source': 'file_upload',
            'original_filename': file.filename
        }
        
        print(f"开始保存文件到分类: {category}")
        
        # 保存图片
        result = save_image_from_data(image_data, f'file_upload:{file.filename}', page_info, user_id, category)
        
        if result:
            print(f"文件保存成功: {result['filename']}")
            
            # 创建任务
            task_id = str(uuid.uuid4())
            db.create_task(task_id, user_id, result['image_id'])
            print(f"任务创建成功: {task_id}")
            
            # 模拟异步处理
            def process_task():
                try:
                    time.sleep(1)  # 模拟处理时间
                    db.update_task_status(task_id, 'completed')
                    print(f"任务完成: {task_id}")
                except Exception as e:
                    print(f"任务处理失败: {e}")
            
            thread = threading.Thread(target=process_task)
            thread.start()
            
            response_data = {
                'success': True,
                'taskId': task_id,
                'imageId': result['image_id'],
                'filename': result['filename'],
                'fileSize': result['file_size'],
                'category': result['category'],
                'originalFilename': file.filename,
                'isLoggedIn': 'user_id' in session,
                'message': f'文件已上传到 {category} 文件夹'
            }
            
            print(f"返回成功响应: {response_data}")
            return jsonify(response_data)
        else:
            print("错误: 保存上传文件失败")
            return jsonify({'success': False, 'error': '保存上传文件失败'}), 500
            
    except Exception as e:
        print(f"处理文件上传失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'服务器错误: {str(e)}'}), 500

if __name__ == '__main__':
    print("启动图片处理服务器...")
    print(f"保存目录: {BASE_SAVE_DIR.absolute()}")
    print(f"数据库: {DB_PATH}")
    print(f"云端同步: {'启用' if ENABLE_CLOUD_SYNC else '禁用'}")
    print("WebUI地址: http://localhost:8080")
    app.run(host='localhost', port=8080, debug=True)
    print(f"云端同步: {'启用' if ENABLE_CLOUD_SYNC else '禁用'}")
    print("WebUI地址: http://localhost:8080")
    app.run(host='localhost', port=8080, debug=True)
def upload_file():
    """文件上传接口"""
    try:
        print("收到文件上传请求")
        
        # 检查用户是否登录，如果没有登录则使用默认用户
        user_id = session.get('user_id')
        if not user_id:
            user_id = get_or_create_default_user()
            print(f"未登录用户，使用默认用户ID: {user_id}")
        else:
            print(f"登录用户ID: {user_id}")
        
        # 检查是否有文件上传
        if 'file' not in request.files:
            print("错误: 没有选择文件")
            return jsonify({'success': False, 'error': '没有选择文件'}), 400
        
        file = request.files['file']
        category = request.form.get('category', 'clothes')
        
        print(f"接收到文件: {file.filename}, 分类: {category}")
        
        if file.filename == '':
            print("错误: 文件名为空")
            return jsonify({'success': False, 'error': '没有选择文件'}), 400
        
        # 验证文件类型
        allowed_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
        if not file.filename.lower().endswith(allowed_extensions):
            print(f"错误: 不支持的文件格式: {file.filename}")
            return jsonify({'success': False, 'error': '不支持的文件格式，请上传 PNG、JPG、JPEG、GIF 或 WebP 格式的图片'}), 400
        
        # 验证分类参数
        if category not in ['clothes', 'char']:
            category = 'clothes'
            print(f"无效分类，使用默认分类: {category}")
        
        # 检查文件大小 (10MB限制)
        file.seek(0, 2)  # 移动到文件末尾
        file_size = file.tell()
        file.seek(0)  # 重置文件指针
        
        if file_size > 10 * 1024 * 1024:  # 10MB
            print(f"错误: 文件过大 ({file_size} bytes)")
            return jsonify({'success': False, 'error': '文件大小不能超过10MB'}), 400
        
        # 读取文件内容并转换为base64
        file_content = file.read()
        file_ext = file.filename.lower().split('.')[-1]
        
        # 确定MIME类型
        mime_types = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'gif': 'image/gif',
            'webp': 'image/webp'
        }
        mime_type = mime_types.get(file_ext, 'image/jpeg')
        
        # 转换为base64格式
        image_data = f"data:{mime_type};base64," + base64.b64encode(file_content).decode('utf-8')
        
        print(f"文件转换完成, MIME类型: {mime_type}, 数据长度: {len(image_data)}")
        
        # 构造页面信息
        page_info = {
            'url': 'file_upload',
            'title': f'上传文件 - {file.filename}',
            'source': 'file_upload',
            'original_filename': file.filename
        }
        
        print(f"开始保存文件到分类: {category}")
        
        # 保存图片
        result = save_image_from_data(image_data, f'file_upload:{file.filename}', page_info, user_id, category)
        
        if result:
            print(f"文件保存成功: {result['filename']}")
            
            # 创建任务
            task_id = str(uuid.uuid4())
            db.create_task(task_id, user_id, result['image_id'])
            print(f"任务创建成功: {task_id}")
            
            # 模拟异步处理
            def process_task():
                try:
                    time.sleep(1)  # 模拟处理时间
                    db.update_task_status(task_id, 'completed')
                    print(f"任务完成: {task_id}")
                except Exception as e:
                    print(f"任务处理失败: {e}")
            
            thread = threading.Thread(target=process_task)
            thread.start()
            
            response_data = {
                'success': True,
                'taskId': task_id,
                'imageId': result['image_id'],
                'filename': result['filename'],
                'fileSize': result['file_size'],
                'category': result['category'],
                'originalFilename': file.filename,
                'isLoggedIn': 'user_id' in session,
                'message': f'文件已上传到 {category} 文件夹'
            }
            
            print(f"返回成功响应: {response_data}")
            return jsonify(response_data)
        else:
            print("错误: 保存上传文件失败")
            return jsonify({'success': False, 'error': '保存上传文件失败'}), 500
            
    except Exception as e:
        print(f"处理文件上传失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'服务器错误: {str(e)}'}), 500

if __name__ == '__main__':
    print("启动图片处理服务器...")
    print(f"保存目录: {BASE_SAVE_DIR.absolute()}")
    print(f"数据库: {DB_PATH}")
    print(f"云端同步: {'启用' if ENABLE_CLOUD_SYNC else '禁用'}")
    print("WebUI地址: http://localhost:8080")
    app.run(host='localhost', port=8080, debug=True)
