from dotenv import load_dotenv
import os
from pydantic import SecretStr
from loguru import logger as log
from cloudflare import Cloudflare
from db.db_setup import (
    splitwise_create_table_sql,
    receipts_create_table_sql,
    reciept_items_create_table_sql,
    create_indexes_sql,
)

load_dotenv()

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


def main():

    cloudflare_account_id_secret = SecretStr(
        os.environ.get("CLOUDFLARE_ACCOUNT_ID") or ""
    )
    cloudflare_api_token_secret = SecretStr(
        os.environ.get("CLOUDFLARE_API_TOKEN") or ""
    )

    if cloudflare_api_token_secret.get_secret_value() == "":
        log.error("CLOUDFLARE_API_TOKEN is not set")
        exit(1)
    else:
        log.info("CLOUDFLARE_API_TOKEN is set")
        try:
            cf_client = Cloudflare(
                api_token=cloudflare_api_token_secret.get_secret_value()
            )
            log.info(f"Cloudflare API token is valid {cloudflare_api_token_secret}")
        except Exception as e:
            log.error(f"Error checking if Cloudflare API token is valid: {e}")
            log.info(
                "A valid API token can be obtained from https://dash.cloudflare.com/profile/api-tokens"
            )
            exit(1)

    if cloudflare_account_id_secret.get_secret_value() == "":
        log.error("CLOUDFLARE_ACCOUNT_ID is not set")
        exit(1)
    else:
        log.info("CLOUDFLARE_ACCOUNT_ID is set")
        accounts = cf_client.accounts.list(
            name=cloudflare_account_id_secret.get_secret_value()
        )
        if accounts:
            log.info(f"Cloudflare account ID is valid: {cloudflare_account_id_secret}")
        else:
            log.error("Cloudflare account is not found")
            log.info(
                "A valid account ID can be obtained from https://dash.cloudflare.com/profile/accounts"
            )
            exit(1)

    d1 = cf_client.d1.database
    try:
        kirana = d1.create(
            account_id=cloudflare_account_id_secret.get_secret_value(), name="kirana"
        )
        log.info(f"D1 database created for kirana : {kirana.name}")
        # write db_id to .env
        with open(".env", "a") as f:
            f.write(f"KIRANA_DB_ID={kirana.uuid}\n")
            log.debug(f"Wrote KIRANA_DB_ID to .env: {kirana.uuid}")
        d1._client.close()
    except Exception as e:
        log.error(
            f"Error creating D1 database for kirana it probably already exists: {e}"
        )

    db_id = os.environ.get("KIRANA_DB_ID")
    if db_id is None:
        log.error("KIRANA_DB_ID is not set")
        log.info("Please run the script again after creating the D1 database")
        exit(1)

    db_setup_statements = [
        splitwise_create_table_sql,
        receipts_create_table_sql,
        reciept_items_create_table_sql,
        create_indexes_sql,
    ]
    for statement in db_setup_statements:
        result = cf_client.d1.database.query(
            database_id=db_id,
            account_id=cloudflare_account_id_secret.get_secret_value(),
            sql=statement,
        )
        log.info(f"Executed {statement} in D1 database: {db_id}")
        log.info(f"Result: {result}")

    log.info("All tables created successfully!")

    # TODO : add setup for cf vectorize, ai gateway, tigris and logfire.


if __name__ == "__main__":
    main()
