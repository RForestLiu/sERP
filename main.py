"""
项目入口 — 加载配置、初始化日志、启动 Flask
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

# 统一日志格式
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
    datefmt="%H:%M:%S"
)

from app import app

if __name__ == "__main__":
    app.run(debug=True, port=5000)
