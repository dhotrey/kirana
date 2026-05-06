from ingestion.sources.disk import DiskImageSource
from ingestion.sources.upload import from_upload


def test_disk_image_source_yields_image_inputs(tmp_path):
    (tmp_path / "b.jpg").write_bytes(b"jpeg-b")
    (tmp_path / "a.jpg").write_bytes(b"jpeg-a")
    (tmp_path / "ignore.txt").write_text("nope", encoding="utf-8")

    images = list(DiskImageSource(tmp_path))

    assert [image.image_id for image in images] == ["a", "b"]
    assert images[0].extension == ".jpg"
    assert images[0].content_type == "image/jpeg"
    assert images[0].data == b"jpeg-a"


def test_from_upload_preserves_display_name_and_content_type():
    image = from_upload("r.jpg", "image/jpeg", b"data")
    assert image.image_id.startswith("upload-")
    assert image.display_name == "r.jpg"
    assert image.content_type == "image/jpeg"
    assert image.extension == ".jpg"
