import os
import hashlib
from collections import defaultdict
from csv import reader
from utils.config import load_config
from utils.types import Config
from utils.logger import log
from decimal import Decimal, ROUND_HALF_UP
from cloudflare import Cloudflare
from dotenv import load_dotenv
from pydantic import SecretStr

load_dotenv()


SPLITWISE_COST_COL_IDX = 3
SPLITWISE_ME_COL_IDX = 5
SPLITWISE_ROOMMATE1_COL_IDX = 6
SPLITWISE_ROOMMATE2_COL_IDX = 7
SPLITWISE_MONEY_COL_IDXS = (
    SPLITWISE_COST_COL_IDX,
    SPLITWISE_ME_COL_IDX,
    SPLITWISE_ROOMMATE1_COL_IDX,
    SPLITWISE_ROOMMATE2_COL_IDX,
)
SPLITWISE_INSERT_COLUMNS = (
    "source_row_hash",
    "date",
    "description",
    "category",
    "cost_cents",
    "currency",
    "me_cents",
    "roommate1_cents",
    "roommate2_cents",
)
SPLITWISE_SOURCE_COLUMNS = len(SPLITWISE_INSERT_COLUMNS) - 1
D1_MAX_SQL_VARIABLES = 100
SPLITWISE_INSERT_BATCH_SIZE = D1_MAX_SQL_VARIABLES // len(SPLITWISE_INSERT_COLUMNS)


def read_splitwise_csv(file_path: str) -> list[list[str]]:
    with open(file_path, newline="", encoding="utf-8", mode="r") as f:
        r = reader(f)
        return [row for row in r]


def money_to_cents(value: str) -> int:
    amount = Decimal(value.strip())
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def splitwise_source_row_hash(row: tuple[str, ...], occurrence: int) -> str:
    row_key = "\x1f".join((*row, str(occurrence)))
    return hashlib.sha256(row_key.encode("utf-8")).hexdigest()


def clean_splitwise_data(data: list[list[str]]) -> list[list[str | int]]:
    cleaned_data = []
    occurrences: defaultdict[tuple[str, ...], int] = defaultdict(int)
    for row in data:
        if not row or not any(cell.strip() for cell in row):
            continue
        if len(row) <= SPLITWISE_COST_COL_IDX:
            raise ValueError(f"Splitwise row has no cost column: {row}")
        if not row[SPLITWISE_COST_COL_IDX].strip():
            log.debug(f"Skipping Splitwise row without a cost: {row}")
            continue
        if len(row) < SPLITWISE_SOURCE_COLUMNS:
            raise ValueError(
                f"Splitwise row has {len(row)} columns; "
                f"expected {SPLITWISE_SOURCE_COLUMNS}: {row}"
            )
        extra_values = [cell for cell in row[SPLITWISE_SOURCE_COLUMNS:] if cell.strip()]
        if extra_values:
            raise ValueError(
                f"Splitwise row has unexpected extra columns after "
                f"{SPLITWISE_SOURCE_COLUMNS} expected columns: {row}"
            )

        source_row = tuple(cell.strip() for cell in row[:SPLITWISE_SOURCE_COLUMNS])
        occurrences[source_row] += 1
        cleaned_row: list[str | int] = [
            splitwise_source_row_hash(source_row, occurrences[source_row]),
            *source_row,
        ]
        for col_idx in SPLITWISE_MONEY_COL_IDXS:
            cleaned_row[col_idx + 1] = money_to_cents(source_row[col_idx])

        cleaned_data.append(cleaned_row)

    return cleaned_data


def prepare_insert(data: list[list[str | int]]) -> tuple[str, list[str]]:
    if not data:
        raise ValueError("Cannot prepare a Splitwise insert with no rows")

    row_placeholder = "(" + ", ".join(["?"] * len(SPLITWISE_INSERT_COLUMNS)) + ")"
    placeholders = ", ".join([row_placeholder] * len(data))
    sql = f"""
INSERT OR IGNORE INTO splits ({", ".join(SPLITWISE_INSERT_COLUMNS)})
VALUES {placeholders};
""".strip()

    params: list[str] = []
    for row in data:
        if len(row) != len(SPLITWISE_INSERT_COLUMNS):
            raise ValueError(
                f"Splitwise row has {len(row)} values; "
                f"expected {len(SPLITWISE_INSERT_COLUMNS)}"
            )
        params.extend(str(value) for value in row)

    return sql, params


def prepare_insert_batches(
    data: list[list[str | int]], batch_size: int = SPLITWISE_INSERT_BATCH_SIZE
) -> list[tuple[str, list[str]]]:
    if batch_size < 1:
        raise ValueError("Batch size must be at least 1")

    return [
        prepare_insert(data[idx : idx + batch_size])
        for idx in range(0, len(data), batch_size)
    ]


def import_splitwise_data(
    config: Config, cf_client: Cloudflare, cloudflare_account_id_secret: SecretStr
) -> None:
    splitwise_data = read_splitwise_csv(config.kb.splitwise_csv_path)
    _, rows = splitwise_data[0], splitwise_data[1:]
    cleaned_data = clean_splitwise_data(rows)
    log.info(f"Cleaned {len(cleaned_data)} Splitwise rows")
    insert_batches = prepare_insert_batches(cleaned_data)
    log.info(f"Prepared {len(insert_batches)} Splitwise insert batches")
    for batch_idx, (insert_sql, insert_params) in enumerate(insert_batches, start=1):
        log.debug(f"Prepared Splitwise insert SQL for batch {batch_idx}: {insert_sql}")
        log.debug(
            f"Prepared {len(insert_params)} Splitwise insert parameters "
            f"for batch {batch_idx}"
        )
        result = cf_client.d1.database.query(
            database_id=os.environ.get("KIRANA_DB_ID") or "",
            account_id=cloudflare_account_id_secret.get_secret_value(),
            sql=insert_sql,
            params=insert_params,
        )
        log.info(f"Inserted Splitwise batch {batch_idx} -> {result.result} ")


def main():
    config = load_config("config.toml")
    cloudflare_account_id_secret = SecretStr(
        os.environ.get("CLOUDFLARE_ACCOUNT_ID") or ""
    )
    cloudflare_api_tok_secret = SecretStr(os.environ.get("CLOUDFLARE_API_TOKEN") or "")
    cf_client = Cloudflare(api_token=cloudflare_api_tok_secret.get_secret_value())
    import_splitwise_data(config, cf_client, cloudflare_account_id_secret)
    log.info("Splitwise data imported successfully")


if __name__ == "__main__":
    main()
