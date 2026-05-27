"""
Product 域 - 基础设施层。
"""
from .json_repositories import JsonProductRepository
from . import handlers

__all__ = [
    "JsonProductRepository",
    "handlers",
]
