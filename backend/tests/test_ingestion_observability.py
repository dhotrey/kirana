import time
from pathlib import Path

from ingestion.observability import Stopwatch, _read_logfire_token, bind_image


def test_stopwatch_populates_timings():
    timings: dict[str, float] = {}
    with Stopwatch("ocr", timings):
        time.sleep(0.001)
    assert timings["ocr"] > 0

    with Stopwatch("ocr", timings):
        pass
    assert "ocr" in timings


def test_bind_image_sets_logger_extra():
    bound = bind_image("receipt1")
    assert bound._options[-1]["image_id"] == "receipt1"


def test_configure_logfire_skips_when_kirana_disable(monkeypatch):
    from ingestion.observability import configure_logfire

    monkeypatch.setenv("KIRANA_DISABLE_LOGFIRE", "1")
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    configure_logfire()


def test_read_logfire_token_prefers_default_toml_over_env(monkeypatch, tmp_path):
    lf = tmp_path / ".logfire"
    lf.mkdir()
    (lf / "default.toml").write_text(
        '[tokens.cli]\ntoken = "from-cli"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("LOGFIRE_TOKEN", "stale-from-env")
    monkeypatch.delenv("LOGFIRE_PREFER_ENV", raising=False)
    assert _read_logfire_token() == "from-cli"


def test_read_logfire_token_prefer_env_restores_env_first(monkeypatch, tmp_path):
    lf = tmp_path / ".logfire"
    lf.mkdir()
    (lf / "default.toml").write_text(
        '[tokens.cli]\ntoken = "from-file"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("LOGFIRE_TOKEN", "from-env")
    monkeypatch.setenv("LOGFIRE_PREFER_ENV", "1")
    assert _read_logfire_token() == "from-env"
