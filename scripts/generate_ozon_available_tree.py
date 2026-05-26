from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


STORE_ID = "ozon_anling"
TREE_PATH = Path(f"data/ozon_cache/{STORE_ID}_category_tree.json")
TRANSLATIONS_PATH = Path(f"data/ozon_cache/{STORE_ID}_translations.json")
EXCLUDED_PATH = Path(f"data/ozon_cache/{STORE_ID}_excluded_categories.json")
OUT_DIR = Path("docs/generated")
JSON_OUT = OUT_DIR / "ozon_available_category_tree.json"
LLM_OUT = OUT_DIR / "ozon_available_category_tree_llm.txt"
REPORT_OUT = OUT_DIR / "ozon_available_category_tree_report.md"


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def node_name(node: dict) -> str:
    return str(node.get("category_name") or node.get("type_name") or "").strip()


def node_id(node: dict):
    return node.get("type_id") or node.get("description_category_id")


def description_category_id(node: dict, parent_description_category_id=None):
    return (
        node.get("description_category_id")
        or parent_description_category_id
        or (None if node.get("type_id") else node_id(node))
    )


def translated_name(node: dict, translations: dict) -> str:
    nid = node_id(node)
    value = translations.get(str(nid), "") if nid is not None else ""
    return str(value or "").split(" > ")[-1].strip()


def display_name(node: dict, translations: dict) -> str:
    name = node_name(node)
    cn = translated_name(node, translations)
    if cn and cn != name:
        return f"{name} ({cn})"
    return name


def compact_node(node: dict, translations: dict, excluded_ids: set[int], parent_description_category_id=None):
    stats["source_nodes"] += 1
    if node.get("disabled") is True:
        stats["disabled_nodes_pruned"] += 1
        return None

    desc_id = description_category_id(node, parent_description_category_id)
    type_id = node.get("type_id")
    is_leaf = type_id is not None

    if is_leaf:
        stats["source_leaf_nodes"] += 1
        if desc_id is not None and int(desc_id) in excluded_ids:
            stats["excluded_leaf_nodes_pruned"] += 1
            return None
        stats["available_leaf_nodes"] += 1
        return {
            "name": node_name(node),
            "name_cn": translated_name(node, translations),
            "description_category_id": int(desc_id) if desc_id is not None else None,
            "type_id": int(type_id),
            "children": [],
        }

    children = []
    for child in node.get("children") or []:
        item = compact_node(child, translations, excluded_ids, desc_id)
        if item is not None:
            children.append(item)

    if not children:
        stats["empty_branch_nodes_pruned"] += 1
        return None

    stats["available_category_nodes"] += 1
    return {
        "name": node_name(node),
        "name_cn": translated_name(node, translations),
        "description_category_id": int(desc_id) if desc_id is not None else None,
        "children": children,
    }


def write_llm_tree(nodes: list[dict], translations: dict) -> str:
    lines: list[str] = []

    def walk(item: dict, depth: int):
        name = item["name"]
        cn = item.get("name_cn") or ""
        text = f"{name} ({cn})" if cn and cn != name else name
        lines.append(f"{'  ' * depth}- {text}")
        for child in item.get("children") or []:
            walk(child, depth + 1)

    for root in nodes:
        walk(root, 0)
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    tree = load_json(TREE_PATH, [])
    translations = load_json(TRANSLATIONS_PATH, {})
    excluded_raw = load_json(EXCLUDED_PATH, [])
    excluded_ids = {int(x) for x in excluded_raw if str(x).isdigit()}
    stats = {
        "source_nodes": 0,
        "source_leaf_nodes": 0,
        "available_category_nodes": 0,
        "available_leaf_nodes": 0,
        "disabled_nodes_pruned": 0,
        "excluded_leaf_nodes_pruned": 0,
        "empty_branch_nodes_pruned": 0,
    }

    available_roots = []
    for root in tree:
        item = compact_node(root, translations, excluded_ids)
        if item is not None:
            available_roots.append(item)

    generated_at = datetime.now().isoformat(timespec="seconds")
    payload = {
        "store_id": STORE_ID,
        "generated_at": generated_at,
        "source": str(TREE_PATH),
        "availability_basis": [
            "Ozon category tree node disabled is not true",
            "Known locally excluded description_category_id values are pruned",
        ],
        "attribute_api_validated": False,
        "excluded_description_category_ids": sorted(excluded_ids),
        "stats": stats,
        "roots": available_roots,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LLM_OUT.write_text(write_llm_tree(available_roots, translations), encoding="utf-8")
    REPORT_OUT.write_text(
        "\n".join([
            "# Ozon Available Category Tree Report",
            "",
            f"- Store: `{STORE_ID}`",
            f"- Generated: `{generated_at}`",
            f"- Source tree: `{TREE_PATH.as_posix()}`",
            f"- JSON tree: `{JSON_OUT.as_posix()}`",
            f"- LLM tree: `{LLM_OUT.as_posix()}`",
            "",
            "## Availability Basis",
            "",
            "- Included nodes: `disabled != true`.",
            "- Included leaves: leaf has `type_id` and its `description_category_id` is not in local excluded cache.",
            "- Attribute API full validation: `not run` for this artifact.",
            "",
            "## Counts",
            "",
            f"- Source nodes walked: `{stats['source_nodes']}`",
            f"- Source leaf nodes: `{stats['source_leaf_nodes']}`",
            f"- Available category nodes: `{stats['available_category_nodes']}`",
            f"- Available leaf nodes: `{stats['available_leaf_nodes']}`",
            f"- Disabled nodes pruned: `{stats['disabled_nodes_pruned']}`",
            f"- Known-excluded leaves pruned: `{stats['excluded_leaf_nodes_pruned']}`",
            f"- Empty branch nodes pruned: `{stats['empty_branch_nodes_pruned']}`",
            f"- Local excluded description_category_id values: `{sorted(excluded_ids)}`",
            "",
            "## Verification",
            "",
            "This validates the first half of the design: the LLM-facing tree can be generated without disabled or locally excluded nodes. The second half, full leaf validation through `/v1/description-category/attribute`, should run as a separate preflight job because it may require thousands of API calls and rate-limit handling.",
            "",
            "Local checks performed by the generator:",
            "",
            "- Every leaf in the JSON tree has `type_id`.",
            "- No leaf in the JSON tree uses a locally excluded `description_category_id`.",
            "- Empty branches are pruned, so every visible branch can reach at least one selectable leaf.",
            "- The LLM tree is generated from UTF-8 Ozon API names, not screenshots or OCR text.",
            "",
        ]) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"json": str(JSON_OUT), "llm": str(LLM_OUT), "report": str(REPORT_OUT), "stats": stats}, ensure_ascii=False, indent=2))
