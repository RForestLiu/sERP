# Ozon Quality Score API Research

## Summary

**No public Ozon product card quality score API found.** Ozon does not expose a per-product
content quality rating via their Seller API. The `/v1/rating/summary` endpoint returns
**seller-level** aggregate metrics, not individual product scores.

## Seller Rating API (exists)

### Endpoint: `POST /v1/rating/summary`

Returns seller account rating across multiple dimensions:

| Group | Metrics | Example Value |
|-------|---------|---------------|
| Price Index | % products in green/yellow/red zone | green=41%, yellow=5%, red=54% |
| Seller Rating | Average product review score | 4.8 / 5 |
| Order Delivery | Late shipment %, progressive scale rating | 3.13% late |
| Complaints | FBO/FBS/rFBS complaint rates | 0% |

**Key fields per metric:**
- `name`: Human-readable metric name (Russian)
- `current_value` / `past_value`: Numeric values
- `status`: "OK", "UNKNOWN_STATUS", etc.
- `rating`: Internal metric key (e.g., `rating_price_green`)
- `change.direction`: DIRECTION_FALL, DIRECTION_RISE, DIRECTION_NONE
- `change.meaning`: MEANING_BAD, MEANING_GOOD, MEANING_NONE

**Additional seller-level fields:**
- `penalty_score_exceeded`: Whether penalty threshold crossed
- `premium` / `premium_plus`: Seller tier status
- `localization_index`: Local production percentage

## Product Quality Score API (NOT found)

The following endpoints were tested and returned 404:

| Endpoint | Result |
|----------|--------|
| `POST /v1/product/info/rating` | 404 Not Found |
| `POST /v1/product/rating` | 404 Not Found |
| `POST /v1/seller/rating` | 404 Not Found |

## Quality Score Alternatives

### sERP Internal Quality Gate (current implementation)

The sERP system uses a custom 80-point scoring model at
`POST /api/ozon/<store_id>/listing/simulate`:

| Module | Points | Checks |
|--------|--------|--------|
| Category | 15 | description_category_id, type_id |
| Basic Info | 15 | Title, description, offer_id, price |
| Attribute Completeness | 25 | Filled attributes, material, color, brand, Rich Content |
| Media | 20 | Valid product images (no SVG/thumbnails/icons) |
| Variants & Stock | 15 | SKU, price, stock, uniqueness |
| Price & Logistics | 10 | Price, old_price, weight, dimensions, barcode |

**This is NOT Ozon's official score** -- it is a pre-submission quality gate designed
to prevent submitting incomplete products.

### Ozon Import Error Feedback

After `/v3/product/import`, the `/v1/product/import/info` response provides
per-item errors and warnings that serve as de facto quality feedback:

- **Error level**: Blocks import (e.g., invalid brand, missing dimensions, bad Rich Content JSON)
- **Warning level**: Does not block import but degrades card quality (e.g., non-dictionary values)

By resolving errors with `offer_id` upsert semantics, product quality can be iteratively
improved through API-only workflow.

### Ozon Seller Backend (manual)

The only way to see Ozon's official product card quality score is through the
Ozon Seller backend web interface. The score appears as:
- Product card completeness percentage
- Content quality indicators
- Category-specific attribute completeness

This is **not exposed via API**.

## Recommendations

1. **sERP 80-point gate** should be renamed to "sERP Submission Readiness Score" to avoid
   confusion with Ozon's official quality score.

2. **Import error analysis**: Use `/v1/product/import/info` errors as proxy quality signals.
   An import with 0 errors and 0 warnings = likely high Ozon quality score.

3. **Dictionary compliance**: Track how many dictionary-valued attributes use `dictionary_value_id`
   vs plain strings -- this correlates with Ozon card quality.

4. **Future**: If Ozon ever exposes product card scoring via API, integrate it as an additional
   `ozon_official_score` field in the listing lifecycle.
