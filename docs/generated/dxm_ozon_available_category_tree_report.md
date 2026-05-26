# Dianxiaomi Ozon Available Category Tree Report

- Generated: `2026-05-26T11:23:45`
- Source API: `https://www.dianxiaomi.com/api/ozonCategoryNew/list.json`
- JSON tree: `docs/generated/dxm_ozon_available_category_tree.json`
- LLM tree: `docs/generated/dxm_ozon_available_category_tree_llm.txt`
- Elapsed seconds: `72.7`

## Availability Basis

- Included nodes: `isDel == 0`.
- Included leaves: `isLeaf == 1`, `typeId` is present, `descriptionCategoryId` is present, and `attributeFile == 1`.
- Empty branches are pruned, so every visible branch can reach at least one selectable leaf.

## Counts

- DXM requests: `648`
- Source nodes walked: `9873`
- Available branch nodes: `637`
- Available leaf nodes: `8578`
- Deleted nodes pruned: `0`
- Non-selectable leaves pruned: `648`
- Duplicate nodes skipped: `0`
- Empty branches pruned: `10`
- Request errors: `0`

## LLM Usage

Use the LLM tree as a compact path map only. It intentionally keeps only Ozon/Dianxiaomi Russian category names to reduce tokens and avoid bilingual matching drift. The LLM should output a category path, then program code resolves that path against the JSON tree and uses `description_category_id` plus `type_id` for later Ozon/Dianxiaomi attribute work.

