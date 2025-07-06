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
import traceback
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

# IDM-VTON API 配置
VTON_API_BASE_URL = "http://localhost:7860"  # Gradio服务地址

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
        
        # 更新图片表，添加category字段
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
                category TEXT DEFAULT 'clothes' CHECK (category IN ('clothes', 'char', 'vton_results', 'favorites')),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # 检查是否需要添加category列到现有的images表
        cursor.execute("PRAGMA table_info(images)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'category' not in columns:
            cursor.execute('ALTER TABLE images ADD COLUMN category TEXT DEFAULT "clothes"')
            print("已为images表添加category字段")
            # 根据filename更新现有记录的category
            cursor.execute('''
                UPDATE images SET category = 'char' 
                WHERE filename LIKE 'char_%'
            ''')
            cursor.execute('''
                UPDATE images SET category = 'vton_results' 
                WHERE filename LIKE 'vton_%'
            ''')
            print("已更新现有记录的category分类")
        
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
        
        # 创建收藏表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS favorites (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                image_id TEXT NOT NULL,
                favorite_type TEXT NOT NULL DEFAULT 'image',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (image_id) REFERENCES images (id),
                UNIQUE(user_id, image_id, favorite_type)
            )
        ''')
        
        # 创建VTON历史表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vton_history (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                human_image TEXT NOT NULL,
                garment_image TEXT NOT NULL,
                result_image TEXT NOT NULL,
                result_image_id TEXT,
                parameters TEXT,
                processing_time REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (result_image_id) REFERENCES images (id)
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
    
    def save_image_record(self, image_id, user_id, filename, original_url, page_info, file_size, width, height, context_info, category='clothes'):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO images (id, user_id, filename, original_url, page_url, page_title, file_size, image_width, image_height, context_info, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (image_id, user_id, filename, original_url, page_info.get('url'), page_info.get('title'), file_size, width, height, json.dumps(context_info), category))
        conn.commit()
        conn.close()
    
    def add_to_favorites(self, user_id, image_id, favorite_type='image'):
        """添加到收藏"""
        if not image_id:
            return False
            
        favorite_id = str(uuid.uuid4())
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO favorites (id, user_id, image_id, favorite_type)
                VALUES (?, ?, ?, ?)
            ''', (favorite_id, user_id, image_id, favorite_type))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            # 已经收藏过了
            return False
        finally:
            conn.close()
    
    def remove_from_favorites(self, user_id, image_id, favorite_type='image'):
        """从收藏中移除"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                DELETE FROM favorites 
                WHERE user_id = ? AND image_id = ? AND favorite_type = ?
            ''', (user_id, image_id, favorite_type))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def is_favorited(self, user_id, image_id, favorite_type='image'):
        """检查是否已收藏"""
        if not image_id:
            return False
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT COUNT(*) FROM favorites 
                WHERE user_id = ? AND image_id = ? AND favorite_type = ?
            ''', (user_id, image_id, favorite_type))
            return cursor.fetchone()[0] > 0
        finally:
            conn.close()
    
    def get_user_favorites(self, user_id, favorite_type='image', limit=50, offset=0):
        """获取用户收藏列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            # 收藏的都是image类型，通过category区分
            cursor.execute('''
                SELECT i.*, f.created_at as favorited_at
                FROM favorites f
                JOIN images i ON f.image_id = i.id
                WHERE f.user_id = ? AND f.favorite_type = ?
                ORDER BY f.created_at DESC
                LIMIT ? OFFSET ?
            ''', (user_id, favorite_type, limit, offset))
            
            results = cursor.fetchall()
            
            favorites = []
            for row in results:
                favorites.append({
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
                    'cloud_synced': bool(row[12]) if len(row) > 12 else False,
                    'category': row[13] if len(row) > 13 else 'clothes',
                    'favorited_at': row[-1],
                    'is_favorited': True  # 这些都是收藏的
                })
            return favorites
                
        finally:
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
    
    def get_user_images(self, user_id, category=None, limit=50, offset=0):
        """获取用户的图片列表，支持按分类过滤"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if category:
            cursor.execute('''
                SELECT * FROM images WHERE user_id = ? AND category = ? ORDER BY saved_at DESC LIMIT ? OFFSET ?
            ''', (user_id, category, limit, offset))
        else:
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
                'cloud_synced': bool(row[12]) if len(row) > 12 else False,
                'category': row[13] if len(row) > 13 else 'clothes',
                'is_favorited': self.is_favorited(user_id, row[0], favorite_type='image')
            })
        return images
    
    def get_image_count(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM images')
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    def get_user_image_count(self, user_id, category=None):
        """获取用户图片数量，支持按分类统计"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if category:
            cursor.execute('SELECT COUNT(*) FROM images WHERE user_id = ? AND category = ?', (user_id, category))
        else:
            cursor.execute('SELECT COUNT(*) FROM images WHERE user_id = ?', (user_id,))
            
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    def get_image_by_filename(self, user_id, filename):
        """根据用户ID和文件名获取图片信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT id, user_id, filename, original_url, page_url, page_title, 
                       saved_at, file_size, image_width, image_height, context_info, 
                       status, cloud_synced, category
                FROM images 
                WHERE user_id = ? AND filename = ?
                LIMIT 1
            ''', (user_id, filename))
            
            row = cursor.fetchone()
            if row:
                return {
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
                    'cloud_synced': bool(row[12]) if len(row) > 12 else False,
                    'category': row[13] if len(row) > 13 else 'clothes'
                }
            return None
        finally:
            conn.close()
    
    def get_image_by_id(self, image_id, user_id=None):
        """根据图片ID获取图片信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            if user_id:
                cursor.execute('SELECT * FROM images WHERE id = ? AND user_id = ?', (image_id, user_id))
            else:
                cursor.execute('SELECT * FROM images WHERE id = ?', (image_id,))
            
            result = cursor.fetchone()
            if result:
                return {
                    'id': result[0],
                    'user_id': result[1],
                    'filename': result[2],
                    'original_url': result[3],
                    'page_url': result[4],
                    'page_title': result[5],
                    'saved_at': result[6],
                    'file_size': result[7],
                    'image_width': result[8],
                    'image_height': result[9],
                    'context_info': json.loads(result[10]) if result[10] else {},
                    'status': result[11],
                    'cloud_synced': bool(result[12]) if len(result) > 12 else False,
                    'category': result[13] if len(result) > 13 else 'clothes'
                }
            return None
        finally:
            conn.close()
    
    def delete_image(self, image_id, user_id):
        """删除图片记录和文件"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            # 先获取图片信息
            image = self.get_image_by_id(image_id, user_id)
            if not image:
                return False, "图片不存在或无权限删除"
            
            # 删除文件
            try:
                category = image.get('category', 'clothes')
                user_save_dir = get_user_save_dir(user_id, category)
                filepath = user_save_dir / image['filename']
                if filepath.exists():
                    filepath.unlink()
                    print(f"已删除文件: {filepath}")
            except Exception as e:
                print(f"删除文件失败: {e}")
                # 即使文件删除失败，也继续删除数据库记录
            
            # 删除数据库记录
            cursor.execute('DELETE FROM images WHERE id = ? AND user_id = ?', (image_id, user_id))
            
            # 删除相关的收藏记录
            cursor.execute('DELETE FROM favorites WHERE image_id = ?', (image_id,))
            
            # 删除相关的VTON历史记录
            cursor.execute('DELETE FROM vton_history WHERE result_image_id = ?', (image_id,))
            
            conn.commit()
            return True, "删除成功"
            
        except Exception as e:
            conn.rollback()
            print(f"删除图片失败: {e}")
            return False, f"删除失败: {str(e)}"
        finally:
            conn.close()
    
    def delete_multiple_images(self, image_ids, user_id):
        """批量删除图片"""
        if not image_ids:
            return False, "未选择图片"
        
        success_count = 0
        failed_count = 0
        errors = []
        
        for image_id in image_ids:
            success, message = self.delete_image(image_id, user_id)
            if success:
                success_count += 1
            else:
                failed_count += 1
                errors.append(f"ID {image_id}: {message}")
        
        if failed_count == 0:
            return True, f"成功删除 {success_count} 张图片"
        elif success_count == 0:
            return False, f"删除失败: {'; '.join(errors)}"
        else:
            return True, f"成功删除 {success_count} 张图片，失败 {failed_count} 张"

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
        """同步用户数据到云端，包括所有图片文件、VTON历史和收藏数据"""
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
            
            # 获取VTON历史数据
            vton_history = user_data.get('vton_history', [])
            print(f"从数据库获取到 {len(vton_history)} 个VTON历史记录")
            
            # 获取收藏数据
            favorites_data = user_data.get('favorites', [])
            print(f"从数据库获取到 {len(favorites_data)} 个收藏记录")
            
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
                
                # 从数据库中获取分类信息，如果没有则从文件名推断
                category = image_meta.get('category', 'clothes')
                if not category or category == 'favorites':  # favorites不是文件夹分类
                    if filename.startswith('char_'):
                        category = 'char'
                    elif filename.startswith('clothes_'):
                        category = 'clothes'
                    elif filename.startswith('vton_result_'):
                        category = 'vton_results'
                    else:
                        category = 'clothes'  # 默认分类
                
                # 构造文件路径
                category_dir = user_dir / category
                filepath = category_dir / filename
                
                # 如果在推断的分类目录中找不到，尝试其他分类目录
                if not filepath.exists():
                    for other_category in ['char', 'clothes', 'vton_results']:
                        if other_category != category:
                            other_category_dir = user_dir / other_category
                            alt_filepath = other_category_dir / filename
                            if alt_filepath.exists():
                                filepath = alt_filepath
                                category = other_category
                                print(f"在 {other_category} 目录中找到文件: {filename}")
                                break
                
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
            
            # 收集分类统计信息
            categories_stats = {}
            for img in images_metadata:
                if img.get('filename'):
                    cat = img.get('category', 'clothes')
                    if cat == 'favorites':  # favorites不计入文件分类统计
                        continue
                    categories_stats[cat] = categories_stats.get(cat, 0) + 1
            
            # 构造完整的同步数据
            sync_payload = {
                'user_info': user_data.get('user_info', {}),
                'images_metadata': images_metadata,
                'image_files': image_files,
                'vton_history': vton_history,
                'favorites_data': favorites_data,
                'sync_timestamp': datetime.datetime.now().isoformat(),
                'sync_statistics': {
                    'total_metadata_records': len(images_metadata),
                    'total_files_found': processed_files,
                    'total_files_missing': failed_files,
                    'total_size': total_size,
                    'categories': list(categories_stats.keys()),
                    'categories_stats': categories_stats,
                    'vton_history_count': len(vton_history),
                    'favorites_count': len(favorites_data)
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

# 虚拟试穿相关函数
def image_to_base64(image_path):
    """将图片文件转换为base64字符串"""
    try:
        with open(image_path, 'rb') as img_file:
            img_data = img_file.read()
            img_base64 = base64.b64encode(img_data).decode('utf-8')
            # 获取文件扩展名判断图片格式
            ext = os.path.splitext(image_path)[1].lower()
            if ext in ['.jpg', '.jpeg']:
                mime_type = 'image/jpeg'
            elif ext == '.png':
                mime_type = 'image/png'
            else:
                mime_type = 'image/jpeg'  # 默认
            
            return f"data:{mime_type};base64,{img_base64}"
    except Exception as e:
        print(f"图片转base64失败 {image_path}: {e}")
        return None

def base64_to_image(base64_str, output_path):
    """将base64字符串保存为图片文件"""
    try:
        if base64_str.startswith('data:image'):
            base64_str = base64_str.split(',')[1]
        
        img_data = base64.b64decode(base64_str)
        with open(output_path, 'wb') as f:
            f.write(img_data)
        return True
    except Exception as e:
        print(f"base64转图片失败 {output_path}: {e}")
        return False

def call_vton_api(human_image_path, garment_image_path, garment_description="a shirt", 
                  auto_mask=True, auto_crop=False, denoise_steps=25, seed=42):
    """使用gradio_client调用IDM-VTON虚拟试穿API"""
    try:
        print(f"开始虚拟试穿: 人物={human_image_path}, 服装={garment_image_path}")
        
        # 检查文件是否存在
        if not os.path.exists(human_image_path):
            return {"success": False, "error": f"人物图片不存在: {human_image_path}"}
        
        if not os.path.exists(garment_image_path):
            return {"success": False, "error": f"服装图片不存在: {garment_image_path}"}
        
        # 转换图片为base64
        print("🔄 转换图片为base64格式...")
        human_base64 = image_to_base64(human_image_path)
        if not human_base64:
            return {"success": False, "error": "人物图片转换base64失败"}
        
        garment_base64 = image_to_base64(garment_image_path)
        if not garment_base64:
            return {"success": False, "error": "服装图片转换base64失败"}
        
        print(f"✅ 人物图片编码完成，长度: {len(human_base64)}")
        print(f"✅ 服装图片编码完成，长度: {len(garment_base64)}")
        
        # 使用gradio_client连接服务
        try:
            from gradio_client import Client
        except ImportError:
            return {"success": False, "error": "gradio_client未安装，请运行: pip install gradio_client"}
        
        print(f"🔗 连接到Gradio服务: {VTON_API_BASE_URL}")
        client = Client(VTON_API_BASE_URL)
        
        print("📤 发送虚拟试穿请求...")
        start_time = time.time()
        
        # 调用API - 使用gradio_client的predict方法
        result = client.predict(
            human_image_base64=human_base64,
            garment_image_base64=garment_base64,
            garment_description=garment_description,
            auto_mask=auto_mask,
            auto_crop=auto_crop,
            denoise_steps=denoise_steps,
            seed=seed,
            api_name="/tryon"
        )
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        print(f"✅ API调用成功，处理时间: {processing_time:.2f}秒")
        
        # 处理结果
        if result and len(result) >= 2:
            result_image_base64, mask_image_base64 = result
            
            return {
                "success": True,
                "result_image": result_image_base64,
                "mask_image": mask_image_base64,
                "processing_time": processing_time,
                "parameters": {
                    "garment_description": garment_description,
                    "auto_mask": auto_mask,
                    "auto_crop": auto_crop,
                    "denoise_steps": denoise_steps,
                    "seed": seed
                }
            }
        else:
            print("❌ API返回结果格式错误")
            return {"success": False, "error": "API返回结果格式错误"}
            
    except ImportError:
        return {"success": False, "error": "gradio_client未安装，请运行: pip install gradio_client"}
    except Exception as e:
        error_msg = str(e)
        print(f"❌ 虚拟试穿API调用失败: {error_msg}")
        
        # 提供更友好的错误信息
        if "Connection" in error_msg or "connection" in error_msg:
            return {"success": False, "error": "无法连接到虚拟试穿服务，请确保IDM-VTON Gradio服务正在运行"}
        elif "timeout" in error_msg.lower():
            return {"success": False, "error": "请求超时，请稍后重试"}
        elif "list index out of range" in error_msg:
            return {"success": False, "error": "姿态检测失败，请尝试设置 auto_mask=False 或使用更清晰的人物图片"}
        elif "CUDA" in error_msg:
            return {"success": False, "error": "GPU内存不足，请尝试降低 denoise_steps 或重启服务"}
        else:
            return {"success": False, "error": f"虚拟试穿失败: {error_msg}"}

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
            file_size, width, height, context_info, category
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
    category = request.args.get('category')  # 支持分类过滤
    offset = (page - 1) * per_page
    
    images = db.get_user_images(user_id, category, per_page, offset)
    total = db.get_user_image_count(user_id, category)
    
    # 为每个图片添加预览URL
    for image in images:
        image['preview_url'] = url_for('serve_user_image', user_id=user_id, filename=image['filename'])
        image['thumbnail_url'] = url_for('serve_user_thumbnail', user_id=user_id, filename=image['filename'])
    
    return jsonify({
        'images': images,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page,
        'category': category
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
    elif filename.startswith('vton_result_'):
        category = 'vton_results'
    
    user_save_dir = get_user_save_dir(user_id, category)
    filepath = user_save_dir / filename
    
    # 如果在默认分类中找不到，尝试在其他分类中查找
    if not filepath.exists():
        for other_category in ['char', 'clothes', 'vton_results']:
            if other_category != category:
                user_save_dir = get_user_save_dir(user_id, other_category)
                filepath = user_save_dir / filename
                if filepath.exists():
                    break
    
    if filepath.exists():
        return send_file(filepath)
    else:
        return "图片不存在", 404

@app.route('/api/images/<filename>')
def serve_image(filename):
    """提供全局图片文件（已弃用，保留兼容性）"""
    # 这个函数主要是为了兼容性，实际应该使用用户专属的图片服务
    # 尝试在默认用户目录中查找
    default_user_id = get_or_create_default_user()
    
    # 从文件名推断分类
    category = 'clothes' if filename.startswith('clothes_') else 'char' if filename.startswith('char_') else 'clothes'
    
    user_save_dir = get_user_save_dir(default_user_id, category)
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
    if category not in ['clothes', 'char', 'vton_results']:
        return jsonify({'error': '无效的分类'}), 400
    
    user_save_dir = get_user_save_dir(user_id, category)
    filepath = user_save_dir / filename
    if filepath.exists():
        return send_file(filepath)
    else:
        return "图片不存在", 404

@app.route('/api/user/file-paths', methods=['GET'])
@login_required
def get_user_file_paths():
    """获取用户图片文件路径信息"""
    user_id = session['user_id']
    category = request.args.get('category', 'all')  # 支持 'all', 'clothes', 'char'
    
    try:
        # 验证分类参数
        if category not in ['all', 'clothes', 'char']:
            return jsonify({'success': False, 'error': '无效的分类参数'}), 400
        
        result = {
            'success': True,
            'user_id': user_id,
            'base_path': str(BASE_SAVE_DIR.absolute()),
            'user_path': str((BASE_SAVE_DIR / user_id).absolute()),
            'paths': {}
        }
        
        # 根据分类返回路径信息
        if category == 'all' or category == 'clothes':
            clothes_dir = get_user_save_dir(user_id, 'clothes')
            result['paths']['clothes'] = {
                'directory': str(clothes_dir.absolute()),
                'exists': clothes_dir.exists(),
                'files': []
            }
            
            if clothes_dir.exists():
                # 获取clothes目录下的所有图片文件
                for file_path in clothes_dir.glob('clothes_*'):
                    if file_path.is_file() and file_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
                        result['paths']['clothes']['files'].append({
                            'filename': file_path.name,
                            'full_path': str(file_path.absolute()),
                            'relative_path': str(file_path.relative_to(BASE_SAVE_DIR)),
                            'size': file_path.stat().st_size,
                            'modified': datetime.datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                        })
        
        if category == 'all' or category == 'char':
            char_dir = get_user_save_dir(user_id, 'char')
            result['paths']['char'] = {
                'directory': str(char_dir.absolute()),
                'exists': char_dir.exists(),
                'files': []
            }
            
            if char_dir.exists():
                # 获取char目录下的所有图片文件
                for file_path in char_dir.glob('char_*'):
                    if file_path.is_file() and file_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
                        result['paths']['char']['files'].append({
                            'filename': file_path.name,
                            'full_path': str(file_path.absolute()),
                            'relative_path': str(file_path.relative_to(BASE_SAVE_DIR)),
                            'size': file_path.stat().st_size,
                            'modified': datetime.datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                        })
        
        # 添加统计信息
        total_files = sum(len(paths.get('files', [])) for paths in result['paths'].values())
        total_size = sum(
            sum(file_info['size'] for file_info in paths.get('files', []))
            for paths in result['paths'].values()
        )
        
        result['statistics'] = {
            'total_files': total_files,
            'total_size': total_size,
            'total_size_mb': round(total_size / 1024 / 1024, 2)
        }
        
        return jsonify(result)
        
    except Exception as e:
        print(f"获取文件路径失败: {e}")
        return jsonify({'success': False, 'error': f'获取文件路径失败: {str(e)}'}), 500

@app.route('/api/user/<user_id>/file-paths', methods=['GET'])
def get_user_file_paths_by_id(user_id):
    """根据用户ID获取图片文件路径信息（支持默认用户）"""
    # 如果是登录用户，验证权限
    if 'user_id' in session and session['user_id'] != user_id:
        return jsonify({'error': '权限不足'}), 403
    
    category = request.args.get('category', 'all')
    include_files = request.args.get('include_files', 'true').lower() == 'true'
    
    try:
        # 验证分类参数
        if category not in ['all', 'clothes', 'char']:
            return jsonify({'success': False, 'error': '无效的分类参数'}), 400
        
        # 检查用户目录是否存在
        user_dir = BASE_SAVE_DIR / user_id
        if not user_dir.exists():
            return jsonify({'success': False, 'error': '用户目录不存在'}), 404
        
        result = {
            'success': True,
            'user_id': user_id,
            'base_path': str(BASE_SAVE_DIR.absolute()),
            'user_path': str(user_dir.absolute()),
            'paths': {}
        }
        
        # 根据分类返回路径信息
        categories_to_check = []
        if category == 'all':
            categories_to_check = ['clothes', 'char']
        else:
            categories_to_check = [category]
        
        for cat in categories_to_check:
            cat_dir = get_user_save_dir(user_id, cat)
            result['paths'][cat] = {
                'directory': str(cat_dir.absolute()),
                'exists': cat_dir.exists(),
                'files': []
            }
            
            if include_files and cat_dir.exists():
                # 获取目录下的所有图片文件
                pattern = f'{cat}_*' if cat in ['clothes', 'char'] else '*'
                for file_path in cat_dir.glob(pattern):
                    if file_path.is_file() and file_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
                        result['paths'][cat]['files'].append({
                            'filename': file_path.name,
                            'full_path': str(file_path.absolute()),
                            'relative_path': str(file_path.relative_to(BASE_SAVE_DIR)),
                            'size': file_path.stat().st_size,
                            'modified': datetime.datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                        })
        
        # 添加统计信息
        if include_files:
            total_files = sum(len(paths.get('files', [])) for paths in result['paths'].values())
            total_size = sum(
                sum(file_info['size'] for file_info in paths.get('files', []))
                for paths in result['paths'].values()
            )
            
            result['statistics'] = {
                'total_files': total_files,
                'total_size': total_size,
                'total_size_mb': round(total_size / 1024 / 1024, 2)
            }
        
        return jsonify(result)
        
    except Exception as e:
        print(f"获取用户文件路径失败: {e}")
        return jsonify({'success': False, 'error': f'获取文件路径失败: {str(e)}'}), 500

# Web界面路由
@app.route('/')
def index():
    """主页面"""
    return render_template('index.html')

@app.route('/images')
def images_page():
    """图片展示页面"""
    return render_template('images.html')

@app.route('/tryon')
def tryon_page():
    """虚拟试穿页面"""
    return render_template('tryon.html')

@app.route('/tutorial')
def tutorial_page():
    """使用教程页面"""
    return render_template('tutorial.html')

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
                cloud_client.register_user(username, email, password, user_id)
            
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
        
        # 获取VTON历史数据
        vton_history = []
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='vton_history'
            ''')
            if cursor.fetchone():
                cursor.execute('''
                    SELECT id, user_id, human_image, garment_image, result_image, 
                           result_image_id, parameters, processing_time, created_at
                    FROM vton_history 
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                ''', (user_id,))
                
                for row in cursor.fetchall():
                    try:
                        parameters = json.loads(row[6]) if row[6] else {}
                    except:
                        parameters = {}
                    
                    vton_history.append({
                        'id': row[0],
                        'user_id': row[1],
                        'human_image': row[2],
                        'garment_image': row[3],
                        'result_image': row[4],
                        'result_image_id': row[5],
                        'parameters': parameters,
                        'processing_time': row[7],
                        'created_at': row[8]
                    })
            conn.close()
        except Exception as e:
            print(f"获取VTON历史失败: {e}")
        
        # 获取收藏数据
        favorites_data = []
        try:
            favorites_data = db.get_user_favorites(user_id, limit=10000)
        except Exception as e:
            print(f"获取收藏数据失败: {e}")
        
        sync_data = {
            'user_info': user_info,
            'images': user_images,
            'vton_history': vton_history,
            'favorites': favorites_data,
            'sync_timestamp': datetime.datetime.now().isoformat()
        }
        
        print(f"准备同步: 用户信息={bool(user_info)}, 图片数量={len(user_images)}, VTON历史={len(vton_history)}, 收藏数量={len(favorites_data)}")
        
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
                'vton_history_count': len(vton_history),
                'favorites_count': len(favorites_data),
                'estimated_time': f"{(len(user_images) + len(vton_history)) * 0.1:.1f}秒"  # 估算时间
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

@app.route('/api/user/current/images/<category>/<filename>')
def serve_current_user_image(category, filename):
    """为当前用户提供图片（适用于已登录和未登录用户）"""
    try:
        # 获取当前用户ID
        if 'user_id' in session:
            user_id = session['user_id']
        else:
            user_id = get_or_create_default_user()
        
        return serve_user_image_by_category(user_id, category, filename)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 虚拟试穿API
@app.route('/api/vton/check', methods=['GET'])
def check_vton_service():
    """使用gradio_client检查虚拟试穿服务状态"""
    try:
        # 尝试导入gradio_client
        try:
            from gradio_client import Client
        except ImportError:
            return jsonify({
                'success': False,
                'status': 'dependency_missing',
                'error': 'gradio_client未安装，请运行: pip install gradio_client'
            }), 503
        
        print(f"🔗 检查Gradio服务: {VTON_API_BASE_URL}")
        
        # 尝试连接到Gradio服务
        client = Client(VTON_API_BASE_URL)
        
        # 检查API是否可用 - 可以尝试获取API信息
        try:
            # 获取API信息来验证服务是否正常
            api_info = client.view_api()
            print(f"✅ Gradio服务连接成功")
            
            # 检查是否有/tryon端点
            has_tryon_api = any('/tryon' in str(endpoint) for endpoint in api_info.get('named_endpoints', {}))
            
            return jsonify({
                'success': True,
                'status': 'available',
                'service_url': VTON_API_BASE_URL,
                'message': '虚拟试穿服务可用',
                'has_tryon_api': has_tryon_api,
                'api_info': {
                    'endpoints': list(api_info.get('named_endpoints', {}).keys()) if api_info else []
                }
            })
            
        except Exception as api_error:
            print(f"⚠️ API检查失败: {api_error}")
            # 即使API检查失败，如果能连接到客户端，说明服务在运行
            return jsonify({
                'success': True,
                'status': 'available_limited',
                'service_url': VTON_API_BASE_URL,
                'message': '虚拟试穿服务运行中（API检查部分失败）',
                'warning': str(api_error)
            })
            
    except Exception as e:
        error_msg = str(e)
        print(f"❌ 服务检查失败: {error_msg}")
        
        # 提供更详细的错误信息
        if "Connection" in error_msg or "connection" in error_msg:
            return jsonify({
                'success': False,
                'status': 'unavailable',
                'error': f'无法连接到虚拟试穿服务 ({VTON_API_BASE_URL})，请确保IDM-VTON Gradio服务正在运行'
            }), 503
        else:
            return jsonify({
                'success': False,
                'status': 'error',
                'error': f'服务检查失败: {error_msg}'
            }), 500

@app.route('/api/vton/tryon', methods=['POST'])
def virtual_tryon():
    """虚拟试穿API"""
    try:
        print("收到虚拟试穿请求")
        
        # 获取当前用户ID
        if 'user_id' in session:
            user_id = session['user_id']
        else:
            user_id = get_or_create_default_user()
        
        print(f"用户ID: {user_id}")
        
        # 获取请求数据
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'}), 400
        
        # 验证必需参数
        human_filename = data.get('human_image')
        garment_filename = data.get('garment_image')
        
        if not human_filename or not garment_filename:
            return jsonify({'success': False, 'error': '人物图片和服装图片都是必需的'}), 400
        
        # 构建图片文件路径
        user_dir = BASE_SAVE_DIR / user_id
        
        # 查找人物图片（可能在char目录下）
        human_path = None
        for category in ['char', 'clothes']:
            potential_path = user_dir / category / human_filename
            if potential_path.exists():
                human_path = potential_path
                break
        
        if not human_path:
            return jsonify({'success': False, 'error': f'人物图片不存在: {human_filename}'}, 404)
        
        # 查找服装图片（通常在clothes目录下）
        garment_path = None
        for category in ['clothes', 'char']:
            potential_path = user_dir / category / garment_filename
            if potential_path.exists():
                garment_path = potential_path
                break
        
        if not garment_path:
            return jsonify({'success': False, 'error': f'服装图片不存在: {garment_filename}'}, 404)
        
        # 获取试穿参数
        garment_description = data.get('garment_description', 'a shirt')
        auto_mask = data.get('auto_mask', True)
        auto_crop = data.get('auto_crop', False)
        denoise_steps = data.get('denoise_steps', 25)
        seed = data.get('seed', int(time.time()) % 10000)  # 使用时间戳作为随机种子
        
        # 验证参数范围
        if not (1 <= denoise_steps <= 50):
            denoise_steps = 25
        
        print(f"试穿参数: 描述={garment_description}, 遮罩={auto_mask}, 裁剪={auto_crop}, 步骤={denoise_steps}, 种子={seed}")
        
        # 调用虚拟试穿API
        vton_result = call_vton_api(
            str(human_path), 
            str(garment_path),
            garment_description=garment_description,
            auto_mask=auto_mask,
            auto_crop=auto_crop,
            denoise_steps=denoise_steps,
            seed=seed
        )
        
        if not vton_result['success']:
            return jsonify({
                'success': False,
                'error': vton_result['error']
            }), 500
        
        # 保存试穿结果 - 只保存result图片
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        result_filename = f"vton_result_{timestamp}_{seed}.png"
        
        # 使用vton_results分类目录
        vton_results_dir = get_user_save_dir(user_id, 'vton_results')
        result_path = vton_results_dir / result_filename
        
        # 获取服装图片的原始页面信息（在保存前获取）
        garment_image_info = db.get_image_by_filename(user_id, garment_filename)
        
        result_image_id = None
        # 保存试穿结果图片
        if base64_to_image(vton_result['result_image'], result_path):
            print(f"试穿结果已保存: {result_path}")
            
            # 将试穿结果保存到images表中，分类为vton_results
            try:
                from PIL import Image
                with Image.open(result_path) as img:
                    width, height = img.size
                file_size = result_path.stat().st_size
                
                # 构造页面信息 - 使用服装图片的原页面信息
                if garment_image_info and garment_image_info.get('page_url') and garment_image_info['page_url'].strip() and garment_image_info.get('original_url') not in ['clipboard', 'vton_result', 'file_upload']:
                    # 如果服装图片有原始页面信息，使用它
                    page_info = {
                        'url': garment_image_info['page_url'],
                        'title': garment_image_info.get('page_title', f'虚拟试穿结果 - {garment_filename}'),
                        'source': 'vton_result_from_garment',
                        'original_garment_url': garment_image_info['original_url'],
                        'original_page_url': garment_image_info.get('page_url', ''),
                        'human_image': human_filename,
                        'garment_image': garment_filename
                    }
                else:
                    # 如果服装图片没有原始页面信息，使用默认信息
                    page_info = {
                        'url': 'vton_result',
                        'title': f'虚拟试穿结果 - {human_filename} + {garment_filename}',
                        'source': 'vton_api',
                        'human_image': human_filename,
                        'garment_image': garment_filename
                    }
                
                context_info = {
                    'vton_parameters': vton_result['parameters'],
                    'processing_time': vton_result['processing_time'],
                    'human_image': human_filename,
                    'garment_image': garment_filename,
                    'category': 'vton_results',
                    'garment_original_info': garment_image_info  # 保存服装图片的完整信息
                }
                
                # 保存到images表
                result_image_id = str(uuid.uuid4())
                db.save_image_record(
                    result_image_id, user_id, result_filename, 'vton_result', 
                    page_info, file_size, width, height, context_info, 'vton_results'
                )
                print(f"试穿结果已保存到图片库: {result_image_id}")
                
            except Exception as e:
                print(f"保存试穿结果到图片库失败: {e}")
        else:
            print(f"保存试穿结果失败: {result_path}")
            return jsonify({'success': False, 'error': '保存试穿结果失败'}), 500
        
        # 记录试穿历史到数据库
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # 创建试穿历史表（如果不存在）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS vton_history (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    human_image TEXT NOT NULL,
                    garment_image TEXT NOT NULL,
                    result_image TEXT NOT NULL,
                    result_image_id TEXT,
                    parameters TEXT,
                    processing_time REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id),
                    FOREIGN KEY (result_image_id) REFERENCES images (id)
                )
            ''')
            
            # 插入试穿记录
            vton_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT INTO vton_history 
                (id, user_id, human_image, garment_image, result_image, result_image_id, parameters, processing_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                vton_id, user_id, human_filename, garment_filename,
                result_filename, result_image_id,
                json.dumps(vton_result['parameters']),
                vton_result['processing_time']
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"保存试穿历史失败: {e}")
        
        # 返回成功结果
        return jsonify({
            'success': True,
            'message': '虚拟试穿完成',
            'result': {
                'vton_id': vton_id,
                'result_image': vton_result['result_image'],  # base64格式，前端可直接显示
                'result_filename': result_filename,
                'result_image_id': result_image_id,  # 添加图片ID用于收藏
                'result_url': url_for('serve_user_image_by_category', user_id=user_id, category='vton_results', filename=result_filename),
                'processing_time': vton_result['processing_time'],
                'parameters': vton_result['parameters'],
                'human_image': human_filename,
                'garment_image': garment_filename,
                'is_favorited': db.is_favorited(user_id, result_image_id, favorite_type='image') if result_image_id else False,
                'original_page_url': garment_image_info.get('page_url') if garment_image_info else None,
                'original_page_title': garment_image_info.get('page_title') if garment_image_info else None,
                'has_original_page': bool(garment_image_info and garment_image_info.get('page_url') and 
                                        garment_image_info.get('page_url').strip() and
                                        garment_image_info.get('original_url') not in ['clipboard', 'vton_result', 'file_upload'])
            }
        })
        
    except Exception as e:
        print(f"虚拟试穿失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'虚拟试穿失败: {str(e)}'
        }), 500

@app.route('/api/vton/history', methods=['GET'])
def get_vton_history():
    """获取虚拟试穿历史"""
    try:
        # 获取当前用户ID
        if 'user_id' in session:
            user_id = session['user_id']
        else:
            user_id = get_or_create_default_user()
        
        # 获取分页参数
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 10, type=int), 50)
        offset = (page - 1) * per_page
        
        # 查询试穿历史
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 检查表是否存在
        cursor.execute('''
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='vton_history'
        ''')
        if not cursor.fetchone():
            conn.close()
            return jsonify({
                'success': True,
                'history': [],
                'total': 0,
                'page': page,
                'per_page': per_page
            })
        
        # 获取总数
        cursor.execute('SELECT COUNT(*) FROM vton_history WHERE user_id = ?', (user_id,))
        total = cursor.fetchone()[0]
        
        # 获取历史记录
        cursor.execute('''
            SELECT id, human_image, garment_image, result_image, mask_image, 
                   parameters, processing_time, created_at
            FROM vton_history 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT ? OFFSET ?
        ''', (user_id, per_page, offset))
        
        records = cursor.fetchall()
        conn.close()
        
        history = []
        for record in records:
            try:
                parameters = json.loads(record[5]) if record[5] else {}
            except:
                parameters = {}
            
            vton_result_id = record[0]
            is_favorited = db.is_favorited(user_id, vton_result_id=vton_result_id, favorite_type='vton_result')
            
            history.append({
                'id': record[0],
                'human_image': record[1],
                'garment_image': record[2],
                'result_image': record[3],
                'mask_image': record[4],
                'result_url': url_for('serve_vton_result', user_id=user_id, filename=record[3]),
                'mask_url': url_for('serve_vton_result', user_id=user_id, filename=record[4]) if record[4] else None,
                'parameters': parameters,
                'processing_time': record[6],
                'created_at': record[7],
                'is_favorited': is_favorited
            })
        
        return jsonify({
            'success': True,
            'history': history,
            'total': total,
            'page': page,
            'per_page': per_page,
            'has_next': offset + per_page < total,
            'has_prev': page > 1
        })
        
    except Exception as e:
        print(f"获取试穿历史失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/user/<user_id>/vton_results/<filename>')
def serve_vton_result(user_id, filename):
    """提供虚拟试穿结果图片"""
    try:
        vton_results_dir = BASE_SAVE_DIR / user_id / "vton_results"
        file_path = vton_results_dir / filename
        
        if file_path.exists():
            return send_file(file_path)
        else:
            return jsonify({'error': '文件不存在'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 收藏功能API
@app.route('/api/favorites', methods=['POST'])
@login_required
def add_favorite():
    """添加收藏"""
    try:
        user_id = session['user_id']
        data = request.get_json()
        
        image_id = data.get('image_id')
        favorite_type = data.get('type', 'image')
        
        if not image_id:
            return jsonify({'success': False, 'error': '缺少image_id参数'}), 400
        
        if favorite_type not in ['image']:
            return jsonify({'success': False, 'error': '无效的收藏类型'}), 400
        
        success = db.add_to_favorites(user_id, image_id, favorite_type)
        
        if success:
            return jsonify({'success': True, 'message': '收藏成功'})
        else:
            return jsonify({'success': False, 'message': '已经收藏过了'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/favorites', methods=['DELETE'])
@login_required
def remove_favorite():
    """移除收藏"""
    try:
        user_id = session['user_id']
        data = request.get_json()
        
        image_id = data.get('image_id')
        favorite_type = data.get('type', 'image')
        
        if not image_id:
            return jsonify({'success': False, 'error': '缺少image_id参数'}), 400
        
        success = db.remove_from_favorites(user_id, image_id, favorite_type)
        
        if success:
            return jsonify({'success': True, 'message': '取消收藏成功'})
        else:
            return jsonify({'success': False, 'message': '收藏记录不存在'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/favorites', methods=['GET'])
@login_required
def get_favorites():
    """获取收藏列表"""
    try:
        user_id = session['user_id']
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        favorite_type = request.args.get('type', 'image')
        offset = (page - 1) * per_page
        
        favorites = db.get_user_favorites(user_id, favorite_type, per_page, offset)
        
        # 获取收藏总数
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) FROM favorites 
            WHERE user_id = ? AND favorite_type = ?
        ''', (user_id, favorite_type))
        total_count = cursor.fetchone()[0]
        conn.close()
        
        total_pages = (total_count + per_page - 1) // per_page  # 向上取整
        
        # 为收藏的图片添加预览URL
        for favorite in favorites:
            if favorite_type == 'image':
                category = favorite.get('category', 'clothes')
                if category in ['clothes', 'char', 'vton_results']:
                    favorite['preview_url'] = url_for('serve_user_image_by_category', 
                                                    user_id=user_id, 
                                                    category=category, 
                                                    filename=favorite['filename'])
                    favorite['thumbnail_url'] = url_for('serve_user_image_by_category', 
                                                      user_id=user_id, 
                                                      category=category, 
                                                      filename=favorite['filename'])
                else:
                    favorite['preview_url'] = url_for('serve_user_image', user_id=user_id, filename=favorite['filename'])
                    favorite['thumbnail_url'] = url_for('serve_user_thumbnail', user_id=user_id, filename=favorite['filename'])
        
        return jsonify({
            'favorites': favorites,
            'page': page,
            'per_page': per_page,
            'pages': total_pages,
            'total': total_count,
            'type': favorite_type
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/categories/stats', methods=['GET'])
@login_required
def get_category_stats():
    """获取分类统计信息"""
    try:
        user_id = session['user_id']
        
        categories = ['clothes', 'char', 'vton_results', 'favorites']
        stats = {}
        
        for category in categories:
            if category == 'favorites':
                # 收藏的统计
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM favorites WHERE user_id = ?', (user_id,))
                count = cursor.fetchone()[0]
                conn.close()
                stats[category] = count
            else:
                stats[category] = db.get_user_image_count(user_id, category)
        
        return jsonify({
            'success': True,
            'stats': stats,
            'total': sum(stats.values())
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# 图片删除功能API
@app.route('/api/images/<image_id>', methods=['DELETE'])
@login_required
def delete_image(image_id):
    """删除单张图片"""
    try:
        user_id = session['user_id']
        success, message = db.delete_image(image_id, user_id)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message}), 400
            
    except Exception as e:
        print(f"删除图片API失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/images/batch-delete', methods=['POST'])
@login_required
def batch_delete_images():
    """批量删除图片"""
    try:
        user_id = session['user_id']
        data = request.get_json()
        
        image_ids = data.get('image_ids', [])
        if not image_ids:
            return jsonify({'success': False, 'error': '未选择图片'}), 400
        
        success, message = db.delete_multiple_images(image_ids, user_id)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message}), 400
            
    except Exception as e:
        print(f"批量删除图片API失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/images/<image_id>', methods=['GET'])
@login_required
def get_image_details(image_id):
    """获取图片详细信息"""
    try:
        user_id = session['user_id']
        image = db.get_image_by_id(image_id, user_id)
        
        if image:
            # 添加预览URL
            category = image.get('category', 'clothes')
            image['preview_url'] = f"/api/user/{user_id}/images/{category}/{image['filename']}"
            image['thumbnail_url'] = f"/api/user/{user_id}/thumbnails/{image['filename']}"
            
            return jsonify({'success': True, 'image': image})
        else:
            return jsonify({'success': False, 'error': '图片不存在'}), 404
            
    except Exception as e:
        print(f"获取图片详情API失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
