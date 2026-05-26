# Ozon Available Category Tree Report

- Store: `ozon_anling`
- Generated: `2026-05-26T10:53:30`
- Source tree: `data/ozon_cache/ozon_anling_category_tree.json`
- JSON tree: `docs/generated/ozon_available_category_tree.json`
- LLM tree: `docs/generated/ozon_available_category_tree_llm.txt`

## Availability Basis

- Included nodes: `disabled != true`.
- Included leaves: leaf has `type_id` and its `description_category_id` is not in local excluded cache.
- Attribute API full validation: `not run` for this artifact.

## Counts

- Source nodes walked: `7988`
- Source leaf nodes: `7420`
- Available category nodes: `567`
- Available leaf nodes: `7383`
- Disabled nodes pruned: `0`
- Known-excluded leaves pruned: `37`
- Empty branch nodes pruned: `1`
- Local excluded description_category_id values: `[17027904]`

## Verification

This validates the first half of the design: the LLM-facing tree can be generated without disabled or locally excluded nodes. The second half, full leaf validation through `/v1/description-category/attribute`, should run as a separate preflight job because it may require thousands of API calls and rate-limit handling.

Local checks performed by the generator:

- Every leaf in the JSON tree has `type_id`.
- No leaf in the JSON tree uses a locally excluded `description_category_id`.
- Empty branches are pruned, so every visible branch can reach at least one selectable leaf.
- The LLM tree is generated from UTF-8 Ozon API names, not screenshots or OCR text.

