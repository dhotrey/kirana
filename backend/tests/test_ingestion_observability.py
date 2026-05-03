import time

from ingestion.observability import Stopwatch, bind_image


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
