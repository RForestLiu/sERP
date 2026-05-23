# Ozon Listing Workbench Design

Date: 2026-05-23

## Goal

Build our own Ozon listing/update page so operations can create or update products through Ozon API without relying on Dianxiaomi.

The first acceptance sample is `WALLET-0006-BLACK`: the page must be able to select the product, match the wallet category, select the Black Russian 3x4 image set, generate and validate attributes, submit through Ozon import, and show the official Ozon content score above 75.

## Scope

In scope:

- Product and store selection.
- Automatic Ozon category matching.
- Automatic draft generation.
- Structured LLM generation for important attributes.
- Programmatic validation of LLM output.
- Image-set selection and temporary/public image URL preparation.
- Batch upsert through Ozon import API.
- Ozon task polling, product SKU resolution, and official content rating lookup.
- Display of local validation, Ozon import warnings/errors, and official score.

Out of scope for this iteration:

- Inventory planning.
- Logistics templates.
- Advertising or promotion setup.
- Full multi-category generalization beyond wallet-like products.
- A permanent image hosting product. The page can start with the current temporary image host path, but the interface should allow swapping to a formal host later.

## Core Principle

LLM output is a proposal, not truth.

The page uses a three-layer pipeline:

1. Deterministic program logic for things we can know.
2. Structured LLM calls for important attributes that need language or operator judgment.
3. Program validation and Ozon API feedback before submit success is trusted.

## User Flow

1. Operator opens the Ozon listing page from a product row.
2. Page loads product data, variants, image sets, existing draft, and target Ozon store.
3. Operator clicks "auto generate".
4. System matches Ozon category and loads category attributes.
5. System fills deterministic attributes.
6. System runs separate structured LLM calls for important fields.
7. Program validates generated values and shows evidence, confidence, warnings, and blocking errors.
8. Operator chooses the image set for each variant.
9. System prepares public image URLs.
10. Operator submits or updates.
11. Page polls import status, resolves numeric Ozon SKU, checks official content rating, and shows next recommended fixes.

## Category Matching

Category matching should prefer deterministic paths before LLM:

- Existing saved draft category.
- Product family rules, starting with wallet:
  - `description_category_id=17027904`
  - `type_id=93338`
  - Russian type name: `Кошелек`
- Historical successful mappings.
- Ozon category search API.
- LLM fallback only when the above cannot decide.

The final category must be verified by Ozon attribute/category APIs before use.

## Attribute Generation

Attributes are split into two groups.

Deterministic attributes:

- Brand when known from our trusted source or operator configuration.
- Color from SKU, variant name, image-set name, and product data.
- Dimensions and weight from product data or operator defaults.
- Material, lining, hardware, closure, gender, country, warranty, count, and model fields from rules and dictionary mappings.
- Dictionary attributes must preserve `dictionary_value_id`.

Important LLM-generated attributes:

- Russian title.
- Russian description.
- Selling points and keywords.
- Collection interpretation.
- Rich Content JSON.
- Ambiguous attributes where the product evidence must be explained.

Brand must not be copied from the collected shop name. If the source does not prove the brand, the output must be marked for human confirmation instead of silently filling a brand.

`Коллекция` must be treated as an operator-facing merchandising field, not as a literal scraped text bucket. For wallets, use a conservative value only when it matches a known dictionary value and the product concept supports it.

## Structured LLM Calls

Important attributes should not be generated in one large prompt. Use separate calls:

- `listing_text_ru`: title, description, bullet selling points, keywords.
- `attribute_reasoning`: important dictionary/text attributes with evidence and confidence.
- `rich_content`: Ozon Rich Content JSON proposal.
- `variant_mapping`: SKU names and image-set recommendations.

Every call returns JSON matching a schema. A typical attribute item:

```json
{
  "attribute_id": 85,
  "value": "Bostanten",
  "dictionary_value_id": 971068372,
  "confidence": 0.92,
  "evidence": "Brand appears in product title and product metadata.",
  "needs_human_review": false
}
```

The service rejects malformed JSON, missing required keys, unsupported attribute IDs, unknown dictionary IDs, and values without evidence when the attribute is marked important.

## Validation

Before submission, the program validates:

- Required Ozon fields exist.
- Category/type are valid.
- Dictionary values exist and IDs match their labels.
- Important attributes include evidence and confidence.
- Brand source is trusted.
- Rich Content JSON matches Ozon `raShowcase` template and can be parsed.
- Image URLs are public and fetchable.
- At least five product images exist; eight or video is recommended for higher media score.
- Local score is at least 75 or the operator explicitly overrides.

After submission, the program records:

- Import `task_id`.
- Import item status.
- Ozon warnings/errors.
- `product_id`.
- Numeric Ozon `sku`.
- Official `/v1/product/rating-by-sku` result.

## Page Design

Use the existing Ozon listing page as the main surface, not a new marketing-style page.

Primary sections:

- Product context: title, SKC/SKU, source data, selected store.
- Category panel: matched category, confidence, source, override control.
- Attribute table: grouped by required, important, generated, optional.
- LLM evidence drawer: prompt result, evidence, confidence, validation result.
- Image-set picker: product image sets, selected set per variant, upload/public URL status.
- Submit panel: local validation, Ozon import status, official score, recommended next fixes.

The page should make it obvious which values came from rules, LLM, saved drafts, operator edits, or Ozon feedback.

## Backend Design

Add focused service endpoints around existing listing routes:

- `POST /api/ozon/<store_id>/listing/auto-category`
- `POST /api/ozon/<store_id>/listing/generate-draft`
- `POST /api/ozon/<store_id>/listing/validate`
- `POST /api/ozon/<store_id>/listing/prepare-images`
- `POST /api/ozon/<store_id>/listing/upsert`
- `POST /api/ozon/<store_id>/listing/official-rating`

The first implementation can call the current script-proven Ozon API client logic directly, then refactor once the flow is stable.

## Data Persistence

Save listing drafts with:

- Product SKC and target store.
- Category ID/type ID and match source.
- Attributes with value, dictionary ID, source, confidence, evidence, validation status.
- Image selections and public URLs.
- Rich Content JSON.
- Latest Ozon task/result/score.
- Lifecycle events.

Temporary image URLs should be marked with provider and creation time so the UI can warn when they may expire.

## Error Handling

Blocking errors stop submit:

- Missing category/type.
- Missing required fields.
- Invalid dictionary value.
- Missing public image URLs.
- Invalid Rich Content JSON.
- Ozon import error.

Warnings allow submit but stay visible:

- Low confidence important attribute.
- Brand not verified.
- Temporary image URL provider.
- Fewer than eight images.
- Missing video/video cover.
- Official score below target after submit.

## Testing

Minimum checks:

- Unit test category/rule matching for wallet products.
- Unit test structured LLM schema validation with valid and invalid examples.
- Unit test Rich Content JSON generator.
- Unit test Ozon SKU extraction from `/v3/product/info/list`.
- Route test for draft generation and validation.
- Manual browser QA for `WALLET-0006-BLACK`.
- Real Ozon smoke test only when explicitly authorized.

## Acceptance Criteria

- Operator can generate an Ozon draft for `WALLET-0006-BLACK` from the page.
- The page auto-selects wallet category `17027904 / 93338`.
- Important attributes are generated through structured LLM calls and validated by program code.
- Brand is not silently copied from a scraped shop name.
- Image-set selection can use the Black Russian 3x4 images.
- Submit uses Ozon batch import/upsert.
- The page resolves numeric Ozon SKU and displays official Ozon score.
- The final official score is at least 75 for `WALLET-0006-BLACK`.
