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


from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


@dataclass(frozen=True)
class IngestionContext:
    cfg: Config
    cf_client: Any
    s3_client: Any
    cloudflare_account_id: SecretStr
    rate_limiter: GeminiRateLimiter
    embedder: Embedder
    gemini_agent: Agent
    mistral_agent: Agent
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


def _model_routes_via_gemini(model_name: str) -> bool:
    m = model_name.lower()
    return "gemini" in m or "google-ai-studio" in m


def _gateway_byok_alias(model_name: str) -> str | None:
    """BYOK provider alias for Cloudflare AI Gateway (cf-aig-byok-alias header)."""
    if _model_routes_via_gemini(model_name):
        return "gemini"
    if "mistral" in model_name.lower():
        return "mistral"
    return None


def _build_agent(model_name: str, cfg: Config) -> Agent:
    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    gateway_token = os.environ["CLOUDFLARE_AI_GATEWAY_API_TOKEN"]
    base_url = (
        "https://gateway.ai.cloudflare.com/v1/"
        f"{account_id}/{cfg.cloudflare.ai_gateway_name}/compat"
    )
    _gw_headers: dict[str, str] = {
        "cf-aig-authorization": f"Bearer {gateway_token}",
    }
    if _alias := _gateway_byok_alias(model_name):
        _gw_headers["cf-aig-byok-alias"] = _alias
    client = AsyncOpenAI(
        api_key="",
        base_url=base_url,
        default_headers=_gw_headers,
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

    gateway_token = (os.environ.get("CLOUDFLARE_AI_GATEWAY_API_TOKEN") or "").strip()
    if not gateway_token:
        raise ValueError(
            "CLOUDFLARE_AI_GATEWAY_API_TOKEN is not set or empty "
            "(AI Gateway bearer for OpenAI-compatible routes)"
        )

    cf_client = Cloudflare(api_token=cloudflare_api_token.get_secret_value())
    return IngestionContext(
        cfg=cfg,
        cf_client=cf_client,
        s3_client=_build_s3_client(cfg),
        cloudflare_account_id=cloudflare_account_id,
        rate_limiter=GeminiRateLimiter(cfg.ingestion.gemini_min_interval_seconds),
        embedder=Embedder(
            cfg.ingestion.embedding_model,
            cfg.ingestion.embedding_dim,
            logger.bind(image_id="-"),
        ),
        gemini_agent=_build_agent(cfg.ingestion.gemini_model, cfg),
        mistral_agent=_build_agent(cfg.ingestion.mistral_model, cfg),
        log=logger.bind(image_id="-"),
    )
