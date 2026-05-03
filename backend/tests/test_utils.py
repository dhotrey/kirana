from utils.config import load_config
import pytest


@pytest.fixture
def config():
    return load_config("config.toml")

def test_load_config(config):
    assert config is not None
    assert config.cloudflare is not None
    assert config.kirana is not None
    assert config.tigris is not None
    assert config.log_level is not None
    assert config.kb is not None
    assert config.ingestion is not None
    assert config.ingestion.gemini_rpm == 5
    assert config.ingestion.embedding_dim == 1536
