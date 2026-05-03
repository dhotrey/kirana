from __future__ import annotations

import mimetypes
from collections.abc import Iterator
from pathlib import Path

from ingestion.sources import ImageInput


SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


class DiskImageSource:
    def __init__(self, directory: Path, *, sort: bool = True) -> None:
        self.directory = directory
        self.sort = sort

    def __iter__(self) -> Iterator[ImageInput]:
        paths = [
            path
            for path in self.directory.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
        ]
        if self.sort:
            paths = sorted(paths, key=lambda path: path.name)
        for path in paths:
            yield from_disk_path(path)


def from_disk_path(path: Path) -> ImageInput:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return ImageInput(
        image_id=path.stem,
        data=path.read_bytes(),
        content_type=content_type,
        extension=path.suffix.lower(),
        display_name=path.name,
    )
