from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config as BotoConfig
from cloudflare import Cloudflare
from dotenv import load_dotenv
from loguru import logger
from pydantic import SecretStr

from ingestion.embeddings import Embedder
from ingestion.rate_limit import GeminiRateLimiter
from utils.config import load_config
from utils.types import Config


@dataclass(frozen=True)
class IngestionContext:
    cfg: Config
    cf_client: Any
    s3_client: Any
    cloudflare_account_id: SecretStr
    rate_limiter: GeminiRateLimiter
    embedder: Embedder
    gemini_agent: Any
    mistral_agent: Any
    log: Any
    dry_run: bool | None = None

    @property
    def effective_dry_run(self) -> bool:
        return self.cfg.ingestion.dry_run if self.dry_run is None else self.dry_run

    @property
    def prompts_dir(self) -> Path:
        return Path(self.cfg.ingestion.prompts_dir)

    @property
    def logs_dir(self) -> Path:
        return Path(self.cfg.ingestion.logs_dir)

    def with_log(self, log: Any) -> "IngestionContext":
        return replace(self, log=log)

    def with_dry_run(self, dry_run: bool | None) -> "IngestionContext":
        return replace(self, dry_run=dry_run)


def _build_agent(model_name: str, cfg: Config) -> Any:
    from openai import AsyncOpenAI
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    gateway_token = os.environ["CLOUDFLARE_AI_GATEWAY_API_TOKEN"]
    base_url = (
        "https://gateway.ai.cloudflare.com/v1/"
        f"{account_id}/{cfg.cloudflare.ai_gateway_name}/compat"
    )
    client = AsyncOpenAI(
        api_key="unused",
        base_url=base_url,
        default_headers={"cf-aig-authorization": f"Bearer {gateway_token}"},
    )
    provider = OpenAIProvider(openai_client=client)
    return Agent(OpenAIChatModel(model_name, provider=provider))


def _build_s3_client(cfg: Config) -> Any:
    return boto3.client(
        "s3",
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        endpoint_url=cfg.tigris.aws_endpoint_url_s3,
        config=BotoConfig(s3={"addressing_style": "virtual"}),
    )


def build_context(config_path: str = "config.toml") -> IngestionContext:
    load_dotenv()
    cfg = load_config(config_path)
    cloudflare_account_id = SecretStr(os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "")
    cloudflare_api_token = SecretStr(os.environ.get("CLOUDFLARE_API_TOKEN") or "")
    if not cloudflare_account_id.get_secret_value():
        raise ValueError("CLOUDFLARE_ACCOUNT_ID is not set")
    if not cloudflare_api_token.get_secret_value():
        raise ValueError("CLOUDFLARE_API_TOKEN is not set")

    cf_client = Cloudflare(api_token=cloudflare_api_token.get_secret_value())
    return IngestionContext(
        cfg=cfg,
        cf_client=cf_client,
        s3_client=_build_s3_client(cfg),
        cloudflare_account_id=cloudflare_account_id,
        rate_limiter=GeminiRateLimiter(cfg.ingestion.gemini_min_interval_seconds),
        embedder=Embedder(cfg.ingestion.embedding_model, cfg.ingestion.embedding_dim),
        gemini_agent=_build_agent(cfg.ingestion.gemini_model, cfg),
        mistral_agent=_build_agent(cfg.ingestion.mistral_model, cfg),
        log=logger.bind(image_id="-"),
    )
