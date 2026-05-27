from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP_FILE = ROOT / "app.py"
MANIFEST_FILE = ROOT / "extensions" / "amazon_collector" / "manifest.json"


def test_flask_startup_logs_extension_version():
    source = APP_FILE.read_text(encoding="utf-8")
    manifest = MANIFEST_FILE.read_text(encoding="utf-8")

    assert "def _read_extension_version" in source
    assert "extensions/amazon_collector/manifest.json" in source
    assert "extension=%s" in source
    assert '"version": "3.2.44"' in manifest
