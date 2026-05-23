# 2026-05-23 Ozon Category Match Root Cause

## Symptom

The Ozon listing workbench "auto category match" looked wrong because it behaved like a hard-coded wallet shortcut instead of an operator-like AI decision.

## Root Cause

The existing Ozon category domain already had an AI-driven flow: load the Ozon category tree, ask LLM to choose through candidates, verify the leaf through `/v1/description-category/attribute`, then load attributes. The new workbench draft path bypassed that boundary by calling wallet-specific rules directly.

There was also a concrete bug in `CategoryMatchingService.keyword_score`: it referenced `c` instead of the `candidate` argument.

## Fix

- Workbench `auto_category` now delegates to the Ozon category facade.
- Draft generation now calls AI category matching first, then loads official category attributes, then passes those attributes to the existing autofill service.
- Category attributes endpoint now accepts and forwards `type_id`.
- `keyword_score` now uses its `candidate` argument.

## Evidence

- `python -m pytest tests\listing tests\ozon_category -q` -> 9 passed.
- `python -m py_compile` passed for modified listing and category modules.
- `git diff --check` passed for modified files.
