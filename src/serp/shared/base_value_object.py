"""
ValueObject 基类 — 不可变，按值相等。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ValueObject:
    """值对象基类。子类用 @dataclass(frozen=True) 继承。"""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._attrs()})"

    def _attrs(self) -> str:
        fields = {f.name: getattr(self, f.name) for f in self.__dataclass_fields__.values()}
        return ", ".join(f"{k}={v!r}" for k, v in fields.items())
