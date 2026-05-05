from types import SimpleNamespace

from pydantic_ai.messages import BinaryImage

from ingestion.gemini import _build_prompt
from ingestion.gemini import _google_upstream_api_key_invalid
from ingestion.sources import ImageInput


def test_google_upstream_api_key_invalid_detects_gateway_body():
    body = [
        {
            "error": {
                "code": 400,
                "message": "API key not valid. Please pass a valid API key.",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "API_KEY_INVALID",
                    }
                ],
            }
        }
    ]
    assert _google_upstream_api_key_invalid(body) is True


def test_google_upstream_api_key_invalid_empty_body():
    assert _google_upstream_api_key_invalid(None) is False


def test_build_prompt_sends_receipt_as_binary_image(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "receipt_extraction.md").write_text("Extract receipt.", encoding="utf-8")
    ctx = SimpleNamespace(prompts_dir=prompts_dir)
    image = ImageInput(
        image_id="receipt1",
        data=b"fake-jpeg-bytes",
        content_type="image/jpeg",
        extension=".jpg",
    )

    prompt = _build_prompt(image, ctx, previous_error=None)

    assert len(prompt) == 2
    assert isinstance(prompt[0], str)
    assert "Image id: receipt1" in prompt[0]
    assert "fake-jpeg-bytes" not in prompt[0]
    assert prompt[1] == BinaryImage(data=b"fake-jpeg-bytes", media_type="image/jpeg")
