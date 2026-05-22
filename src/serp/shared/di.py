"""
DIContainer — 简易依赖注入容器。
"""
from typing import Any, Callable, Type, TypeVar

T = TypeVar("T")

Factory = Callable[[], Any]


class DIContainer:
    """轻量级 DI 容器 — 注册工厂函数或实例，按名称解析。

    用法:
        di = DIContainer()
        di.register("settings_repo", lambda: JsonSettingsRepository("data/settings.json"))
        di.register_instance("event_bus", SyncEventBus())
        repo = di.resolve("settings_repo")
    """

    def __init__(self):
        self._factories: dict[str, Factory] = {}
        self._instances: dict[str, Any] = {}

    def register(self, name: str, factory: Factory):
        self._factories[name] = factory

    def register_instance(self, name: str, instance: Any):
        self._instances[name] = instance

    def resolve(self, name: str) -> Any:
        if name in self._instances:
            return self._instances[name]
        factory = self._factories.get(name)
        if not factory:
            raise KeyError(f"Dependency '{name}' not registered")
        instance = factory()
        self._instances[name] = instance
        return instance

    def resolve_type(self, type_: Type[T]) -> T:
        """按类型解析（注册名需为类型的全限定名）"""
        name = type_.__name__
        return self.resolve(name)
