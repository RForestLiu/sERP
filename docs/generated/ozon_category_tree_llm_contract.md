# Ozon Category Matching LLM Contract

This file replaces the old full JSONL export. The LLM must not receive the full
Ozon category tree. The application owns the full tree. The LLM can express a
global target path, while the program resolves that path against the full tree
and validates the final leaf.

## Ownership

- Program: load and traverse the full Ozon tree.
- Program: resolve LLM-proposed category paths against the full tree.
- Program: keep `description_category_id`, `type_id`, parent path, and retry state.
- Program: validate the final leaf by loading Ozon attributes.
- LLM: propose the most likely Ozon path when enough product context exists.
- LLM: choose one candidate from a bounded packet when path resolution is ambiguous.
- LLM: explain briefly why that candidate is closest.

## Preferred Flow: Path Proposal

Ask the LLM for a path-shaped intent first:

```json
{
  "product": {
    "title": "",
    "source_category": "",
    "description": ""
  },
  "task": "Return the most likely Ozon category path. Do not return ids."
}
```

The LLM response must be:

```json
{
  "path": "Одежда > Спецодежда > Форма силовых структур",
  "reason": "The product is a uniform item for security or official service use.",
  "confidence": 0.78
}
```

The program then resolves `path` against the full local tree:

- Normalize case, spaces, punctuation, and `>` separators.
- Match each path segment against Russian names and cached Chinese translations.
- Prefer exact path matches, then high-confidence fuzzy segment matches.
- If multiple leaves match, ask the LLM to choose from that small sibling set.
- If no path matches, fall back to tree-level decision packets.

This solves a weakness of pure top-down traversal: an early local choice might
block the globally correct leaf. The path proposal lets the LLM state the global
destination first, while the program still owns ids and validation.

## Fallback Flow: Decision Packet

Send one packet per tree level only when path proposal is ambiguous or fails:

```json
{
  "product": {
    "title": "",
    "source_category": "",
    "description": ""
  },
  "current_path": ["Спорт и отдых", "Спортивные чехлы и сумки"],
  "allow_none": false,
  "candidates": [
    {
      "id": "115950834",
      "name": "Мешок спортивный",
      "name_cn": "运动袋",
      "is_leaf": true,
      "description_category_id": 77119630,
      "type_id": 115950834
    }
  ]
}
```

The candidate list is the complete sibling set for the current tree node, not a
global top-N search result. This preserves full-tree coverage while keeping each
LLM call bounded.

## LLM Response

The LLM must return only:

```json
{
  "category_id": "115950834",
  "reason": "The product is a drawstring sports bag, matching the sports bag leaf.",
  "confidence": 0.86
}
```

Rules:

- `category_id` must be one of the candidate ids in the packet.
- Use `__NONE__` only when `allow_none` is true and no current leaf fits.
- Do not invent ids.
- Do not ask for or rely on the full tree.
- Prefer the candidate that keeps the path open toward the correct leaf.

## Traversal Algorithm

1. Ask the LLM for a target Ozon path.
2. Resolve the path against the full local tree.
3. If resolution finds one leaf, validate it through Ozon attributes.
4. If resolution finds several leaves, ask the LLM to choose among those leaves.
5. If path resolution fails, start at root candidates.
6. Ask the LLM to choose one candidate from the current sibling set.
7. If the chosen node has children, move into that node and repeat.
8. If the chosen node is a leaf, call Ozon attributes with
   `description_category_id` and `type_id`.
9. If validation fails, mark that branch as exhausted and backtrack.
10. Stop when a validated leaf is found.

## Why This Shape

- The program can inspect all 7,420 leaf types without token cost.
- The LLM can express a global path without seeing the full tree.
- The LLM sees the full candidate set relevant to one bounded decision.
- The LLM does not lose focus across unrelated top-level categories.
- The final result keeps both Ozon ids required by later attribute loading.
