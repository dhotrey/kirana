from dotenv import load_dotenv
import os
from pydantic import SecretStr
from cloudflare import Cloudflare
from utils.db.db_setup import (
    splitwise_create_table_sql,
    receipts_create_table_sql,
    reciept_items_create_table_sql,
    splitwise_expense_views_sql,
    create_indexes_sql,
)
from utils.types import Config as Cfg
from utils.config import load_config
from utils.logger import log
import boto3
from botocore.client import Config

load_dotenv()


class SetupError(Exception):
    """Raised when infrastructure setup cannot continue."""


def setup_tigris(infra_config: Cfg):
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        endpoint_url=infra_config.tigris.aws_endpoint_url_s3,
        config=Config(s3={"addressing_style": "virtual"}),
    )

    s3_client.create_bucket(Bucket=infra_config.tigris.bucket_name)
    log.info(f"Tigris bucket created: {infra_config.tigris.bucket_name}")


def setup_d1(cf_client, cloudflare_account_id_secret: SecretStr, infra_config: Cfg):
    log.info("Setting up D1 database...")
    db_id = os.environ.get("KIRANA_DB_ID")
    if db_id is None:
        d1 = cf_client.d1.database
        try:
            kirana = d1.create(
                account_id=cloudflare_account_id_secret.get_secret_value(),
                name=infra_config.cloudflare.d1_database_name,
            )
            db_id = kirana.uuid
            if db_id is None:
                raise SetupError("D1 database creation did not return a database ID")
            os.environ["KIRANA_DB_ID"] = db_id
            log.info(f"D1 database created for kirana: {kirana.name}")
            # Persist the generated ID for future setup runs.
            with open(".env", "a", encoding="utf-8") as f:
                f.write(f"KIRANA_DB_ID={db_id}\n")
            log.debug(f"Wrote KIRANA_DB_ID to .env: {db_id}")
        except SetupError:
            raise
        except Exception as e:
            raise SetupError(
                "Error creating D1 database for kirana. "
                "Set KIRANA_DB_ID in .env if the database already exists."
            ) from e
    else:
        log.info("Using existing KIRANA_DB_ID from environment")

    db_setup_statements = [
        splitwise_create_table_sql,
        receipts_create_table_sql,
        reciept_items_create_table_sql,
        splitwise_expense_views_sql,
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


def setup_vectorize(
    cf_client, cloudflare_account_id_secret: SecretStr, infra_config: Cfg
):
    log.info("Setting up Cloudflare Vectorize...")
    for index_name in (
        infra_config.cloudflare.vectorize_index_name,
        infra_config.cloudflare.vectorize_item_index_name,
    ):
        kirana_vectorize_index = cf_client.vectorize.indexes.create(
            account_id=cloudflare_account_id_secret.get_secret_value(),
            name=index_name,
            config={
                "dimensions": infra_config.cloudflare.vectorize_index_dimension,
                "metric": "cosine",
            },
        )
        if kirana_vectorize_index is None:
            raise SetupError(f"Cloudflare Vectorize index creation failed: {index_name}")
        else:
            log.info(
                f"Cloudflare Vectorize index created for {index_name} "
                f"with config: {kirana_vectorize_index.config}"
            )


def setup_vectorize_metadata_indices(
    cf_client, cloudflare_account_id_secret: SecretStr, infra_config: Cfg
):
    log.info("Setting up metadata indices for Cloudflare Vectorize...")
    index_metadata = [
        (
            infra_config.cloudflare.vectorize_index_name,
            infra_config.cloudflare.vectorize_index_metadata_fields,
            infra_config.cloudflare.vectorize_index_metadata_field_types,
        ),
        (
            infra_config.cloudflare.vectorize_item_index_name,
            infra_config.cloudflare.vectorize_item_index_metadata_fields,
            infra_config.cloudflare.vectorize_item_index_metadata_field_types,
        ),
    ]
    for index_name, metadata_fields, metadata_field_types in index_metadata:
        for idx_name, idx_type in zip(metadata_fields, metadata_field_types, strict=True):
            metadata_index = cf_client.vectorize.indexes.metadata_index.create(
                index_name=index_name,
                index_type=idx_type,
                account_id=cloudflare_account_id_secret.get_secret_value(),
                property_name=idx_name,
            )
            if metadata_index is None:
                raise SetupError(
                    f"Metadata index creation failed for {index_name}.{idx_name} "
                    f"with type {idx_type}"
                )
            else:
                log.info(
                    f"Metadata index created for {index_name}.{idx_name} "
                    f"with type {idx_type} and mutation id {metadata_index.mutation_id}"
                )


def setup_ai_gateway(
    cf_client, cloudflare_account_id_secret: SecretStr, infra_config: Cfg
):
    log.info("Setting up AI Gateway...")

    ai_gateway = cf_client.ai_gateway.create(
        account_id=cloudflare_account_id_secret.get_secret_value(),
        id=infra_config.cloudflare.ai_gateway_name,
        cache_invalidate_on_update=True,
        cache_ttl=3600,
        collect_logs=True,
        rate_limiting_interval=0,
        rate_limiting_limit=0,
        rate_limiting_technique="fixed",
        log_management_strategy="DELETE_OLDEST",
    )
    if ai_gateway is None:
        raise SetupError("AI Gateway creation failed")
    else:
        log.info(f"AI Gateway created with id: {ai_gateway.id}")


def main():

    infra_config = load_config("config.toml")
    cloudflare_account_id_secret = SecretStr(
        os.environ.get("CLOUDFLARE_ACCOUNT_ID") or ""
    )
    cloudflare_api_token_secret = SecretStr(
        os.environ.get("CLOUDFLARE_API_TOKEN") or ""
    )

    if cloudflare_api_token_secret.get_secret_value() == "":
        raise SetupError("CLOUDFLARE_API_TOKEN is not set")
    else:
        log.info("CLOUDFLARE_API_TOKEN is set")
        try:
            cf_client = Cloudflare(
                api_token=cloudflare_api_token_secret.get_secret_value()
            )
            log.info("Cloudflare API token is valid")
        except Exception as e:
            raise SetupError(
                "Error checking if Cloudflare API token is valid. "
                "A valid API token can be obtained from "
                "https://dash.cloudflare.com/profile/api-tokens."
            ) from e

    if cloudflare_account_id_secret.get_secret_value() == "":
        raise SetupError("CLOUDFLARE_ACCOUNT_ID is not set")
    else:
        log.info("CLOUDFLARE_ACCOUNT_ID is set")
        accounts = cf_client.accounts.list(
            name=cloudflare_account_id_secret.get_secret_value()
        )
        if accounts:
            log.info("Cloudflare account ID is valid")
        else:
            raise SetupError(
                "Cloudflare account is not found. A valid account ID can be "
                "obtained from https://dash.cloudflare.com/profile/accounts."
            )

    setup_d1(cf_client, cloudflare_account_id_secret, infra_config)

    setup_vectorize(cf_client, cloudflare_account_id_secret, infra_config)
    setup_vectorize_metadata_indices(
        cf_client, cloudflare_account_id_secret, infra_config
    )
    setup_ai_gateway(cf_client, cloudflare_account_id_secret, infra_config)

    setup_tigris(infra_config)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error(f"Error setting up infrastructure: {e}")
        log.info(
            "Please check ../docs/setup.md for more information on how to set up "
            "the infrastructure"
        )
        raise SystemExit(1) from e
