def test_configure_logfire_skips_when_kirana_disable(monkeypatch):
    from ingestion.observability import configure_logfire

    monkeypatch.setenv("KIRANA_DISABLE_LOGFIRE", "1")
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    configure_logfire()
