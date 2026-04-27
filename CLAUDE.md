# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## 5. Bug Reporting Format

**Every bug report must follow this 3-section structure. No fluff, no repetition.**

### 问题分析
- **根因**：一句话说明根本原因，指向具体代码位置
- **关键代码路径**：列出涉及的文件 + 行号，说明每个节点做了什么
- **为什么不只改 X**：如果存在看似更简单的方案，解释为什么它不可靠

### 解决方案
- **策略**：一句话概括思路
- **具体改动**：每个文件 + 行号 + 改什么
- **需要/不需要改动的部分**：明确边界，避免 scope creep

### 验收标准
- 表格形式：`| # | 标准 | 验证方式 |`
- 每条标准必须可验证（观察什么行为、调用什么接口、检查什么返回值）
- **从业务/用户视角出发**，不以代码实现为验收标准：
  - ✅ 前端显示完整的品类路径 → ✅ 匹配结果可直接用于上传商品
  - ❌ 日志出现 `[品类匹配] 第 0 层` → ❌ `py_compile` 通过
- 覆盖：正常路径 + 边界情况 + 回归保护

**反例**：只描述现象然后直接写代码。**正例**：本文件的 3 段式结构。

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## 6. Project Architecture (g:/sERP)

**Flask single-file backend** (`app.py`, ~2800 lines). All routes, API integrations, and business logic in one file.

### Key modules (by section in app.py)
| Lines | Module | Purpose |
|---|---|---|
| ~370-870 | Product management | `/api/products` CRUD, store status |
| ~870-1100 | SKC/SKU parsing | `_parse_sku()` Excel row → JSON |
| ~1100-1310 | AI recognition | DeepSeek vision (`_analyze_product_image`) |
| ~1310-1365 | Listing drafts | `/api/listings/<skc>/<store_id>` CRUD |
| ~1370-1424 | Ozon API client | `_call_ozon_api(store_id, endpoint, payload)` |
| ~1426-1715 | Category tree cache | `_get_cached_category_tree`, translation |
| ~1718-1980 | Category endpoints | `/api/ozon/<store_id>/category-tree`, `translate-categories`, `refresh-categories` |
| ~2043-2383 | Match-category | Stack-based DFS backtracking with LLM + keyword verification |
| ~2387-2590 | Category attributes | `/api/ozon/<store_id>/category-attributes` with `name_cn` translation |
| ~2593-2664 | Auto-fill | DeepSeek maps product data → Ozon attributes |
| ~2748-2848 | Product create | `/api/ozon/<store_id>/product/create` → Ozon `/v3/product/import` |

### Caches (in `data/ozon_cache/`)
- `{store_id}_category_tree.json` — full category tree with translations (`_name_cn`)
- `{store_id}_translations.json` — `{category_id: chinese_name}`
- `{store_id}_attr_translations.json` — `{russian_attr_name: chinese_name}`
- `{store_id}_excluded_categories.json` — category IDs with no attributes (banned)

### Frontend
- `templates/ozon_listing.html` — Ozon product listing page, 店小秘-style UI. Card-based layout with anchor nav, form-card sections, category selector modal. All business logic in vanilla JS.

### API key config (.env)
- `DEEPSEEK_API_KEY`, `DEEPSEEK_API_URL` — for category translation + auto-fill
- Ozon credentials stored per-store in `data/stores.json` (`client_id`, `api_key`)

### Key Ozon API calls
| Endpoint | Use |
|---|---|
| `/v1/description-category/tree` | Get category tree |
| `/v1/description-category/attribute` | Get attributes (needs `description_category_id` + `type_id`) |
| `/v1/description-category/attribute/values` | Get dictionary attribute values |
| `/v3/product/import` | Create/update product |