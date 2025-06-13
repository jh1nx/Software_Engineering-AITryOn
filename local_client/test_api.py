import requests
import json
import sys
from pathlib import Path

class APITester:
    def __init__(self, base_url="http://localhost:8080"):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json'
        })
    
    def print_help(self):
        """打印帮助信息"""
        print(f"""
{'='*60}
图片处理服务器 API 测试工具
{'='*60}

服务器地址: {self.base_url}
API文档: 请查看 API_DOCUMENTATION.md

使用方法:
  python test_api.py [服务器地址] [测试类型]

参数说明:
  服务器地址: 可选，默认 http://localhost:8080
  测试类型: 可选，full(完整测试) 或 register(注册测试)，默认 full

示例:
  python test_api.py                                    # 使用默认配置运行完整测试
  python test_api.py http://localhost:8080             # 指定服务器地址
  python test_api.py http://localhost:8080 register    # 运行注册测试
  python test_api.py help                              # 显示此帮助信息

测试流程:
  完整测试 (full):
    1. 检查系统状态
    2. 检查登录状态
    3. 尝试登录 (如果未登录)
    4. 获取用户资料
    5. 获取图片列表
    6. 下载第一张图片
    7. 测试登出
    8. 再次检查登录状态

  注册测试 (register):
    1. 检查系统状态
    2. 注册新用户
    3. 使用新用户登录
    4. 获取新用户资料
    5. 检查新用户图片列表

注意事项:
  - 确保服务器已启动
  - 默认测试账户: admin/admin123
  - 下载的图片保存在 test_downloads/ 目录
  - 请参考 API_DOCUMENTATION.md 了解详细接口信息

{'='*60}
""")
    
    def print_request(self, title, method, url, data=None, params=None):
        """打印请求信息"""
        print(f"\n{'='*20} 请求信息 {'='*20}")
        print(f"标题: {title}")
        print(f"方法: {method}")
        print(f"URL: {url}")
        if params:
            print(f"查询参数: {json.dumps(params, indent=2, ensure_ascii=False)}")
        if data:
            print(f"请求体: {json.dumps(data, indent=2, ensure_ascii=False)}")
        print(f"请求头: {json.dumps(dict(self.session.headers), indent=2, ensure_ascii=False)}")
    
    def print_response(self, title, response):
        """打印响应信息"""
        print(f"\n{'='*20} 响应信息 {'='*20}")
        print(f"标题: {title}")
        print(f"状态码: {response.status_code}")
        print(f"响应头: {json.dumps(dict(response.headers), indent=2, ensure_ascii=False)}")
        try:
            response_data = response.json()
            print(f"响应内容: {json.dumps(response_data, indent=2, ensure_ascii=False)}")
        except:
            print(f"响应内容: {response.text}")
        print(f"{'='*50}")
    
    def test_auth_check(self):
        """测试检查登录状态"""
        print("1. 检查当前登录状态...")
        url = f"{self.base_url}/api/auth/check"
        
        self.print_request("检查登录状态", "GET", url)
        response = self.session.get(url)
        self.print_response("检查登录状态", response)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('authenticated'):
                print(f"✓ 已登录用户: {data['user']['username']}")
                return data['user']
            else:
                print("✗ 未登录，需要先登录")
                return None
        else:
            print("✗ 检查登录状态失败")
            return None
    
    def test_login(self, username="admin", password="admin123"):
        """测试登录"""
        print(f"2. 尝试登录 (用户名: {username})...")
        url = f"{self.base_url}/api/login"
        login_data = {
            "username": username,
            "password": password,
            "remember_me": True
        }
        
        self.print_request("用户登录", "POST", url, data=login_data)
        response = self.session.post(url, json=login_data)
        self.print_response("用户登录", response)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print(f"✓ 登录成功: {data['user']['username']}")
                return data['user']
            else:
                print(f"✗ 登录失败: {data.get('error')}")
                return None
        else:
            print("✗ 登录请求失败")
            return None
    
    def test_get_user_profile(self):
        """测试获取用户信息"""
        print("3. 获取用户资料...")
        url = f"{self.base_url}/api/user/profile"
        
        self.print_request("获取用户资料", "GET", url)
        response = self.session.get(url)
        self.print_response("获取用户资料", response)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                user_info = data['user']
                print(f"✓ 用户信息获取成功:")
                print(f"  - 用户ID: {user_info['user_id']}")
                print(f"  - 用户名: {user_info['username']}")
                print(f"  - 邮箱: {user_info['email']}")
                print(f"  - 图片数量: {user_info['image_count']}")
                print(f"  - 创建时间: {user_info['created_at']}")
                return user_info
            else:
                print(f"✗ 获取用户信息失败: {data.get('error')}")
                return None
        else:
            print(f"✗ 获取用户信息请求失败: {response.status_code}")
            return None
    
    def test_get_user_images(self, per_page=10):
        """测试获取用户图片列表"""
        print(f"4. 获取用户图片列表 (每页{per_page}张)...")
        url = f"{self.base_url}/api/user/images"
        params = {"per_page": per_page}
        
        self.print_request("获取用户图片列表", "GET", url, params=params)
        response = self.session.get(url, params=params)
        self.print_response("获取用户图片列表", response)
        
        if response.status_code == 200:
            data = response.json()
            images = data.get('images', [])
            total = data.get('total', 0)
            
            print(f"✓ 图片列表获取成功:")
            print(f"  - 总图片数: {total}")
            print(f"  - 当前页图片数: {len(images)}")
            print(f"  - 总页数: {data.get('pages', 0)}")
            
            if images:
                print("  - 图片列表:")
                for i, image in enumerate(images):
                    print(f"    [{i+1}] ID: {image['id'][:8]}... | 文件: {image['filename']}")
                    print(f"        页面: {image.get('page_title', '未知')}")
                    print(f"        时间: {image['saved_at']}")
                    print(f"        大小: {image.get('file_size', 0)} bytes")
                    print(f"        预览URL: {image.get('preview_url', '无')}")
                    print()
            
            return images
        else:
            print(f"✗ 获取图片列表失败: {response.status_code}")
            return []
    
    def test_get_first_image(self, images):
        """测试获取第一张图片"""
        if not images:
            print("5. 没有图片可供测试")
            return None
        
        first_image = images[0]
        print(f"5. 获取第一张图片: {first_image['filename']}")
        
        # 获取图片文件
        image_url = first_image.get('preview_url')
        if image_url:
            # 构建完整URL
            if not image_url.startswith('http'):
                image_url = f"{self.base_url}{image_url}"
            
            print(f"图片URL: {image_url}")
            
            self.print_request("获取图片文件", "GET", image_url)
            response = self.session.get(image_url)
            
            print(f"\n{'='*20} 图片响应信息 {'='*20}")
            print(f"状态码: {response.status_code}")
            print(f"Content-Type: {response.headers.get('Content-Type', 'unknown')}")
            print(f"Content-Length: {response.headers.get('Content-Length', 'unknown')}")
            print(f"实际内容长度: {len(response.content)} bytes")
            
            if response.status_code == 200:
                # 保存图片到测试目录
                test_dir = Path("test_downloads")
                test_dir.mkdir(exist_ok=True)
                
                image_path = test_dir / first_image['filename']
                with open(image_path, 'wb') as f:
                    f.write(response.content)
                
                print(f"✓ 图片下载成功，保存至: {image_path.absolute()}")
                print(f"  - 文件大小: {len(response.content)} bytes")
                return image_path
            else:
                print(f"✗ 图片下载失败: {response.status_code}")
                if response.text:
                    print(f"错误信息: {response.text}")
                return None
        else:
            print("✗ 图片URL不可用")
            return None
    
    def test_system_status(self):
        """测试系统状态"""
        print("0. 检查系统状态...")
        url = f"{self.base_url}/api/status"
        
        self.print_request("系统状态检查", "GET", url)
        response = self.session.get(url)
        self.print_response("系统状态检查", response)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✓ 系统运行正常")
            print(f"  - 状态: {data.get('status')}")
            print(f"  - 时间: {data.get('timestamp')}")
            print(f"  - 总图片数: {data.get('total_images')}")
            return True
        else:
            print("✗ 系统状态检查失败")
            return False
    
    def test_register_new_user(self, username=None, email=None, password=None):
        """测试注册新用户"""
        if not username:
            username = f"testuser_{int(__import__('time').time())}"
        if not email:
            email = f"{username}@test.com"
        if not password:
            password = "test123456"
        
        print(f"测试注册新用户: {username}")
        url = f"{self.base_url}/api/register"
        register_data = {
            "username": username,
            "email": email,
            "password": password
        }
        
        self.print_request("用户注册", "POST", url, data=register_data)
        response = self.session.post(url, json=register_data)
        self.print_response("用户注册", response)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print(f"✓ 注册成功: {username}")
                print(f"  - 用户ID: {data.get('user_id')}")
                return {
                    'username': username,
                    'email': email,
                    'password': password,
                    'user_id': data.get('user_id')
                }
            else:
                print(f"✗ 注册失败: {data.get('error')}")
                return None
        else:
            print("✗ 注册请求失败")
            return None
    
    def test_logout(self):
        """测试登出"""
        print("测试用户登出...")
        url = f"{self.base_url}/api/logout"
        
        self.print_request("用户登出", "POST", url)
        response = self.session.post(url)
        self.print_response("用户登出", response)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print(f"✓ 登出成功")
                return True
            else:
                print(f"✗ 登出失败: {data.get('error')}")
                return False
        else:
            print("✗ 登出请求失败")
            return False
    
    def run_full_test(self):
        """运行完整测试流程"""
        print("开始API测试...")
        print(f"测试服务器: {self.base_url}")
        print("详细API文档请查看: API_DOCUMENTATION.md")
        
        # 0. 检查系统状态
        if not self.test_system_status():
            print("系统状态异常，终止测试")
            return
        
        # 1. 检查登录状态
        current_user = self.test_auth_check()
        
        # 2. 如果未登录，尝试登录
        if not current_user:
            current_user = self.test_login()
            if not current_user:
                print("登录失败，终止测试")
                return
        
        # 3. 获取用户资料
        user_profile = self.test_get_user_profile()
        if not user_profile:
            print("获取用户资料失败，终止测试")
            return
        
        # 4. 获取图片列表
        images = self.test_get_user_images()
        
        # 5. 获取第一张图片
        if images:
            self.test_get_first_image(images)
        else:
            print("5. 用户暂无图片")
        
        # 6. 测试登出
        self.test_logout()
        
        # 7. 再次检查登录状态
        print("\n登出后检查登录状态:")
        self.test_auth_check()
        
        print("\n" + "="*50)
        print("测试完成!")
        print("="*50)
    
    def run_register_test(self):
        """运行注册测试"""
        print("开始注册功能测试...")
        print("详细API文档请查看: API_DOCUMENTATION.md")
        
        # 1. 检查系统状态
        if not self.test_system_status():
            return
        
        # 2. 测试注册新用户
        new_user = self.test_register_new_user()
        if not new_user:
            return
        
        # 3. 用新用户登录
        login_user = self.test_login(new_user['username'], new_user['password'])
        if not login_user:
            return
        
        # 4. 获取新用户资料
        self.test_get_user_profile()
        
        # 5. 获取新用户图片（应该为空）
        self.test_get_user_images()
        
        print("\n注册测试完成!")

def main():
    """主函数"""
    # 检查是否请求帮助
    if len(sys.argv) > 1 and sys.argv[1] in ['help', '-h', '--help']:
        tester = APITester()
        tester.print_help()
        return
    
    # 可以通过命令行参数指定服务器地址和测试类型
    base_url = "http://localhost:8080"
    test_type = "full"  # full 或 register
    
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    if len(sys.argv) > 2:
        test_type = sys.argv[2]
    
    tester = APITester(base_url)
    
    try:
        if test_type == "register":
            tester.run_register_test()
        else:
            tester.run_full_test()
    except KeyboardInterrupt:
        print("\n测试被用户中断")
    except Exception as e:
        print(f"\n测试过程中出错: {e}")
        print("\n请检查:")
        print("1. 服务器是否已启动")
        print("2. 服务器地址是否正确")
        print("3. 网络连接是否正常")
        print("\n详细错误信息:")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
