from types import SimpleNamespace

from pydantic_ai.messages import BinaryImage

from ingestion.gemini import MAX_PREVIOUS_OUTPUT_CHARS
from ingestion.gemini import _build_prompt
from ingestion.sources import ImageInput


def test_build_prompt_sends_receipt_as_binary_image(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "receipt_extraction.md").write_text(
        "Extract receipt.", encoding="utf-8"
    )
    ctx = SimpleNamespace(prompts_dir=prompts_dir)
    image = ImageInput(
        image_id="receipt1",
        data=b"fake-jpeg-bytes",
        content_type="image/jpeg",
        extension=".jpg",
    )

    prompt = _build_prompt(
        image,
        ctx,
        previous_json_text=None,
        previous_error=None,
    )

    assert len(prompt) == 2
    assert isinstance(prompt[0], str)
    assert "Image id: receipt1" in prompt[0]
    assert "Previous output to repair" not in prompt[0]
    assert "Previous validation error" not in prompt[0]
    assert "fake-jpeg-bytes" not in prompt[0]
    assert prompt[1] == BinaryImage(data=b"fake-jpeg-bytes", media_type="image/jpeg")


def test_build_prompt_includes_retry_repair_context(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "receipt_extraction.md").write_text(
        "Extract receipt.", encoding="utf-8"
    )
    ctx = SimpleNamespace(prompts_dir=prompts_dir)
    image = ImageInput(
        image_id="receipt1",
        data=b"fake-jpeg-bytes",
        content_type="image/jpeg",
        extension=".jpg",
    )
    previous_json = '{"store_name": "", "items": []}'
    previous_error = "store_name: String should have at least 1 character"

    prompt = _build_prompt(
        image,
        ctx,
        previous_json_text=previous_json,
        previous_error=previous_error,
    )

    assert "Return a complete corrected JSON object" in prompt[0]
    assert "Previous output to repair:" in prompt[0]
    assert previous_json in prompt[0]
    assert f"Previous validation error: {previous_error}" in prompt[0]
    assert prompt[1] == BinaryImage(data=b"fake-jpeg-bytes", media_type="image/jpeg")


def test_build_prompt_truncates_large_previous_output(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "receipt_extraction.md").write_text(
        "Extract receipt.", encoding="utf-8"
    )
    ctx = SimpleNamespace(prompts_dir=prompts_dir)
    image = ImageInput(
        image_id="receipt1",
        data=b"fake-jpeg-bytes",
        content_type="image/jpeg",
        extension=".jpg",
    )
    previous_json = "x" * (MAX_PREVIOUS_OUTPUT_CHARS + 3)

    prompt = _build_prompt(
        image,
        ctx,
        previous_json_text=previous_json,
        previous_error="invalid JSON",
    )

    assert "x" * MAX_PREVIOUS_OUTPUT_CHARS in prompt[0]
    assert "omitted 3 characters" in prompt[0]
