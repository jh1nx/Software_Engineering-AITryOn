from flask import Flask, request, jsonify
import os
import json
import base64
import uuid
import datetime
from pathlib import Path
import sqlite3
import hashlib
import secrets
from functools import wraps
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)

# 云端服务器配置
CLOUD_DATA_DIR = Path("cloud_data")
CLOUD_DB_PATH = "cloud_database.db"
CLOUD_USERS_DIR = CLOUD_DATA_DIR / "users"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# 确保目录存在
CLOUD_DATA_DIR.mkdir(exist_ok=True)
CLOUD_USERS_DIR.mkdir(exist_ok=True)

class CloudDatabase:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建云端用户表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cloud_users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_sync TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                local_user_id TEXT,
                total_images INTEGER DEFAULT 0,
                total_storage_size INTEGER DEFAULT 0
            )
        ''')
        
        # 创建云端图片表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cloud_images (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                original_url TEXT,
                page_url TEXT,
                page_title TEXT,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                file_size INTEGER,
                image_width INTEGER,
                image_height INTEGER,
                context_info TEXT,
                category TEXT DEFAULT 'clothes',
                status TEXT DEFAULT 'synced',
                FOREIGN KEY (user_id) REFERENCES cloud_users (user_id)
            )
        ''')
        
        # 创建同步记录表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sync_records (
                sync_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                sync_type TEXT DEFAULT 'full',
                sync_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                images_count INTEGER DEFAULT 0,
                total_size INTEGER DEFAULT 0,
                status TEXT DEFAULT 'completed',
                error_message TEXT,
                FOREIGN KEY (user_id) REFERENCES cloud_users (user_id)
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("云端数据库初始化完成")
    
    def create_user(self, username, email, password, local_user_id=None):
        """创建云端用户"""
        # 如果提供了local_user_id，则直接使用它作为云端用户ID，否则生成新的UUID
        user_id = local_user_id if local_user_id else str(uuid.uuid4())
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO cloud_users (user_id, username, email, password_hash, local_user_id)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, username, email, password_hash, local_user_id))
            conn.commit()
            
            # 创建用户云端目录
            user_cloud_dir = CLOUD_USERS_DIR / user_id
            user_cloud_dir.mkdir(exist_ok=True)
            (user_cloud_dir / "clothes").mkdir(exist_ok=True)
            (user_cloud_dir / "char").mkdir(exist_ok=True)
            
            logger.info(f"云端用户创建成功: {username} ({user_id})")
            return user_id
        except sqlite3.IntegrityError as e:
            logger.error(f"创建用户失败: {e}")
            return None
        finally:
            conn.close()
    
    def verify_user(self, username, password):
        """验证云端用户"""
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_id, username, email, local_user_id FROM cloud_users 
            WHERE username = ? AND password_hash = ? AND is_active = 1
        ''', (username, password_hash))
        result = cursor.fetchone()
        conn.close()
        return result
    
    def get_user_by_local_id(self, local_user_id):
        """通过本地用户ID获取云端用户"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_id, username, email FROM cloud_users 
            WHERE local_user_id = ? AND is_active = 1
        ''', (local_user_id,))
        result = cursor.fetchone()
        conn.close()
        return result
    
    def save_sync_record(self, user_id, sync_type, images_count, total_size, status='completed', error_message=None):
        """保存同步记录"""
        sync_id = str(uuid.uuid4())
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO sync_records (sync_id, user_id, sync_type, images_count, total_size, status, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (sync_id, user_id, sync_type, images_count, total_size, status, error_message))
        conn.commit()
        conn.close()
        return sync_id
    
    def save_cloud_image(self, image_data, user_id):
        """保存云端图片记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO cloud_images 
            (id, user_id, filename, original_url, page_url, page_title, file_size, 
             image_width, image_height, context_info, category, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            image_data['id'], user_id, image_data['filename'], 
            image_data.get('original_url'), image_data.get('page_url'), 
            image_data.get('page_title'), image_data.get('file_size', 0),
            image_data.get('image_width', 0), image_data.get('image_height', 0),
            json.dumps(image_data.get('context_info', {})),
            image_data.get('context_info', {}).get('category', 'clothes'),
            'synced'
        ))
        conn.commit()
        conn.close()
    
    def update_user_stats(self, user_id, image_count, total_size):
        """更新用户统计信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE cloud_users 
            SET total_images = ?, total_storage_size = ?, last_sync = CURRENT_TIMESTAMP
            WHERE user_id = ?
        ''', (image_count, total_size, user_id))
        conn.commit()
        conn.close()

# 初始化云端数据库
cloud_db = CloudDatabase(CLOUD_DB_PATH)

def get_user_cloud_dir(user_id, category='clothes'):
    """获取用户云端存储目录"""
    user_dir = CLOUD_USERS_DIR / user_id
    user_dir.mkdir(exist_ok=True)
    
    category_dir = user_dir / category
    category_dir.mkdir(exist_ok=True)
    
    return category_dir

def save_cloud_image_file(image_filename, image_data_url, user_id, category='clothes'):
    """保存图片文件到云端存储"""
    try:
        # 解析base64数据
        if image_data_url.startswith('data:image'):
            header, data = image_data_url.split(',', 1)
            image_bytes = base64.b64decode(data)
        else:
            logger.error(f"无效的图片数据格式: {image_filename}")
            return False
        
        # 获取云端存储目录
        cloud_dir = get_user_cloud_dir(user_id, category)
        filepath = cloud_dir / image_filename
        
        # 保存文件
        with open(filepath, 'wb') as f:
            f.write(image_bytes)
        
        logger.info(f"云端图片保存成功: {filepath} ({len(image_bytes)} bytes)")
        return True
        
    except Exception as e:
        logger.error(f"保存云端图片文件失败 {image_filename}: {e}")
        return False

# API路由

@app.route('/api/status', methods=['GET'])
def cloud_status():
    """云端服务器状态"""
    return jsonify({
        'status': 'running',
        'service': 'cloud_sync_server',
        'timestamp': datetime.datetime.now().isoformat(),
        'version': '1.0.0'
    })

@app.route('/api/register', methods=['POST'])
def cloud_register():
    """云端用户注册"""
    try:
        data = request.get_json()
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        local_user_id = data.get('local_user_id')
        
        if not all([username, email, password]):
            return jsonify({'success': False, 'error': '用户名、邮箱和密码不能为空'}), 400
        
        user_id = cloud_db.create_user(username, email, password, local_user_id)
        if not user_id:
            return jsonify({'success': False, 'error': '用户名或邮箱已存在'}), 400
        
        logger.info(f"云端用户注册成功: {username}")
        return jsonify({
            'success': True,
            'cloud_user_id': user_id,
            'message': '云端注册成功'
        })
        
    except Exception as e:
        logger.error(f"云端注册失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/login', methods=['POST'])
def cloud_login():
    """云端用户登录"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not all([username, password]):
            return jsonify({'success': False, 'error': '用户名和密码不能为空'}), 400
        
        user_result = cloud_db.verify_user(username, password)
        if not user_result:
            return jsonify({'success': False, 'error': '用户名或密码错误'}), 401
        
        user_id, username, email, local_user_id = user_result
        
        logger.info(f"云端用户登录成功: {username}")
        return jsonify({
            'success': True,
            'cloud_user': {
                'user_id': user_id,
                'username': username,
                'email': email,
                'local_user_id': local_user_id
            },
            'message': '云端登录成功'
        })
        
    except Exception as e:
        logger.error(f"云端登录失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/sync/user/<user_id>', methods=['POST'])
def sync_user_data(user_id):
    """处理用户数据同步请求"""
    try:
        logger.info(f"收到用户 {user_id} 的同步请求")
        
        # 获取同步数据
        sync_data = request.get_json()
        if not sync_data:
            logger.error("同步请求中没有数据")
            return jsonify({'success': False, 'error': '没有接收到同步数据'}), 400
        
        # 解析同步数据
        user_info = sync_data.get('user_info', {})
        images_metadata = sync_data.get('images_metadata', [])
        image_files = sync_data.get('image_files', {})
        sync_timestamp = sync_data.get('sync_timestamp')
        sync_stats = sync_data.get('sync_statistics', {})
        
        logger.info(f"同步数据概览: 用户信息={bool(user_info)}, 图片元数据={len(images_metadata)}个, 图片文件={len(image_files)}个")
        logger.info(f"同步统计: {sync_stats}")
        
        # 检查或创建云端用户
        cloud_user = cloud_db.get_user_by_local_id(user_id)
        if not cloud_user:
            # 如果云端没有对应用户，可以选择自动创建或返回错误
            logger.warning(f"云端未找到对应本地用户 {user_id} 的记录")
            # 这里可以选择自动创建用户或要求先注册
            return jsonify({'success': False, 'error': '用户未在云端注册，请先注册'}), 404
        
        cloud_user_id = cloud_user[0]
        logger.info(f"找到对应云端用户: {cloud_user_id}")
        
        # 保存图片文件和元数据
        saved_files = 0
        failed_files = 0
        total_saved_size = 0
        
        for image_meta in images_metadata:
            try:
                filename = image_meta.get('filename')
                if not filename:
                    logger.warning(f"跳过无文件名的图片: {image_meta.get('id', 'unknown')}")
                    failed_files += 1
                    continue
                
                # 获取对应的图片文件数据
                image_file_data = image_files.get(filename)
                if not image_file_data:
                    logger.warning(f"图片文件数据缺失: {filename}")
                    failed_files += 1
                    continue
                
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
                    total_saved_size += image_meta.get('file_size', 0)
                    logger.debug(f"已保存: {filename} ({category})")
                else:
                    failed_files += 1
                    logger.error(f"保存失败: {filename}")
                
            except Exception as e:
                logger.error(f"处理图片失败 {filename}: {e}")
                failed_files += 1
                continue
        
        # 更新用户统计信息
        cloud_db.update_user_stats(cloud_user_id, saved_files, total_saved_size)
        
        # 记录同步结果
        sync_status = 'completed' if failed_files == 0 else 'partial'
        error_msg = f"{failed_files} 个文件同步失败" if failed_files > 0 else None
        
        sync_record_id = cloud_db.save_sync_record(
            cloud_user_id, 'full', saved_files, total_saved_size, sync_status, error_msg
        )
        
        result = {
            'success': True,
            'message': '数据同步完成',
            'sync_result': {
                'sync_id': sync_record_id,
                'cloud_user_id': cloud_user_id,
                'total_images': len(images_metadata),
                'saved_files': saved_files,
                'failed_files': failed_files,
                'total_size': total_saved_size,
                'sync_timestamp': sync_timestamp,
                'server_timestamp': datetime.datetime.now().isoformat(),
                'status': sync_status
            }
        }
        
        logger.info(f"用户 {user_id} 同步完成: 成功 {saved_files} 个，失败 {failed_files} 个")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"处理同步请求失败: {e}")
        import traceback
        traceback.print_exc()
        
        # 记录失败的同步
        try:
            if 'cloud_user_id' in locals():
                cloud_db.save_sync_record(
                    cloud_user_id, 'full', 0, 0, 'failed', str(e)
                )
        except:
            pass
        
        return jsonify({
            'success': False, 
            'error': f'同步处理失败: {str(e)}',
            'timestamp': datetime.datetime.now().isoformat()
        }), 500

@app.route('/api/user/<user_id>/sync/status', methods=['GET'])
def get_sync_status(user_id):
    """获取用户同步状态"""
    try:
        cloud_user = cloud_db.get_user_by_local_id(user_id)
        if not cloud_user:
            return jsonify({'success': False, 'error': '用户未找到'}), 404
        
        cloud_user_id = cloud_user[0]
        
        # 获取最近的同步记录
        conn = sqlite3.connect(CLOUD_DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT sync_id, sync_type, sync_timestamp, images_count, total_size, status, error_message
            FROM sync_records 
            WHERE user_id = ? 
            ORDER BY sync_timestamp DESC 
            LIMIT 5
        ''', (cloud_user_id,))
        records = cursor.fetchall()
        conn.close()
        
        sync_history = []
        for record in records:
            sync_history.append({
                'sync_id': record[0],
                'sync_type': record[1],
                'sync_timestamp': record[2],
                'images_count': record[3],
                'total_size': record[4],
                'status': record[5],
                'error_message': record[6]
            })
        
        return jsonify({
            'success': True,
            'cloud_user_id': cloud_user_id,
            'sync_history': sync_history
        })
        
    except Exception as e:
        logger.error(f"获取同步状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    logger.info("启动云端同步服务器...")
    logger.info(f"云端数据目录: {CLOUD_DATA_DIR.absolute()}")
    logger.info(f"云端数据库: {CLOUD_DB_PATH}")
    logger.info("云端服务器地址: http://localhost:8081")
    app.run(host='localhost', port=8081, debug=True)
