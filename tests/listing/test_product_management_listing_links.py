from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_template(name: str) -> str:
    return (ROOT / "templates" / name).read_text(encoding="utf-8")


def read_source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_legacy_product_management_listing_entries_are_hidden():
    template = read_template("index.html")

    assert 'href="/listing-workbench"' not in template
    assert 'href="/product-maintenance"' not in template
    assert "store-listing-btn" not in template
    assert "data-action=\"listing\"" not in template
    assert "window.open(`/ozon-listing?skc=${skc}&store_id=${storeId}`" not in template
    assert "window.open(`/ozon-product/add?skc=${encodeURIComponent(skc)}&store_id=${encodeURIComponent(storeId)}`" not in template


def test_index_sidebar_navigation_order_and_bottom_items():
    template = read_template("index.html")

    collect_pos = template.index('data-module="collect-product"')
    product_pos = template.index('data-module="product-manage"')
    image_pos = template.index('data-module="image-batch"')
    spacer_pos = template.index('class="nav-spacer"')
    knowledge_pos = template.index('href="/knowledge-base"')
    settings_pos = template.index('data-module="settings"')

    assert collect_pos < product_pos < image_pos
    assert image_pos < spacer_pos < knowledge_pos < settings_pos
    assert "<span class=\"nav-label\">采集</span>" in template
    assert "<span class=\"nav-label\">图片处理</span>" in template


def test_product_image_management_supports_box_toggle_and_copy_actions():
    template = read_template("index.html")
    product_routes = read_source("src/serp/product/interfaces/routes.py")
    product_commands = read_source("src/serp/product/application/commands.py")

    assert 'id="img-mgmt-copy-url"' in template
    assert 'id="img-mgmt-copy-files"' in template
    assert "function bindImageMgmtBoxSelect" in template
    assert "baseSelection = new Set(selectedImages)" in template
    assert "if (selectedImages.has(idx)) selectedImages.delete(idx);" in template
    assert "else selectedImages.add(idx);" in template
    assert "/images/copy_to_clipboard" in template
    assert "navigator.clipboard.writeText(urls.join(\"\\n\"))" in template
    assert '"/products/<skc>/images/copy_to_clipboard"' in product_routes
    assert "def copy_images_to_clipboard" in product_commands
    assert "CopyToClipboardService.copy_files(paths)" in product_commands


def test_clipboard_copy_uses_ctypes_without_pywin32_dependency():
    service_source = read_source("src/serp/imagetask/domain/services.py")

    assert "import win32clipboard" not in service_source
    assert "CF_HDROP = 15" in service_source
    assert "user32.SetClipboardData(CF_HDROP, hglobal)" in service_source


def test_product_maintenance_listing_entries_are_hidden():
    template = read_template("product_maintenance.html")

    assert 'href="/ozon-product/add"' not in template
    assert 'href="/ozon-listing"' not in template
    assert "store-listing-link" not in template
    assert "listingUrl(store.id)" not in template


def test_latest_ozon_editor_preselects_product_from_query_skc():
    template = read_template("ozon_product_editor.html")

    assert 'skc: query.get("skc") || ""' in template
    assert "selectProduct(pageState.skc);" in template
