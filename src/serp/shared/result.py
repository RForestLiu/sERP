"""
Result 类型 — 统一的操作结果，避免异常驱动的控制流。
"""
from dataclasses import dataclass, field
from typing import Generic, TypeVar, Optional

T = TypeVar("T")


@dataclass
class Result(Generic[T]):
    """操作结果 — 成功时携带值，失败时携带错误信息。

    用法:
        Result.ok(value)
        Result.fail("something wrong")
    """
    success: bool
    value: Optional[T] = None
    error: str = ""
    errors: list[str] = field(default_factory=list)

    @classmethod
    def ok(cls, value: T = None) -> "Result[T]":
        return cls(success=True, value=value)

    @classmethod
    def fail(cls, error: str, errors: list[str] = None) -> "Result[T]":
        return cls(success=False, error=error, errors=errors or [error])

    @property
    def is_success(self) -> bool:
        return self.success

    @property
    def is_failure(self) -> bool:
        return not self.success

    def unwrap(self) -> T:
        if not self.success:
            raise ValueError(f"Called unwrap on failed result: {self.error}")
        return self.value
