from src.serp.shared.json_store import JsonFileStore


def test_json_store_reads_utf8_bom_files(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"models": []}', encoding="utf-8-sig")

    assert JsonFileStore(str(path)).read() == {"models": []}
