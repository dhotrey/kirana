# Kirana Agent Guide

## Project Shape

- This is an early-stage research/prototype repo for grocery finance QA across receipts, Splitwise exports, and pantry/item images.
- The main design goal is to compare retrieval strategy vs. model tier. Preserve the ablation boundaries described in `README.md`: SQL-only vs. hybrid retrieval, weak vs. strong model, plus a plain-LLM baseline.
- Current code lives under `backend/`. Treat `backend/.venv/` as generated local environment state; do not read, edit, format, or commit files inside it.

## Backend Workflow

- Use Python `>=3.13`.
- Manage backend dependencies with `uv` from the `backend/` directory.
- Common commands:
  - `cd backend && uv sync`
  - `cd backend && uv run python main.py`
- Keep `backend/uv.lock` in sync when changing dependencies in `backend/pyproject.toml`.

## Implementation Conventions

- Prefer small, typed Python modules over putting substantial logic in `main.py`.
- Use Pydantic models for structured data crossing module boundaries: receipt JSON, Splitwise rows, tool inputs/outputs, evaluation cases, and trace payloads.
- When adding, removing, or changing API endpoints, update the API documentation in `docs/` in the same change. Keep the documented Swagger/OpenAPI path, request bodies, response shapes, and error cases aligned with `main.py`.
- Keep deterministic retrieval and accounting logic outside LLM prompts where possible. Use parameterized SQL/templates for predictable factual and reconciliation queries.
- Limit schema-grounded LLM SQL generation to analytical/multi-hop query paths, and validate it as read-only before execution.
- When adding agent/tool routing, make routing decisions explicit and observable rather than hidden in synthesis prompts.

## Data & Privacy

- Treat grocery receipts, pantry images, exports, local DBs, embeddings, and Logfire tokens as private user data.
- Do not commit `.env`, local databases, raw receipts/images, Chroma stores, generated embeddings, or files under `knowledge-base/`.
- Keep telemetry lightweight and intentional. Prefer Pydantic Logfire spans for query traces instead of adding persistent local telemetry services.

## Testing & Evaluation

- When adding behavior, add focused tests or evaluation fixtures for the affected query family.
- For financial answers, preserve the README tolerance unless the project explicitly changes it: `±$3` or `±5%`, whichever is larger.
- Ground truth for evaluation cases should be hand-verified before running model comparisons.
- If adding cross-modal or RAG behavior, log enough metadata to inspect retrieval recall, selected receipt IDs, tool calls, latency, and model choice.

## Before Finishing Work

- Run the narrowest relevant check available. For the current backend skeleton, use `cd backend && uv run python main.py`.
- If tests or linters are introduced later, document and run them with `uv run ...` from `backend/`.
- Keep README claims, environment flags, and evaluation conditions aligned with code changes.
