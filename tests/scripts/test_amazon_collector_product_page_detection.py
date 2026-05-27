from pathlib import Path


CONTENT_FILE = Path(__file__).resolve().parents[2] / "extensions" / "amazon_collector" / "content.js"


def test_amazon_mobile_product_path_injects_collector_ui():
    source = CONTENT_FILE.read_text(encoding="utf-8")

    assert r"/\/gp\/aw\/d\//i.test(href)" in source
    assert r"/\/dp\//i.test(href)" in source
    assert r"/\/gp\/product\//i.test(href)" in source
