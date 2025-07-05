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
import requests
import time

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

# IDM-VTON API 配置
VTON_API_BASE_URL = "http://localhost:7860"  # Gradio服务地址
VTON_API_ENDPOINT = "/api/tryon"
VTON_API_TIMEOUT = 300  # 5分钟超时

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
        
        # 创建试穿历史表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vton_history (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                human_image TEXT NOT NULL,
                garment_image TEXT NOT NULL,
                result_image TEXT NOT NULL,
                result_image_id TEXT,
                mask_image TEXT,
                parameters TEXT,
                processing_time REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES cloud_users (user_id),
                FOREIGN KEY (result_image_id) REFERENCES cloud_images (id)
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
                FOREIGN KEY (user_id) REFERENCES cloud_users (user_id),
                FOREIGN KEY (image_id) REFERENCES cloud_images (id),
                UNIQUE(user_id, image_id, favorite_type)
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
            (user_cloud_dir / "vton_results").mkdir(exist_ok=True)  # 添加vton_results目录
            
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
            image_data.get('category', 'clothes'),  # 直接使用category字段
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
    
    def save_vton_history(self, vton_data, user_id):
        """保存VTON历史记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO vton_history 
            (id, user_id, human_image, garment_image, result_image, result_image_id,
             mask_image, parameters, processing_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            vton_data['id'], user_id, vton_data['human_image'], 
            vton_data['garment_image'], vton_data['result_image'],
            vton_data.get('result_image_id'), vton_data.get('mask_image'),
            json.dumps(vton_data.get('parameters', {})),
            vton_data.get('processing_time', 0.0),
            vton_data.get('created_at')
        ))
        conn.commit()
        conn.close()
    
    def save_favorite(self, favorite_data, user_id):
        """保存收藏记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO favorites 
            (id, user_id, image_id, favorite_type, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            favorite_data['id'], user_id, favorite_data['image_id'],
            favorite_data.get('favorite_type', 'image'),
            favorite_data.get('created_at')
        ))
        conn.commit()
        conn.close()
    
# 初始化云端数据库
cloud_db = CloudDatabase(CLOUD_DB_PATH)

def get_user_cloud_dir(user_id, category='clothes'):
    """获取用户云端存储目录"""
    user_dir = CLOUD_USERS_DIR / user_id
    user_dir.mkdir(exist_ok=True)
    
    # 支持所有分类
    if category not in ['clothes', 'char', 'vton_results']:
        category = 'clothes'  # 默认分类
    
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
        logger.error(f"图片转base64失败 {image_path}: {e}")
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
        logger.error(f"base64转图片失败 {output_path}: {e}")
        return False

def call_vton_api(human_image_path, garment_image_path, garment_description="a shirt", 
                  auto_mask=True, auto_crop=False, denoise_steps=25, seed=42):
    """使用gradio_client调用IDM-VTON虚拟试穿API"""
    try:
        logger.info(f"开始虚拟试穿: 人物={human_image_path}, 服装={garment_image_path}")
        
        # 检查文件是否存在
        if not os.path.exists(human_image_path):
            return {"success": False, "error": f"人物图片不存在: {human_image_path}"}
        
        if not os.path.exists(garment_image_path):
            return {"success": False, "error": f"服装图片不存在: {garment_image_path}"}
        
        # 转换图片为base64
        logger.info("🔄 转换图片为base64格式...")
        human_base64 = image_to_base64(human_image_path)
        if not human_base64:
            return {"success": False, "error": "人物图片转换base64失败"}
        
        garment_base64 = image_to_base64(garment_image_path)
        if not garment_base64:
            return {"success": False, "error": "服装图片转换base64失败"}
        
        logger.info(f"✅ 人物图片编码完成，长度: {len(human_base64)}")
        logger.info(f"✅ 服装图片编码完成，长度: {len(garment_base64)}")
        
        # 使用gradio_client连接服务
        try:
            from gradio_client import Client
        except ImportError:
            return {"success": False, "error": "gradio_client未安装，请运行: pip install gradio_client"}
        
        logger.info(f"🔗 连接到Gradio服务: {VTON_API_BASE_URL}")
        client = Client(VTON_API_BASE_URL)
        
        logger.info("📤 发送虚拟试穿请求...")
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
        
        logger.info(f"✅ API调用成功，处理时间: {processing_time:.2f}秒")
        
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
            logger.error("❌ API返回结果格式错误")
            return {"success": False, "error": "API返回结果格式错误"}
            
    except ImportError:
        return {"success": False, "error": "gradio_client未安装，请运行: pip install gradio_client"}
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ 虚拟试穿API调用失败: {error_msg}")
        
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
        vton_history = sync_data.get('vton_history', [])
        favorites_data = sync_data.get('favorites_data', [])
        sync_timestamp = sync_data.get('sync_timestamp')
        sync_stats = sync_data.get('sync_statistics', {})
        
        logger.info(f"同步数据概览: 用户信息={bool(user_info)}, 图片元数据={len(images_metadata)}个, 图片文件={len(image_files)}个")
        logger.info(f"VTON历史={len(vton_history)}个, 收藏数据={len(favorites_data)}个")
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
                
                # 确定分类 - 优先使用数据库中的分类信息
                category = image_meta.get('category', 'clothes')
                if category == 'favorites':  # favorites不是文件夹分类，需要重新判断
                    category = 'clothes'
                
                # 如果数据库中没有分类信息，则从文件名推断
                if not category or category not in ['clothes', 'char', 'vton_results']:
                    if filename.startswith('char_'):
                        category = 'char'
                    elif filename.startswith('clothes_'):
                        category = 'clothes'
                    elif filename.startswith('vton_result_'):
                        category = 'vton_results'
                    else:
                        category = 'clothes'  # 默认分类
                
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
        
        # 同步VTON历史数据
        vton_synced = 0
        vton_failed = 0
        
        for vton_record in vton_history:
            try:
                cloud_db.save_vton_history(vton_record, cloud_user_id)
                vton_synced += 1
                logger.debug(f"VTON历史同步成功: {vton_record.get('id')}")
            except Exception as e:
                logger.error(f"VTON历史同步失败 {vton_record.get('id')}: {e}")
                vton_failed += 1
                
        logger.info(f"VTON历史同步完成: 成功 {vton_synced} 个，失败 {vton_failed} 个")
        
        # 同步收藏数据
        favorites_synced = 0
        favorites_failed = 0
        
        for favorite_record in favorites_data:
            try:
                cloud_db.save_favorite(favorite_record, cloud_user_id)
                favorites_synced += 1
                logger.debug(f"收藏数据同步成功: {favorite_record.get('id')}")
            except Exception as e:
                logger.error(f"收藏数据同步失败 {favorite_record.get('id')}: {e}")
                favorites_failed += 1
                
        logger.info(f"收藏数据同步完成: 成功 {favorites_synced} 个，失败 {favorites_failed} 个")
        
        # 记录同步结果
        sync_status = 'completed' if (failed_files == 0 and vton_failed == 0 and favorites_failed == 0) else 'partial'
        error_details = []
        if failed_files > 0:
            error_details.append(f"{failed_files} 个文件同步失败")
        if vton_failed > 0:
            error_details.append(f"{vton_failed} 个VTON历史同步失败")
        if favorites_failed > 0:
            error_details.append(f"{favorites_failed} 个收藏记录同步失败")
        
        error_msg = "; ".join(error_details) if error_details else None
        
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
                'vton_synced': vton_synced,
                'vton_failed': vton_failed,
                'favorites_synced': favorites_synced,
                'favorites_failed': favorites_failed,
                'sync_timestamp': sync_timestamp,
                'server_timestamp': datetime.datetime.now().isoformat(),
                'status': sync_status
            }
        }
        
        logger.info(f"用户 {user_id} 同步完成: 图片成功 {saved_files} 个，失败 {failed_files} 个; VTON历史成功 {vton_synced} 个，失败 {vton_failed} 个; 收藏成功 {favorites_synced} 个，失败 {favorites_failed} 个")
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
        # 检查云端用户
        cloud_user = cloud_db.get_user_by_local_id(user_id)
        if not cloud_user:
            return jsonify({'success': False, 'error': '用户未找到'}), 404
        
        cloud_user_id = cloud_user[0]
        
        conn = sqlite3.connect(CLOUD_DB_PATH)
        cursor = conn.cursor()
        
        # 获取最近的同步记录
        cursor.execute('''
            SELECT sync_id, sync_type, sync_timestamp, images_count, 
                   total_size, status, error_message
            FROM sync_records 
            WHERE user_id = ?
            ORDER BY sync_timestamp DESC
            LIMIT 1
        ''', (cloud_user_id,))
        
        last_sync = cursor.fetchone()
        
        # 获取统计信息
        cursor.execute('SELECT COUNT(*) FROM cloud_images WHERE user_id = ?', (cloud_user_id,))
        total_images = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM vton_history WHERE user_id = ?', (cloud_user_id,))
        total_vton_history = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM favorites WHERE user_id = ?', (cloud_user_id,))
        total_favorites = cursor.fetchone()[0]
        
        conn.close()
        
        result = {
            'success': True,
            'user_id': user_id,
            'cloud_user_id': cloud_user_id,
            'sync_statistics': {
                'total_images': total_images,
                'total_vton_history': total_vton_history,
                'total_favorites': total_favorites
            }
        }
        
        if last_sync:
            result['last_sync'] = {
                'sync_id': last_sync[0],
                'sync_type': last_sync[1],
                'sync_timestamp': last_sync[2],
                'images_count': last_sync[3],
                'total_size': last_sync[4],
                'status': last_sync[5],
                'error_message': last_sync[6]
            }
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"获取同步状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# 云端收藏API
@app.route('/api/user/<user_id>/favorites', methods=['GET'])
def get_user_favorites(user_id):
    """获取用户收藏列表"""
    try:
        # 检查云端用户
        cloud_user = cloud_db.get_user_by_local_id(user_id)
        if not cloud_user:
            return jsonify({'success': False, 'error': '用户未找到'}), 404
        
        cloud_user_id = cloud_user[0]
        
        # 获取分页参数
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 20, type=int), 100)
        favorite_type = request.args.get('favorite_type', 'image')
        offset = (page - 1) * per_page
        
        conn = sqlite3.connect(CLOUD_DB_PATH)
        cursor = conn.cursor()
        
        # 获取总数
        cursor.execute('''
            SELECT COUNT(*) FROM favorites 
            WHERE user_id = ? AND favorite_type = ?
        ''', (cloud_user_id, favorite_type))
        total = cursor.fetchone()[0]
        
        # 获取收藏记录，关联图片信息
        cursor.execute('''
            SELECT f.id, f.image_id, f.favorite_type, f.created_at,
                   i.filename, i.original_url, i.page_url, i.page_title,
                   i.category, i.file_size, i.image_width, i.image_height
            FROM favorites f
            LEFT JOIN cloud_images i ON f.image_id = i.id
            WHERE f.user_id = ? AND f.favorite_type = ?
            ORDER BY f.created_at DESC
            LIMIT ? OFFSET ?
        ''', (cloud_user_id, favorite_type, per_page, offset))
        
        favorites = []
        for row in cursor.fetchall():
            favorites.append({
                'id': row[0],
                'image_id': row[1],
                'favorite_type': row[2],
                'favorited_at': row[3],
                'image_info': {
                    'filename': row[4],
                    'original_url': row[5],
                    'page_url': row[6],
                    'page_title': row[7],
                    'category': row[8],
                    'file_size': row[9],
                    'image_width': row[10],
                    'image_height': row[11]
                } if row[4] else None
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'favorites': favorites,
            'total': total,
            'page': page,
            'per_page': per_page,
            'has_next': offset + per_page < total,
            'has_prev': page > 1
        })
        
    except Exception as e:
        logger.error(f"获取收藏列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/user/<user_id>/cloud/file-paths', methods=['GET'])
def get_cloud_user_file_paths(user_id):
    """获取云端用户图片文件路径信息"""
    try:
        # 通过本地用户ID查找云端用户
        cloud_user = cloud_db.get_user_by_local_id(user_id)
        if not cloud_user:
            return jsonify({'success': False, 'error': '用户未在云端注册'}), 404
        
        cloud_user_id = cloud_user[0]
        category = request.args.get('category', 'all')
        include_files = request.args.get('include_files', 'true').lower() == 'true'
        
        # 验证分类参数
        if category not in ['all', 'clothes', 'char']:
            return jsonify({'success': False, 'error': '无效的分类参数'}), 400
        
        # 检查云端用户目录是否存在
        cloud_user_dir = CLOUD_USERS_DIR / cloud_user_id
        if not cloud_user_dir.exists():
            return jsonify({'success': False, 'error': '云端用户目录不存在'}), 404
        
        result = {
            'success': True,
            'local_user_id': user_id,
            'cloud_user_id': cloud_user_id,
            'cloud_base_path': str(CLOUD_DATA_DIR.absolute()),
            'cloud_user_path': str(cloud_user_dir.absolute()),
            'paths': {}
        }
        
        # 根据分类返回路径信息
        categories_to_check = []
        if category == 'all':
            categories_to_check = ['clothes', 'char']
        else:
            categories_to_check = [category]
        
        for cat in categories_to_check:
            cat_dir = get_user_cloud_dir(cloud_user_id, cat)
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
                            'relative_path': str(file_path.relative_to(CLOUD_DATA_DIR)),
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
        
        # 从数据库获取用户统计信息进行对比
        conn = sqlite3.connect(CLOUD_DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT total_images, total_storage_size, last_sync
            FROM cloud_users WHERE user_id = ?
        ''', (cloud_user_id,))
        db_stats = cursor.fetchone()
        conn.close()
        
        if db_stats:
            result['database_statistics'] = {
                'total_images': db_stats[0],
                'total_storage_size': db_stats[1],
                'total_storage_size_mb': round(db_stats[1] / 1024 / 1024, 2) if db_stats[1] else 0,
                'last_sync': db_stats[2]
            }
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"获取云端文件路径失败: {e}")
        return jsonify({'success': False, 'error': f'获取文件路径失败: {str(e)}'}), 500

@app.route('/api/vton/check', methods=['GET'])
def check_vton_service():
    """检查虚拟试穿服务状态"""
    try:
        # 检查VTON服务是否可用
        check_url = f"{VTON_API_BASE_URL}/api/predict"
        response = requests.get(check_url, timeout=5)
        
        if response.status_code == 200:
            return jsonify({
                'success': True,
                'status': 'available',
                'service_url': VTON_API_BASE_URL,
                'message': '虚拟试穿服务可用'
            })
        else:
            return jsonify({
                'success': False,
                'status': 'unavailable',
                'error': f'服务响应异常: {response.status_code}'
            }), 503
            
    except requests.exceptions.ConnectionError:
        return jsonify({
            'success': False,
            'status': 'unavailable',
            'error': '无法连接到虚拟试穿服务'
        }), 503
    except Exception as e:
        return jsonify({
            'success': False,
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/api/user/<user_id>/vton', methods=['POST'])
def virtual_tryon(user_id):
    """虚拟试穿API"""
    try:
        logger.info(f"用户 {user_id} 请求虚拟试穿")
        
        # 检查云端用户
        cloud_user = cloud_db.get_user_by_local_id(user_id)
        if not cloud_user:
            return jsonify({'success': False, 'error': '用户未在云端注册'}), 404
        
        cloud_user_id = cloud_user[0]
        
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
        cloud_user_dir = CLOUD_USERS_DIR / cloud_user_id
        
        # 查找人物图片（可能在char目录下）
        human_path = None
        for category in ['char', 'clothes']:
            potential_path = cloud_user_dir / category / human_filename
            if potential_path.exists():
                human_path = potential_path
                break
        
        if not human_path:
            return jsonify({'success': False, 'error': f'人物图片不存在: {human_filename}'}), 404
        
        # 查找服装图片（通常在clothes目录下）
        garment_path = None
        for category in ['clothes', 'char']:
            potential_path = cloud_user_dir / category / garment_filename
            if potential_path.exists():
                garment_path = potential_path
                break
        
        if not garment_path:
            return jsonify({'success': False, 'error': f'服装图片不存在: {garment_filename}'}), 404
        
        # 获取试穿参数
        garment_description = data.get('garment_description', 'a shirt')
        auto_mask = data.get('auto_mask', True)
        auto_crop = data.get('auto_crop', False)
        denoise_steps = data.get('denoise_steps', 25)
        seed = data.get('seed', int(time.time()) % 10000)  # 使用时间戳作为随机种子
        
        # 验证参数范围
        if not (1 <= denoise_steps <= 50):
            denoise_steps = 25
        
        logger.info(f"试穿参数: 描述={garment_description}, 遮罩={auto_mask}, 裁剪={auto_crop}, 步骤={denoise_steps}, 种子={seed}")
        
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
        
        # 保存试穿结果
        result_filename = f"vton_result_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{seed}.png"
        mask_filename = f"vton_mask_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{seed}.png"
        
        # 创建试穿结果目录
        vton_results_dir = cloud_user_dir / "vton_results"
        vton_results_dir.mkdir(exist_ok=True)
        
        result_path = vton_results_dir / result_filename
        mask_path = vton_results_dir / mask_filename
        
        # 保存试穿结果图片
        if base64_to_image(vton_result['result_image'], result_path):
            logger.info(f"试穿结果已保存: {result_path}")
        else:
            logger.error(f"保存试穿结果失败: {result_path}")
        
        # 保存遮罩图片
        if base64_to_image(vton_result['mask_image'], mask_path):
            logger.info(f"遮罩图片已保存: {mask_path}")
        else:
            logger.error(f"保存遮罩图片失败: {mask_path}")
        
        # 记录试穿历史到数据库（可选）
        try:
            conn = sqlite3.connect(CLOUD_DB_PATH)
            cursor = conn.cursor()
            
            # 插入试穿记录
            vton_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT INTO vton_history 
                (id, user_id, human_image, garment_image, result_image, mask_image, parameters, processing_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                vton_id, cloud_user_id, human_filename, garment_filename,
                result_filename, mask_filename,
                json.dumps(vton_result['parameters']),
                vton_result['processing_time']
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"保存试穿历史失败: {e}")
        
        # 返回成功结果
        return jsonify({
            'success': True,
            'message': '虚拟试穿完成',
            'result': {
                'vton_id': vton_id,
                'result_image': vton_result['result_image'],  # base64格式，前端可直接显示
                'mask_image': vton_result['mask_image'],
                'result_filename': result_filename,
                'mask_filename': mask_filename,
                'processing_time': vton_result['processing_time'],
                'parameters': vton_result['parameters'],
                'human_image': human_filename,
                'garment_image': garment_filename
            }
        })
        
    except Exception as e:
        logger.error(f"虚拟试穿失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'虚拟试穿失败: {str(e)}'
        }), 500

@app.route('/api/user/<user_id>/vton/history', methods=['GET'])
def get_vton_history(user_id):
    """获取用户虚拟试穿历史"""
    try:
        # 检查云端用户
        cloud_user = cloud_db.get_user_by_local_id(user_id)
        if not cloud_user:
            return jsonify({'success': False, 'error': '用户未找到'}), 404
        
        cloud_user_id = cloud_user[0]
        
        # 获取分页参数
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 10, type=int), 50)
        offset = (page - 1) * per_page
        
        # 查询试穿历史
        conn = sqlite3.connect(CLOUD_DB_PATH)
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
        cursor.execute('SELECT COUNT(*) FROM vton_history WHERE user_id = ?', (cloud_user_id,))
        total = cursor.fetchone()[0]
        
        # 获取历史记录
        cursor.execute('''
            SELECT id, human_image, garment_image, result_image, mask_image, 
                   parameters, processing_time, created_at
            FROM vton_history 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT ? OFFSET ?
        ''', (cloud_user_id, per_page, offset))
        
        records = cursor.fetchall()
        conn.close()
        
        history = []
        for record in records:
            try:
                parameters = json.loads(record[5]) if record[5] else {}
            except:
                parameters = {}
            
            history.append({
                'id': record[0],
                'human_image': record[1],
                'garment_image': record[2],
                'result_image': record[3],
                'mask_image': record[4],
                'parameters': parameters,
                'processing_time': record[6],
                'created_at': record[7]
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
        logger.error(f"获取试穿历史失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    logger.info("启动云端同步服务器...")
    logger.info(f"云端数据目录: {CLOUD_DATA_DIR.absolute()}")
    logger.info(f"云端数据库: {CLOUD_DB_PATH}")
    logger.info("云端服务器地址: http://localhost:8081")
    app.run(host='localhost', port=8081, debug=True)
