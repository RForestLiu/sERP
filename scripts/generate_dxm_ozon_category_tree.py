from __future__ import annotations

import argparse
import asyncio
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp


CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
DXM_CATEGORY_URL = "https://www.dianxiaomi.com/api/ozonCategoryNew/list.json"
OUT_DIR = Path("docs/generated")
JSON_OUT = OUT_DIR / "dxm_ozon_available_category_tree.json"
LLM_OUT = OUT_DIR / "dxm_ozon_available_category_tree_llm.txt"
REPORT_OUT = OUT_DIR / "dxm_ozon_available_category_tree_report.md"


class DxmCategoryCrawler:
    def __init__(self, ws: aiohttp.ClientWebSocketResponse, *, delay: float = 0.03) -> None:
        self.ws = ws
        self.delay = delay
        self.msg_id = 1
        self.visited: set[str] = set()
        self.stats = {
            "requests": 0,
            "source_nodes": 0,
            "available_branch_nodes": 0,
            "available_leaf_nodes": 0,
            "deleted_nodes_pruned": 0,
            "non_selectable_leaf_nodes_pruned": 0,
            "duplicate_nodes_skipped": 0,
            "empty_branch_nodes_pruned": 0,
            "request_errors": 0,
        }

    async def evaluate_json(self, expression: str) -> Any:
        msg_id = self.msg_id
        self.msg_id += 1
        await self.ws.send_json({
            "id": msg_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
        })
        while True:
            msg = await self.ws.receive_json()
            if msg.get("id") != msg_id:
                continue
            result = msg.get("result", {})
            if "exceptionDetails" in result:
                raise RuntimeError(str(result["exceptionDetails"]))
            value = result.get("result", {}).get("value")
            if isinstance(value, str):
                return json.loads(value)
            return value

    async def fetch_children(self, category_id: str) -> list[dict[str, Any]]:
        expression = f"""
        (async () => {{
          const body = new URLSearchParams({{ categoryId: {json.dumps(category_id)} }});
          const res = await fetch({json.dumps(DXM_CATEGORY_URL)}, {{
            method: "POST",
            credentials: "include",
            headers: {{
              "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
              "x-requested-with": "XMLHttpRequest"
            }},
            body
          }});
          const text = await res.text();
          let data;
          try {{ data = JSON.parse(text); }} catch (e) {{ data = {{ code: -999, msg: text.slice(0, 500), data: null }}; }}
          return JSON.stringify({{ status: res.status, data }});
        }})()
        """
        self.stats["requests"] += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        payload = await self.evaluate_json(expression)
        if payload.get("status") != 200 or payload.get("data", {}).get("code") != 0:
            self.stats["request_errors"] += 1
            raise RuntimeError(f"DXM category request failed for {category_id}: {payload}")
        data = payload.get("data", {}).get("data") or []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    async def crawl_children(self, parent_id: str, depth: int = 0) -> list[dict[str, Any]]:
        children = await self.fetch_children(parent_id)
        compact_children: list[dict[str, Any]] = []
        for child in children:
            item = await self.compact_node(child, depth)
            if item is not None:
                compact_children.append(item)
        return compact_children

    async def compact_node(self, node: dict[str, Any], depth: int) -> dict[str, Any] | None:
        self.stats["source_nodes"] += 1
        node_id = str(node.get("categoryId") or "").strip()
        if not node_id:
            self.stats["empty_branch_nodes_pruned"] += 1
            return None
        if node_id in self.visited:
            self.stats["duplicate_nodes_skipped"] += 1
            return None
        self.visited.add(node_id)

        if str(node.get("isDel", "0")) != "0":
            self.stats["deleted_nodes_pruned"] += 1
            return None

        is_leaf = str(node.get("isLeaf", "0")) == "1"
        type_id = str(node.get("typeId") or "").strip()
        description_category_id = str(node.get("descriptionCategoryId") or "").strip()
        has_attribute_file = str(node.get("attributeFile") or "") == "1"
        if is_leaf:
            if not type_id or type_id == "0" or not description_category_id or not has_attribute_file:
                self.stats["non_selectable_leaf_nodes_pruned"] += 1
                return None
            self.stats["available_leaf_nodes"] += 1
            return {
                "name": str(node.get("name") or "").strip(),
                "name_cn": str(node.get("nameCn") or "").strip(),
                "category_id": node_id,
                "description_category_id": int(description_category_id),
                "type_id": int(type_id),
                "node_path": str(node.get("nodePath") or "").strip(),
                "node_path_id": str(node.get("nodePathId") or "").strip(),
                "children": [],
            }

        children = await self.crawl_children(node_id, depth + 1)
        if not children:
            self.stats["empty_branch_nodes_pruned"] += 1
            return None

        self.stats["available_branch_nodes"] += 1
        return {
            "name": str(node.get("name") or "").strip(),
            "name_cn": str(node.get("nameCn") or "").strip(),
            "category_id": node_id,
            "description_category_id": int(description_category_id) if description_category_id else None,
            "node_path": str(node.get("nodePath") or "").strip(),
            "node_path_id": str(node.get("nodePathId") or "").strip(),
            "children": children,
        }


def load_targets(host: str, port: int) -> list[dict[str, Any]]:
    with urllib.request.urlopen(f"http://{host}:{port}/json", timeout=3) as resp:
        return json.loads(resp.read().decode("utf-8"))


def select_dxm_target(targets: list[dict[str, Any]]) -> dict[str, Any]:
    for target in targets:
        if target.get("type") == "page" and "dianxiaomi.com" in target.get("url", ""):
            return target
    raise RuntimeError("No dianxiaomi.com page found in Chrome remote debugging targets")


def write_llm_tree(nodes: list[dict[str, Any]]) -> str:
    lines: list[str] = []

    def walk(item: dict[str, Any], depth: int) -> None:
        name = item["name"]
        cn = item.get("name_cn") or ""
        text = f"{name} ({cn})" if cn and cn != name else name
        lines.append(f"{'  ' * depth}- {text}")
        for child in item.get("children") or []:
            walk(child, depth + 1)

    for root in nodes:
        walk(root, 0)
    return "\n".join(lines) + "\n"


def write_outputs(roots: list[dict[str, Any]], stats: dict[str, int], elapsed_seconds: float) -> None:
    generated_at = datetime.now().isoformat(timespec="seconds")
    payload = {
        "generated_at": generated_at,
        "source": DXM_CATEGORY_URL,
        "availability_basis": [
            "Dianxiaomi node isDel equals 0",
            "Selectable leaves require isLeaf=1, typeId, descriptionCategoryId, and attributeFile=1",
            "Empty branches are pruned",
        ],
        "stats": stats,
        "roots": roots,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LLM_OUT.write_text(write_llm_tree(roots), encoding="utf-8")
    REPORT_OUT.write_text(
        "\n".join([
            "# Dianxiaomi Ozon Available Category Tree Report",
            "",
            f"- Generated: `{generated_at}`",
            f"- Source API: `{DXM_CATEGORY_URL}`",
            f"- JSON tree: `{JSON_OUT.as_posix()}`",
            f"- LLM tree: `{LLM_OUT.as_posix()}`",
            f"- Elapsed seconds: `{elapsed_seconds:.1f}`",
            "",
            "## Availability Basis",
            "",
            "- Included nodes: `isDel == 0`.",
            "- Included leaves: `isLeaf == 1`, `typeId` is present, `descriptionCategoryId` is present, and `attributeFile == 1`.",
            "- Empty branches are pruned, so every visible branch can reach at least one selectable leaf.",
            "",
            "## Counts",
            "",
            f"- DXM requests: `{stats['requests']}`",
            f"- Source nodes walked: `{stats['source_nodes']}`",
            f"- Available branch nodes: `{stats['available_branch_nodes']}`",
            f"- Available leaf nodes: `{stats['available_leaf_nodes']}`",
            f"- Deleted nodes pruned: `{stats['deleted_nodes_pruned']}`",
            f"- Non-selectable leaves pruned: `{stats['non_selectable_leaf_nodes_pruned']}`",
            f"- Duplicate nodes skipped: `{stats['duplicate_nodes_skipped']}`",
            f"- Empty branches pruned: `{stats['empty_branch_nodes_pruned']}`",
            f"- Request errors: `{stats['request_errors']}`",
            "",
            "## LLM Usage",
            "",
            "Use the LLM tree as a compact path map only. The LLM should output a category path, then program code resolves that path against the JSON tree and uses `description_category_id` plus `type_id` for later Ozon/Dianxiaomi attribute work.",
            "",
        ]) + "\n",
        encoding="utf-8",
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate selectable Ozon category trees from Dianxiaomi's category API.")
    parser.add_argument("--host", default=CDP_HOST)
    parser.add_argument("--port", type=int, default=CDP_PORT)
    parser.add_argument("--delay", type=float, default=0.03)
    args = parser.parse_args()

    targets = load_targets(args.host, args.port)
    target = select_dxm_target(targets)
    start = time.monotonic()
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(target["webSocketDebuggerUrl"]) as ws:
            crawler = DxmCategoryCrawler(ws, delay=args.delay)
            roots = await crawler.crawl_children("0")
            elapsed = time.monotonic() - start
            write_outputs(roots, crawler.stats, elapsed)
            print(json.dumps({
                "json": str(JSON_OUT),
                "llm": str(LLM_OUT),
                "report": str(REPORT_OUT),
                "stats": crawler.stats,
                "elapsed_seconds": round(elapsed, 1),
            }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
