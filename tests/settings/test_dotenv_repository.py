import os

from src.serp.settings.infrastructure.json_repositories import DotEnvRepository


def test_dotenv_write_updates_current_process_environment(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("API_KEY=old\n", encoding="utf-8")
    monkeypatch.setenv("API_KEY", "old")

    DotEnvRepository(str(path)).write({"API_KEY": "new"})

    assert os.environ["API_KEY"] == "new"
    assert path.read_text(encoding="utf-8") == "API_KEY=new\n"
