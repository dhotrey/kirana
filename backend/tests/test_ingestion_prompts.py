import pytest

from ingestion.prompts import load_prompt


def test_load_prompt_reads_markdown_and_caches(tmp_path):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "receipt_summary.md").write_text("hello", encoding="utf-8")

    first = load_prompt(prompts, "receipt_summary")
    second = load_prompt(prompts, "receipt_summary")

    assert first == "hello"
    assert id(first) == id(second)


def test_load_prompt_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_prompt(tmp_path, "missing")
