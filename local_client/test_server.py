import requests
import json
import base64
import uuid
import datetime
import time
import random
import os
from pathlib import Path
import sqlite3
import hashlib
import threading
from PIL import Image
import io

# 测试配置
LOCAL_CLIENT_URL = "http://localhost:8080"
CLOUD_SERVER_URL = "http://localhost:6006"
TEST_DATA_DIR = Path("test_data")
TEST_IMAGES_DIR = TEST_DATA_DIR / "test_images"

# 确保测试目录存在
TEST_DATA_DIR.mkdir(exist_ok=True)
TEST_IMAGES_DIR.mkdir(exist_ok=True)

class ServerTester:
    def __init__(self):
        self.local_session = requests.Session()
        self.cloud_session = requests.Session()
        self.test_results = []
        self.test_user_data = {'token': None, 'cloud_user_id': None}
        
    def log_test(self, test_name, success, message, details=None):
        """记录测试结果"""
        result = {
            'test_name': test_name,
            'success': success,
            'message': message,
            'timestamp': datetime.datetime.now().isoformat(),
            'details': details or {}
        }
        self.test_results.append(result)
        
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}: {message}")
        
        if details:
            print(f"   详情: {details}")
    
    def generate_test_image(self, filename, width=400, height=300, color="RGB"):
        """生成测试图片"""
        try:
            # 创建测试图片
            image = Image.new(color, (width, height), (255, 0, 0))  # 红色背景
            
            # 保存到测试目录
            filepath = TEST_IMAGES_DIR / filename
            image.save(filepath, "PNG")
            
            # 转换为base64
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            image_bytes = buffer.getvalue()
            image_base64 = base64.b64encode(image_bytes).decode('utf-8')
            image_data_url = f"data:image/png;base64,{image_base64}"
            
            return {
                'filepath': str(filepath),
                'size': len(image_bytes),
                'data_url': image_data_url,
                'dimensions': (width, height)
            }
        except Exception as e:
            print(f"生成测试图片失败: {e}")
            return None
    
    def test_cloud_server_status(self):
        """测试云端服务器状态"""
        try:
            response = self.cloud_session.get(f"{CLOUD_SERVER_URL}/api/status", timeout=10)
            if response.status_code == 200:
                data = response.json()
                self.log_test(
                    "云端服务器状态检查", 
                    True, 
                    "云端服务器运行正常",
                    data
                )
                return True
            else:
                self.log_test(
                    "云端服务器状态检查", 
                    False, 
                    f"状态码: {response.status_code}"
                )
                return False
        except Exception as e:
            self.log_test(
                "云端服务器状态检查", 
                False, 
                f"连接失败: {str(e)}"
            )
            return False
    
    def test_local_client_status(self):
        """测试本地客户端状态"""
        try:
            response = self.local_session.get(f"{LOCAL_CLIENT_URL}/api/status", timeout=10)
            if response.status_code == 200:
                data = response.json()
                self.log_test(
                    "本地客户端状态检查", 
                    True, 
                    "本地客户端运行正常",
                    data
                )
                return True
            else:
                self.log_test(
                    "本地客户端状态检查", 
                    False, 
                    f"状态码: {response.status_code}"
                )
                return False
        except Exception as e:
            self.log_test(
                "本地客户端状态检查", 
                False, 
                f"连接失败: {str(e)}"
            )
            return False
    
    def test_user_registration(self):
        """测试用户注册"""
        try:
            # 生成测试用户数据
            timestamp = int(time.time())* random.randint(10, 50000)
            test_user = {
                'username': f'testuser_{timestamp}',
                'email': f'test_{timestamp}@example.com',
                'password': 'test123456'
            }
            self.test_user_data = test_user
            print("生成的测试用户数据:", test_user)
            
            # 测试本地注册
            response = self.local_session.post(
                f"{LOCAL_CLIENT_URL}/api/register",
                json=test_user,
                timeout=10
            )
            
            if response.status_code == 200:
                local_result = response.json()
                if local_result.get('success'):
                    self.test_user_data['local_user_id'] = local_result['user_id']
                    self.log_test(
                        "本地用户注册", 
                        True, 
                        f"注册成功，用户ID: {local_result['user_id']}",
                        local_result
                    )
                    
                    # 测试云端注册
                    cloud_response = self.cloud_session.post(
                        f"{CLOUD_SERVER_URL}/api/register",
                        json={**test_user, 'local_user_id': local_result['user_id']},
                        timeout=20
                    )
                    
                    if cloud_response.status_code == 200:
                        cloud_result = cloud_response.json()
            
                        if cloud_result.get('success'):
                            self.test_user_data['cloud_user_id'] = cloud_result['cloud_user_id']
                            self.log_test(
                                "云端用户注册", 
                                True, 
                                f"云端注册成功，用户ID: {cloud_result['cloud_user_id']}",
                                cloud_result
                            )
                            return True
                    
                    self.log_test(
                        "云端用户注册", 
                        False, 
                        f"云端注册失败: {cloud_response.text}"
                    )
                    return False
                    
            self.log_test(
                "本地用户注册", 
                False, 
                f"注册失败: {response.text}"
            )
            return False
            
        except Exception as e:
            self.log_test(
                "用户注册测试", 
                False, 
                f"异常: {str(e)}"
            )
            return False
    
    def test_user_login(self):
        """测试用户登录"""
        try:
            login_data = {
                'username': self.test_user_data['username'],
                'password': self.test_user_data['password']
            }
            
            # 测试本地登录
            response = self.local_session.post(
                f"{LOCAL_CLIENT_URL}/api/login",
                json=login_data,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                self.log_test(
                    "本地用户登录", 
                    True, 
                    "登录成功",
                    result
                )
                return True
            
            self.log_test(
                "本地用户登录", 
                False, 
                f"登录失败: {response.text}"
            )
            return False
            
        except Exception as e:
            self.log_test(
                "用户登录测试", 
                False, 
                f"异常: {str(e)}"
            )
            return False
    
    def my_login(self):
        """云端用户登录"""
        try:
            login_data = {
                'username': self.test_user_data['username'],
                'password': self.test_user_data['password']
            }
            
            # 测试云端登录
            response = self.local_session.post(
                f"{CLOUD_SERVER_URL}/api/login",
                json=login_data,
                timeout=20
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"响应中包含的键: {list(result.keys())}")
                token_key = 'token'  # 尝试小写
                if token_key in result:
                    self.test_user_data['token'] = result[token_key]
                    self.log_test(
                        "云端用户登录", 
                        True, 
                        "登录成功",
                        result
                    )
                else:
                    # 尝试大写
                    token_key = 'Token'
                    if token_key in result:
                        self.test_user_data['token'] = result[token_key]
                        self.log_test(
                            "云端用户登录", 
                            True, 
                            "登录成功（使用大写Token）",
                            result
                        )
                        return True
                    else:
                        self.log_test(
                            "本地用户登录", 
                            False, 
                            "响应中没有token或Token字段"
                        )
                        return False    
                return True 
            
            self.log_test(
                "云端用户登录", 
                False, 
                f"登录失败: {response.text}"
            )
            return False
            
        except Exception as e:
            self.log_test(
                "云端登录测试", 
                False, 
                f"异常: {str(e)}"
            )
            return False
    
    
    
    def test_image_upload(self):
        """测试图片上传功能"""
        try:
            uploaded_images = []
            
            # 测试不同分类的图片上传
            test_images = [
                {'category': 'clothes', 'filename': 'test_clothes.png'},
                {'category': 'char', 'filename': 'test_char.png'},
                {'category': 'clothes', 'filename': 'test_clothes2.png'}
            ]
            
            for img_info in test_images:
                # 生成测试图片
                test_image = self.generate_test_image(img_info['filename'])
                if not test_image:
                    continue
                
                # 上传图片
                upload_data = {
                    'imageData': test_image['data_url'],
                    'originalUrl': f"test://{img_info['filename']}",
                    'category': img_info['category'],
                    'pageInfo': {
                        'url': 'test://page',
                        'title': f"测试页面 - {img_info['category']}"
                    }
                }
                
                response = self.local_session.post(
                    f"{LOCAL_CLIENT_URL}/api/receive-image",
                    json=upload_data,
                    timeout=30
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get('success'):
                        uploaded_images.append({
                            'image_id': result['imageId'],
                            'filename': result['filename'],
                            'category': result['category'],
                            'task_id': result['taskId']
                        })
                        self.log_test(
                            f"图片上传 ({img_info['category']})", 
                            True, 
                            f"上传成功: {result['filename']}",
                            result
                        )
                    else:
                        self.log_test(
                            f"图片上传 ({img_info['category']})", 
                            False, 
                            f"上传失败: {result.get('error', 'Unknown error')}"
                        )
                else:
                    self.log_test(
                        f"图片上传 ({img_info['category']})", 
                        False, 
                        f"HTTP错误: {response.status_code}"
                    )
            
            self.test_user_data['uploaded_images'] = uploaded_images
            return len(uploaded_images) > 0
            
        except Exception as e:
            self.log_test(
                "图片上传测试", 
                False, 
                f"异常: {str(e)}"
            )
            return False
    
    def test_get_user_images(self):
        """测试获取用户图片列表"""
        try:
            response = self.local_session.get(
                f"{LOCAL_CLIENT_URL}/api/user/images?per_page=50",
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                images = result.get('images', [])
                total = result.get('total', 0)
                
                self.log_test(
                    "获取用户图片列表", 
                    True, 
                    f"获取成功，共 {total} 张图片",
                    {'total': total, 'current_page': len(images)}
                )
                
                # 更新用户数据中的图片信息
                self.test_user_data['user_images'] = images
                return True
            else:
                self.log_test(
                    "获取用户图片列表", 
                    False, 
                    f"HTTP错误: {response.status_code}"
                )
                return False
                
        except Exception as e:
            self.log_test(
                "获取用户图片列表", 
                False, 
                f"异常: {str(e)}"
            )
            return False
    
    def test_cloud_sync(self):
        """测试云端同步功能"""
        try:
            # 首先需要修改本地客户端配置以启用云端同步
            print("\n开始测试云端同步功能...")
            print("注意: 需要在本地客户端中将 ENABLE_CLOUD_SYNC 设置为 True")
            print("注意: 需要将 CLOUD_SERVER_URL 设置为 'http://localhost:6006/api'")
            
            # 检查用户是否有图片数据
            if not self.test_user_data.get('user_images'):
                self.log_test(
                    "云端同步准备", 
                    False, 
                    "没有可同步的图片数据"
                )
                return False
            
            # 模拟手动调用同步API（因为本地客户端可能禁用了云端同步）
            print("模拟调用云端同步...")
            
            # 直接构造同步数据
            user_id = self.test_user_data['local_user_id']
            user_images = self.test_user_data['user_images']
            
            # 获取图片文件数据
            image_files = {}
            processed_images = []
            
            for img in user_images:
                try:
                    filename = img['filename']
                    category = img.get('context_info', {}).get('category', 'clothes')
                    
                    # 构造本地文件路径
                    local_file_path = Path(f"saved_images/{user_id}/{category}/{filename}")
                    
                    if local_file_path.exists():
                        # 读取文件并转换为base64
                        with open(local_file_path, 'rb') as f:
                            file_content = f.read()
                        
                        file_base64 = base64.b64encode(file_content).decode('utf-8')
                        image_data_url = f"data:image/png;base64,{file_base64}"
                        image_files[filename] = image_data_url
                        processed_images.append(img)
                        
                        print(f"已处理图片: {filename} ({len(file_content)} bytes)")
                    else:
                        print(f"文件不存在: {local_file_path}")
                        
                except Exception as e:
                    print(f"处理图片文件失败 {img.get('filename', 'unknown')}: {e}")
                    continue
            
            if not image_files:
                self.log_test(
                    "云端同步数据准备", 
                    False, 
                    "没有找到可同步的图片文件"
                )
                return False
            
            # 构造同步数据
            sync_payload = {
                'user_info': {
                    'userId': user_id,
                    'username': self.test_user_data['username'],
                    'email': self.test_user_data['email']
                },
                'images_metadata': processed_images,
                'image_files': image_files,
                'sync_timestamp': datetime.datetime.now().isoformat(),
                'sync_statistics': {
                    'total_metadata_records': len(processed_images),
                    'total_files_found': len(image_files),
                    'total_files_missing': len(user_images) - len(image_files),
                    'total_size': sum(len(base64.b64decode(data.split(',')[1])) for data in image_files.values()),
                    'categories': list(set([
                        img.get('context_info', {}).get('category', 'clothes') 
                        for img in processed_images
                    ]))
                }
            }
            
            print(f"同步数据统计: {sync_payload['sync_statistics']}")
            print(f"元数据数量: {len(sync_payload['images_metadata'])}")
            print(f"文件数据数量: {len(sync_payload['image_files'])}")
            print(f"第一个文件名: {list(sync_payload['image_files'].keys())[0] if sync_payload['image_files'] else '空'}")
            print(f"第一个文件数据大小: {len(sync_payload['image_files'][list(sync_payload['image_files'].keys())[0]]) if sync_payload['image_files'] else 0}")
            
            token = self.test_user_data.get('token')
            
            # 添加认证头
            headers = {'Content-Type': 'application/json'}
            if token:
                headers['Authorization'] = f'Bearer {token}'
            else:
                print("警告：未找到token，将尝试无认证请求")
            
            # 发送同步请求到云端
            response = self.cloud_session.post(
                f"{CLOUD_SERVER_URL}/api/sync/user/{user_id}",
                json=sync_payload,
                timeout=300,  # 5分钟超时
                headers=headers
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    sync_result = result.get('upserted', {})
                    self.log_test(
                        "云端数据同步", 
                        True, 
                        f"同步成功，保存 {sync_result.get('saved_files')} 个文件",
                        sync_result
                    )
                    
                    # 测试同步状态查询
                    self.test_sync_status()
                    return True
                else:
                    self.log_test(
                        "云端数据同步", 
                        False, 
                        f"同步失败: {result.get('error', 'Unknown error')}",
                        result
                    )
                    return False
            else:
                self.log_test(
                    "云端数据同步", 
                    False, 
                    f"HTTP错误: {response.status_code}, 响应: {response.text[:200]}"
                )
                return False
                
        except Exception as e:
            self.log_test(
                "云端同步测试", 
                False, 
                f"异常: {str(e)}"
            )
            import traceback
            traceback.print_exc()
            return False
    
    def test_sync_status(self):
        """测试同步状态查询"""
        try:
            user_id = self.test_user_data['local_user_id']
            
            headers = {'Content-Type': 'application/json'}
            headers['Authorization'] = f"Bearer {self.test_user_data['token']}"
            
            # 发送同步请求到云端
            response = self.cloud_session.get(
                f"{CLOUD_SERVER_URL}/api/user/{user_id}/sync/status",
                timeout=300,  # 5分钟超时
                headers=headers
            )
        
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    sync_history = result.get('sync_history', [])
                    self.log_test(
                        "同步状态查询", 
                        True, 
                        f"查询成功，共 {len(sync_history)} 条同步记录",
                        {'history_count': len(sync_history), 'latest': sync_history[0] if sync_history else None}
                    )
                    return True
            
            self.log_test(
                "同步状态查询", 
                False, 
                f"查询失败: {response.text}"
            )
            return False
            
        except Exception as e:
            self.log_test(
                "同步状态查询", 
                False, 
                f"异常: {str(e)}"
            )
            return False
    
    def test_local_client_sync_api(self):
        """测试本地客户端的同步API"""
        try:
            response = self.local_session.post(
                f"{LOCAL_CLIENT_URL}/api/cloud/sync",
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    self.log_test(
                        "本地客户端同步API", 
                        True, 
                        "同步任务启动成功",
                        result
                    )
                    return True
                else:
                    self.log_test(
                        "本地客户端同步API", 
                        False, 
                        f"同步失败: {result.get('error', 'Unknown error')}"
                    )
                    return False
            else:
                self.log_test(
                    "本地客户端同步API", 
                    False, 
                    f"HTTP错误: {response.status_code}, 可能是云端同步被禁用"
                )
                return False
                
        except Exception as e:
            self.log_test(
                "本地客户端同步API", 
                False, 
                f"异常: {str(e)}"
            )
            return False
    
    
    
    def run_all_tests(self):
        """运行所有测试"""
        print("🧪 开始服务器同步功能测试")
        print("=" * 60)
        
        test_functions = [
            self.test_cloud_server_status,
            self.test_local_client_status,
            self.test_user_registration,
            self.test_user_login,
            self.my_login,  # 添加云端登录测试
            self.test_image_upload,
            self.test_get_user_images,
            self.test_cloud_sync,
            self.test_local_client_sync_api
        ]
        
        for test_func in test_functions:
            try:
                print(f"\n📋 执行测试: {test_func.__name__}")
                test_func()
                time.sleep(1)  # 短暂延迟避免请求过快
            except Exception as e:
                self.log_test(
                    test_func.__name__, 
                    False, 
                    f"测试执行异常: {str(e)}"
                )
        
        self.generate_test_report()
    
    
    def generate_test_report(self):
        """生成测试报告"""
        print("\n" + "=" * 60)
        print("📊 测试报告")
        print("=" * 60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results if result['success'])
        failed_tests = total_tests - passed_tests
        
        print(f"总测试数: {total_tests}")
        print(f"通过: {passed_tests} ✅")
        print(f"失败: {failed_tests} ❌")
        print(f"成功率: {(passed_tests/total_tests*100):.1f}%")
        
        if failed_tests > 0:
            print("\n❌ 失败的测试:")
            for result in self.test_results:
                if not result['success']:
                    print(f"  - {result['test_name']}: {result['message']}")
        
        print(f"\n📝 测试用户数据:")
        print(f"  用户名: {self.test_user_data.get('username', 'N/A')}")
        print(f"  本地用户ID: {self.test_user_data.get('local_user_id', 'N/A')}")
        print(f"  云端用户ID: {self.test_user_data.get('cloud_user_id', 'N/A')}")
        print(f"  上传图片数: {len(self.test_user_data.get('uploaded_images', []))}")
        
        # 保存详细报告到文件
        report_file = TEST_DATA_DIR / f"test_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump({
                'summary': {
                    'total_tests': total_tests,
                    'passed_tests': passed_tests,
                    'failed_tests': failed_tests,
                    'success_rate': passed_tests/total_tests*100
                },
                'test_results': self.test_results,
                'test_user_data': self.test_user_data,
                'timestamp': datetime.datetime.now().isoformat()
            }, f, indent=2, ensure_ascii=False)
        
        print(f"\n📄 详细报告已保存到: {report_file}")

def main():
    """主函数"""
    print("🚀 启动服务器同步功能测试")
    print("请确保以下服务正在运行:")
    print("  - 本地客户端: http://localhost:8080")
    print("  - 云端服务器: http://localhost:6006")
    print("\n开始测试前，请确认:")
    print("  1. 两个服务器都已启动")
    print("  2. 如果要测试完整同步功能，请在 app.py 中设置:")
    print("     ENABLE_CLOUD_SYNC = True")
    print("     CLOUD_SERVER_URL = 'http://localhost:6006/api'")
    
    input("\n按 Enter 键开始测试...")
    
    tester = ServerTester()
    tester.run_all_tests()
    
    print("\n🎉 测试完成!")

if __name__ == "__main__":
    main()
