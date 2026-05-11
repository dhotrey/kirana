from __future__ import annotations

import os

from langchain_openai import ChatOpenAI

from utils.types import Config


def model_routes_via_gemini(model_name: str) -> bool:
    model = model_name.lower()
    return "gemini" in model or "google-ai-studio" in model


def gateway_byok_alias(model_name: str) -> str | None:
    """BYOK provider alias for Cloudflare AI Gateway."""
    if model_routes_via_gemini(model_name):
        return "gemini"
    if "mistral" in model_name.lower():
        return "mistral"
    return None


def cloudflare_gateway_base_url(cfg: Config) -> str:
    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    return (
        "https://gateway.ai.cloudflare.com/v1/"
        f"{account_id}/{cfg.cloudflare.ai_gateway_name}/compat"
    )


def cloudflare_gateway_headers(model_identifier: str) -> dict[str, str]:
    gateway_token = os.environ["CLOUDFLARE_AI_GATEWAY_API_TOKEN"]
    headers = {"cf-aig-authorization": f"Bearer {gateway_token}"}
    if alias := gateway_byok_alias(model_identifier):
        headers["cf-aig-byok-alias"] = alias
    return headers


def build_chat_model(model_identifier: str, cfg: Config) -> ChatOpenAI:
    return ChatOpenAI(
        model=model_identifier,
        api_key="",
        base_url=cloudflare_gateway_base_url(cfg),
        default_headers=cloudflare_gateway_headers(model_identifier),
        temperature=0,
        streaming=True,
        stream_usage=True,
    )
