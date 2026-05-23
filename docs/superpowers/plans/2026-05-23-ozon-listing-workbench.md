# Ozon Listing Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable Ozon listing/update workbench flow for wallet products, centered on automatic category matching, structured important-attribute generation, program validation, image URL preparation, upsert, and official score lookup.

**Architecture:** Add small pure helper functions for Ozon draft generation and validation, then expose them through focused listing endpoints. Reuse the existing `ozon_listing.html` page and existing `/api/ozon/<store_id>/product/create` import path instead of creating a second listing workflow.

**Tech Stack:** Flask, Python service classes, existing Ozon Seller API client, existing DeepSeek-compatible chat API client, vanilla HTML/CSS/JavaScript.

---

### Task 1: Pure Ozon Draft Helpers

**Files:**
- Create: `src/serp/listing/domain/ozon_workbench.py`
- Test: `tests/listing/test_ozon_workbench.py`

- [ ] **Step 1: Write tests for wallet category, Rich Content, SKU extraction, and validation**

Create `tests/listing/test_ozon_workbench.py` with tests that:

```python
from src.serp.listing.domain.ozon_workbench import (
    WALLET_CATEGORY_ID,
    WALLET_TYPE_ID,
    build_wallet_rich_content,
    collect_ozon_skus,
    match_wallet_category,
    validate_workbench_payload,
)


def test_match_wallet_category_for_wallet_title():
    result = match_wallet_category({
        "skc": "WALLET-0006",
        "title": "Bostanten wristlet wallet black",
        "category": "wallets",
    })

    assert result["matched"] is True
    assert result["description_category_id"] == WALLET_CATEGORY_ID
    assert result["type_id"] == WALLET_TYPE_ID
    assert result["source"] == "wallet_rule"


def test_build_wallet_rich_content_uses_ozon_template():
    rich = build_wallet_rich_content([
        "https://example.com/1.png",
        "https://example.com/2.png",
        "https://example.com/3.png",
    ])

    assert rich["version"] == 0.3
    assert rich["content"][0]["widgetName"] == "raShowcase"
    assert rich["content"][0]["type"] == "billboard"
    assert len(rich["content"][0]["blocks"]) == 3


def test_collect_ozon_skus_from_info_list_shape():
    result = {
        "items": [{
            "sku": 4408894048,
            "sources": [{"sku": 4408894048}],
        }]
    }

    assert collect_ozon_skus(result) == [4408894048]


def test_validate_blocks_untrusted_brand():
    payload = {
        "category_id": WALLET_CATEGORY_ID,
        "type_id": WALLET_TYPE_ID,
        "name": "Кошелек Bostanten WALLET-0006, черный",
        "description": "x" * 500,
        "price": "99.00",
        "offer_id": "WALLET-0006-BLACK",
        "images": [{"url": "https://example.com/1.png"}] * 5,
        "attributes": [{
            "attribute_id": 85,
            "value": "Collected Shop",
            "dictionary_value_id": 123,
            "source": "scraped_shop",
        }],
        "skus": [{"name": "WALLET-0006-BLACK", "price": "99.00", "stock": "100"}],
    }

    report = validate_workbench_payload(payload)

    assert report["can_submit"] is False
    assert any("品牌" in issue for issue in report["issues"])
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `python -m pytest tests/listing/test_ozon_workbench.py -q`

Expected: import failure because `ozon_workbench.py` does not exist yet.

- [ ] **Step 3: Implement pure helpers**

Create `src/serp/listing/domain/ozon_workbench.py` with:

- `WALLET_CATEGORY_ID = 17027904`
- `WALLET_TYPE_ID = 93338`
- `match_wallet_category(product)`
- `build_wallet_rich_content(image_urls)`
- `collect_ozon_skus(value)`
- `validate_workbench_payload(payload)`

Implementation rules:

- Wallet category matching is rule-based for `wallet`, `кошелек`, `кошелёк`, `портмоне`, and SKC prefix `WALLET-`.
- Rich Content returns the working Ozon `{"content":[{"widgetName":"raShowcase","type":"billboard","blocks":[...]}],"version":0.3}` structure.
- SKU extraction recursively scans `sku`, `fbo_sku`, `fbs_sku`, `items`, `result.items`, and `sources`.
- Validation rejects untrusted brand sources, missing category/type, missing required core fields, invalid Rich Content, fewer than five public image URLs, and missing SKU rows.

- [ ] **Step 4: Run tests and confirm they pass**

Run: `python -m pytest tests/listing/test_ozon_workbench.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/serp/listing/domain/ozon_workbench.py tests/listing/test_ozon_workbench.py
git commit -m "feat: add ozon workbench helpers"
```

### Task 2: Listing Service Endpoints

**Files:**
- Modify: `src/serp/listing/facade.py`
- Modify: `src/serp/listing/application/commands.py`
- Modify: `src/serp/listing/interfaces/routes.py`
- Test: `tests/listing/test_ozon_workbench_service.py`

- [ ] **Step 1: Write service tests with fakes**

Create `tests/listing/test_ozon_workbench_service.py` using fake dependencies to instantiate `ListingApplicationService`.

Test:

- `generate_workbench_draft()` returns wallet category, important attributes, Rich Content, and validation.
- `official_rating()` resolves numeric SKU from `/v3/product/info/list` before calling `/v1/product/rating-by-sku`.

- [ ] **Step 2: Run tests and confirm they fail**

Run: `python -m pytest tests/listing/test_ozon_workbench_service.py -q`

Expected: methods do not exist.

- [ ] **Step 3: Add facade contract**

Add methods:

- `auto_category(store_id, data)`
- `generate_workbench_draft(store_id, data)`
- `validate_workbench_payload(store_id, data)`
- `prepare_images(store_id, data)`
- `upsert_workbench(store_id, data)`
- `official_rating(store_id, data)`

- [ ] **Step 4: Implement service methods**

Implementation uses:

- Product lookup through `_find_product_by_skc`.
- Category rule through `match_wallet_category`.
- Existing `_format_ozon_attributes` and `_build_ozon_items`.
- Existing Ozon client for import and rating.
- `validate_workbench_payload` before upsert.
- Temporary public image URL preparation initially only validates existing HTTP URLs and local `/product_images/...` paths; actual third-party upload remains explicit and can be added behind the same endpoint.

- [ ] **Step 5: Add routes**

Add:

- `POST /api/ozon/<store_id>/listing/auto-category`
- `POST /api/ozon/<store_id>/listing/generate-draft`
- `POST /api/ozon/<store_id>/listing/validate`
- `POST /api/ozon/<store_id>/listing/prepare-images`
- `POST /api/ozon/<store_id>/listing/upsert`
- `POST /api/ozon/<store_id>/listing/official-rating`

- [ ] **Step 6: Run tests**

Run:

```bash
python -m pytest tests/listing/test_ozon_workbench.py tests/listing/test_ozon_workbench_service.py -q
python -m py_compile src/serp/listing/application/commands.py src/serp/listing/interfaces/routes.py src/serp/listing/facade.py
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/serp/listing/facade.py src/serp/listing/application/commands.py src/serp/listing/interfaces/routes.py tests/listing/test_ozon_workbench_service.py
git commit -m "feat: add ozon workbench endpoints"
```

### Task 3: Ozon Listing Page Wiring

**Files:**
- Modify: `templates/ozon_listing.html`

- [ ] **Step 1: Add UI controls and state**

Add a compact workbench toolbar to the existing Ozon listing page:

- "自动生成草稿"
- "验证"
- "准备图片 URL"
- "官方评分"

Add display areas:

- Category source/confidence.
- Important attribute evidence and validation messages.
- Temporary image URL warnings.
- Official score.

- [ ] **Step 2: Wire frontend API calls**

Add JavaScript functions:

- `autoGenerateWorkbenchDraft()`
- `validateWorkbenchDraft()`
- `prepareWorkbenchImages()`
- `upsertWorkbenchDraft()`
- `loadOfficialRating()`

These functions call the new endpoints and update `listingDraft`.

- [ ] **Step 3: Preserve existing submit flow**

Keep the old submit button available, but make the primary path call `/listing/upsert` when the generated draft has a workbench validation report.

- [ ] **Step 4: Verify page renders**

Run the Flask app with the project command used locally, open `/ozon-listing?skc=WALLET-0006&store_id=ozon_anling`, and verify:

- The page loads.
- Auto-generate button appears.
- Existing SKU/image sections still render.
- No console syntax errors.

- [ ] **Step 5: Commit**

Run:

```bash
git add templates/ozon_listing.html
git commit -m "feat: wire ozon listing workbench page"
```

### Task 4: Documentation And Smoke Check

**Files:**
- Modify: `docs/Ozon_WALLET-0006_Black_上架复盘.md`

- [ ] **Step 1: Update documentation**

Add a section describing how to use the new page flow and which endpoint owns each step.

- [ ] **Step 2: Run verification**

Run:

```bash
python -m pytest tests/listing -q
python -m py_compile src/serp/listing/domain/ozon_workbench.py src/serp/listing/application/commands.py src/serp/listing/interfaces/routes.py
```

Expected: pass.

- [ ] **Step 3: Commit**

Run:

```bash
git add docs/Ozon_WALLET-0006_Black_上架复盘.md
git commit -m "docs: document ozon workbench flow"
```
