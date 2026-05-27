"""
领域异常基类。
"""


class DomainError(Exception):
    """领域异常基类"""
    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code or self.__class__.__name__


class NotFoundError(DomainError):
    """实体未找到"""
    def __init__(self, entity_type: str, entity_id: str):
        super().__init__(f"{entity_type} with id '{entity_id}' not found", "NOT_FOUND")
        self.entity_type = entity_type
        self.entity_id = entity_id


class ValidationError(DomainError):
    """校验错误"""
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors), "VALIDATION_ERROR")
        self.errors = errors


class ConflictError(DomainError):
    """冲突错误（如重复创建）"""
    def __init__(self, message: str):
        super().__init__(message, "CONFLICT")
