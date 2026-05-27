"""
OzonCategory 域 - 实体与聚合根。
"""
from dataclasses import dataclass, field

from src.serp.shared import Entity, AggregateRoot


@dataclass
class CategoryNode(Entity):
    """品类树节点"""
    name: str = ""
    children: list["CategoryNode"] = field(default_factory=list, repr=False)
    type_id: int = 0
    type_name: str = ""
    description_category_id: int = 0
    _name_cn: str = ""  # 翻译后的中文名（从翻译缓存注入）

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def count_nodes(self) -> int:
        """递归统计子节点数（含自身）"""
        cnt = 1
        for child in self.children:
            cnt += child.count_nodes()
        return cnt

    def flatten(self, path: str = "", root_type_id: int = None, root_type_name: str = "") -> list[dict]:
        """展平为字典列表，包含路径信息，用于翻译和匹配"""
        rid = root_type_id if root_type_id is not None else self.type_id
        rname = root_type_name or self.name or self.type_name
        current_path = f"{path} > {self.name}" if path else (self.name or self.type_name)
        nodes = [{
            "id": self.id,
            "name": self.name or self.type_name,
            "path": current_path,
            "type_id": rid,
            "type_name": rname,
        }]
        for child in self.children:
            nodes.extend(child.flatten(current_path, rid, rname))
        return nodes

    def to_dict(self, translations: dict[str, str] = None) -> dict:
        """序列化为字典"""
        result = {
            "type_id": self.type_id if self.type_id else None,
            "description_category_id": self.description_category_id or (int(self.id) if self.id and not self.type_id else None),
            "type_name": self.type_name or self.name,
            "category_name": self.name,
        }
        if translations:
            cn = translations.get(str(self.id), "")
            if cn:
                result["_name_cn"] = cn
        if self.children:
            result["children"] = [c.to_dict(translations) for c in self.children]
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "CategoryNode":
        """从 Ozon API 返回的节点 dict 构建"""
        description_category_id = data.get("description_category_id") or data.get("category_id") or 0
        type_id = data.get("type_id") or 0
        node_id = str(type_id or description_category_id or "")
        name = data.get("type_name") or data.get("category_name") or data.get("title") or ""
        children_data = data.get("children", [])
        children = [CategoryNode.from_dict(c) for c in children_data] if children_data else []
        node = cls(
            id=node_id,
            name=name,
            children=children,
            type_id=type_id,
            type_name=data.get("type_name") or "",
            description_category_id=int(description_category_id or 0),
        )
        for child in node.children:
            if not child.description_category_id and node.description_category_id:
                child.description_category_id = node.description_category_id
        return node


@dataclass
class CategoryTree(AggregateRoot):
    """品类树聚合根"""
    store_id: str = ""
    root_nodes: list[CategoryNode] = field(default_factory=list)

    def count_nodes(self) -> int:
        return sum(n.count_nodes() for n in self.root_nodes)

    def flatten_all(self) -> list[dict]:
        """展平所有节点为字典列表"""
        result = []
        for node in self.root_nodes:
            result.extend(node.flatten())
        return result

    def find_node(self, node_id: int) -> CategoryNode | None:
        """按 ID 查找节点"""

        def _search(nodes):
            for n in nodes:
                if str(n.id) == str(node_id):
                    return n
                if n.children:
                    found = _search(n.children)
                    if found:
                        return found
            return None

        return _search(self.root_nodes)

    def find_parent(self, node_id: int) -> CategoryNode | None:
        """查找节点的父节点"""

        def _search(nodes, parent=None):
            for n in nodes:
                if str(n.id) == str(node_id):
                    return parent
                if n.children:
                    found = _search(n.children, n)
                    if found is not None:
                        return found
            return None

        return _search(self.root_nodes)

    def find_siblings(self, node_id: int, only_leaves: bool = True) -> list[CategoryNode]:
        """查找同父节点的兄弟品类"""
        parent = self.find_parent(node_id)
        if parent:
            return [c for c in parent.children if str(c.id) != str(node_id) and (not only_leaves or c.is_leaf)]
        # 根级节点
        return [n for n in self.root_nodes if str(n.id) != str(node_id) and (not only_leaves or n.is_leaf)]

    def collect_leaves(self) -> list[CategoryNode]:
        """收集所有叶子节点"""
        result = []

        def _collect(nodes):
            for n in nodes:
                if n.is_leaf:
                    result.append(n)
                else:
                    _collect(n.children)

        _collect(self.root_nodes)
        return result

    def enrich_translations(self, translations: dict[str, str]) -> list[dict]:
        """为整棵树附加中文翻译，返回可序列化的列表"""

        def _enrich(nodes):
            result = []
            for n in nodes:
                cn = translations.get(str(n.id), "")
                d = n.to_dict()
                if cn:
                    d["_name_cn"] = cn
                if n.children:
                    d["children"] = _enrich(n.children)
                result.append(d)
            return result

        return _enrich(self.root_nodes)

    @classmethod
    def from_api_result(cls, store_id: str, tree_data: list[dict]) -> "CategoryTree":
        """从 Ozon API response.result 构建"""
        root_nodes = [CategoryNode.from_dict(d) for d in tree_data] if tree_data else []
        return cls(store_id=store_id, root_nodes=root_nodes)

    def to_dict(self) -> list[dict]:
        """序列化为 list[dict]（与 Ozon API 格式兼容）"""
        return [n.to_dict() for n in self.root_nodes]
