import os
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
    "date",
    "description",
    "category",
    "cost_cents",
    "currency",
    "me_cents",
    "roommate1_cents",
    "roommate2_cents",
)
D1_MAX_SQL_VARIABLES = 100
SPLITWISE_INSERT_BATCH_SIZE = D1_MAX_SQL_VARIABLES // len(SPLITWISE_INSERT_COLUMNS)
SPLITWISE_EXPECTED_COL_COUNT = len(SPLITWISE_INSERT_COLUMNS)


def read_splitwise_csv(file_path: str) -> list[list[str]]:
    with open(file_path, newline="", encoding="utf-8", mode="r") as f:
        r = reader(f)
        return [row for row in r]


def money_to_cents(value: str) -> int:
    amount = Decimal(value.strip())
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def clean_splitwise_data(data: list[list[str]]) -> list[list[str | int]]:
    cleaned_data = []
    for row in data:
        if not row or not any(cell.strip() for cell in row):
            continue
        if len(row) != SPLITWISE_EXPECTED_COL_COUNT:
            raise ValueError(
                "Splitwise row has "
                f"{len(row)} columns; expected {SPLITWISE_EXPECTED_COL_COUNT}: {row}"
            )
        if not row[SPLITWISE_COST_COL_IDX].strip():
            log.debug(f"Skipping Splitwise row without a cost: {row}")
            continue

        cleaned_row: list[str | int] = [cell.strip() for cell in row]
        for col_idx in SPLITWISE_MONEY_COL_IDXS:
            cleaned_row[col_idx] = money_to_cents(row[col_idx])

        cleaned_data.append(cleaned_row)

    return cleaned_data


def prepare_insert(data: list[list[str | int]]) -> tuple[str, list[str]]:
    if not data:
        raise ValueError("Cannot prepare a Splitwise insert with no rows")

    for row in data:
        if len(row) != SPLITWISE_EXPECTED_COL_COUNT:
            raise ValueError(
                "Cleaned Splitwise row has "
                f"{len(row)} columns; expected {SPLITWISE_EXPECTED_COL_COUNT}: {row}"
            )

    row_placeholder = "(" + ", ".join(["?"] * len(SPLITWISE_INSERT_COLUMNS)) + ")"
    placeholders = ", ".join([row_placeholder] * len(data))
    source_columns = ", ".join(f"deduped.{column}" for column in SPLITWISE_INSERT_COLUMNS)
    duplicate_match = " AND ".join(
        f"splits.{column} = deduped.{column}" for column in SPLITWISE_INSERT_COLUMNS
    )
    sql = f"""
WITH deduped ({", ".join(SPLITWISE_INSERT_COLUMNS)}) AS (
    VALUES {placeholders}
)
INSERT INTO splits ({", ".join(SPLITWISE_INSERT_COLUMNS)})
SELECT DISTINCT {source_columns}
FROM deduped
WHERE NOT EXISTS (
    SELECT 1
    FROM splits
    WHERE {duplicate_match}
);
""".strip()

    params: list[str] = []
    for row in data:
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
