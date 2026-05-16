import json

from ingestion.canonical_log import CanonicalLog, LatencySeconds, write_canonical_log
from ingestion.stats import RetryCounts, TokenAccumulator, ValidationStats


def canonical() -> CanonicalLog:
    return CanonicalLog(
        image_id="receipt1",
        outcome="success",
        error=None,
        receipt_id=17,
        store_name="Woolworths",
        date="2026-04-28",
        retries=RetryCounts(ocr_validation_retries=2, total_retries=2),
        latency_seconds=LatencySeconds(
            ocr=1,
            summary=2,
            db_insert=3,
            embedding=4,
            vectorize_upsert=5,
            tigris_upload=6,
            total=21,
        ),
        tokens=TokenAccumulator(
            gemini_input=10, gemini_output=20, mistral_input=30, mistral_output=40
        ),
        validation=ValidationStats(subtotal_match=True, price_sum_diff_pct=1.3),
    )


def test_canonical_log_shape_matches_spec():
    data = canonical().model_dump()
    assert set(data) == {
        "image_id",
        "timestamp",
        "outcome",
        "error",
        "receipt_id",
        "store_name",
        "date",
        "retries",
        "latency_seconds",
        "tokens",
        "validation",
        "dry_run",
    }
    assert set(data["retries"]) == {"ocr_validation_retries", "total_retries"}
    assert set(data["tokens"]) == {
        "gemini_input",
        "gemini_output",
        "mistral_input",
        "mistral_output",
    }


def test_write_canonical_log_pretty_json(tmp_path):
    path = write_canonical_log(canonical(), tmp_path)
    assert path.name == "17.json"
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["receipt_id"] == 17
    assert "\n  " in path.read_text(encoding="utf-8")


def test_failure_log_without_receipt_id_validates():
    log = canonical().model_copy(
        update={"outcome": "failure", "error": "boom", "receipt_id": None}
    )
    assert log.error == "boom"
