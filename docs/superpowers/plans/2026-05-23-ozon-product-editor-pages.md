# Ozon Product Editor Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first real create/update Ozon product page using the Dianxiaomi-style editor layout with a fixed AI assistant rail.

**Architecture:** Add one shared Flask template for both create and update states. The left 2/3 follows Dianxiaomi's Ozon product form structure; the right 1/3 is a fixed AI rail that uses the existing workbench endpoints.

**Tech Stack:** Flask routes, Jinja template, vanilla HTML/CSS/JavaScript, existing Ozon listing workbench APIs.

---

### Task 1: Shared Create/Update Page

**Files:**
- Create: `templates/ozon_product_editor.html`
- Modify: `src/serp/listing/interfaces/routes.py`

- [ ] Add `/ozon-product/add` and `/ozon-product/edit` routes that render the same template with `mode="create"` or `mode="update"`.
- [ ] Build a Dianxiaomi-style page shell: blue navigation, breadcrumb, top actions, left form sections, right fixed AI rail, bottom action bar.
- [ ] Represent create state as empty store/category/title fields and no Ozon attribute panel until category exists.
- [ ] Represent update state as selected store/category plus an Ozon platform attributes panel.

### Task 2: Operator Controls

**Files:**
- Modify: `templates/ozon_product_editor.html`

- [ ] Add controls for AI category selection, official attributes loading, AI attribute filling, image matching, validation, upsert, and official rating.
- [ ] Keep low-level Ozon fields hidden behind operator controls: video and video cover are one media module; PDF/files are an advanced folded module.
- [ ] Add SKU image rows with drag-drop placeholders and variant rows for add/edit/delete.

### Task 3: Verification

**Files:**
- Modify: `templates/product_maintenance.html`

- [ ] Point the workbench navigation to `/ozon-product/add`.
- [ ] Run `python -m py_compile src/serp/listing/interfaces/routes.py`.
- [ ] Open `/ozon-product/add` and `/ozon-product/edit?skc=WALLET-0006&store_id=ozon_anling` in the browser and check layout.
