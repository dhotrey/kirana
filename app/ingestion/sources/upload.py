from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from ingestion.sources import ImageInput


def from_upload(filename: str, content_type: str, data: bytes) -> ImageInput:
    suffix = Path(filename).suffix.lower() or ".bin"
    return ImageInput(
        image_id=f"upload-{uuid4().hex[:8]}",
        data=data,
        content_type=content_type,
        extension=suffix,
        display_name=filename,
    )
