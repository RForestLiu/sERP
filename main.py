"""
项目入口 — 加载配置、启动 Flask
（日志配置在 app.py 顶部，保证 reloader 子进程也能生效）
"""
from dotenv import load_dotenv
load_dotenv()

from app import app

if __name__ == "__main__":
    app.run(debug=True, port=5000)
