"""
Facade 抽象基类 — 所有域的对外的统一入口。
"""
from abc import ABC


class Facade(ABC):
    """域外观基类。每个域定义一个 Facade ABC 作为公共契约。"""
    pass
