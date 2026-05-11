from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from pydantic import BaseModel, Field


class ImageInput(BaseModel):
    image_id: str = Field(min_length=1)
    data: bytes
    content_type: str = Field(min_length=1)
    extension: str = Field(pattern=r"^\.[A-Za-z0-9]+$")
    display_name: str | None = None


class ImageSource(Protocol):
    def __iter__(self) -> Iterator[ImageInput]: ...
