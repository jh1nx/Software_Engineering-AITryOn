import os
import sys
from pathlib import Path

# 添加当前目录到Python路径
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

# 导入应用
from app import app

if __name__ == '__main__':
    print("=" * 50)
    print("图片处理客户端启动中...")
    print("=" * 50)
    print(f"保存目录: {current_dir / 'saved_images'}")
    print(f"数据库文件: {current_dir / 'image_database.db'}")
    print("WebUI地址: http://localhost:8080")
    print("API地址: http://localhost:8080/api")
    print("=" * 50)
    print("按 Ctrl+C 停止服务器")
    print("=" * 50)
    
    try:
        app.run(host='localhost', port=8080, debug=False)
    except KeyboardInterrupt:
        print("\n服务器已停止")
