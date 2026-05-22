# Kirana Technical Documentation

This folder contains technical documentation for Kirana's architecture, infrastructure, and implementation decisions.

Kirana is still an early-stage research prototype, so these docs should stay close to the code and record decisions as they become concrete. The goal is to make the retrieval design, infrastructure shape, evaluation assumptions, and setup requirements easy to inspect without overloading the project README.

## Where to look

| Goal | Document |
|---|---|
| First-time Cloudflare, Tigris, gateway, Logfire | [Setup](./setup.md) |
| How chat, tools, stores, and ingestion fit together | [Architecture](./architecture.md) |
| Tables, views, indexes, Vectorize metadata | [Data model](./data-model.md) |
| Receipt / Splitwise / item-vector CLIs and pipeline stages | [Ingestion](./ingestion.md) |
| HTTP and SSE contracts | [API](./api.md) |
| Benchmarks, ablations, metrics | [Evaluation](./evaluation.md) |
| Local failures and configuration pitfalls | [Troubleshooting](./troubleshooting.md) |

`app/main.py` sets Hugging Face-related environment variables at import time (including `HF_HUB_OFFLINE=1` for deterministic local runs). That affects first-time embedding model downloads; see [Troubleshooting](./troubleshooting.md#models-and-local-embeddings).

## Current Documents

- [Setup](./setup.md): infrastructure setup, required credentials, and the resources created by `app/setup.py`.
- [Architecture](./architecture.md): chat graph, registered tools, finance store, vector indexes, and retrieval modalities.
- [Data Model](./data-model.md): D1 tables, views, SQL indexes, Vectorize indexes, metadata fields, and local SQLite tables.
- [Ingestion Pipeline](./ingestion.md): receipt CLI flow, Splitwise import separation, storage responsibilities, observability, and error handling.
- [API Endpoints](./api.md): FastAPI Swagger/OpenAPI locations and the current chat API request/response contracts.
- [Evaluation](./evaluation.md): query families, ablation boundaries, benchmark commands, correctness rules, and runtime telemetry.
- [Troubleshooting](./troubleshooting.md): common chat, embedding, ingestion, and configuration pitfalls with fixes.
- [Benchmark Harness](../app/utils/benchmarks/README.md): local benchmark client usage against the streaming chat API.

## Common Entry Points

Run these from `app/` unless noted otherwise:

```sh
uv sync
uv run python main.py
uv run python setup.py
uv run python ingest_kb.py
uv run python ingest_receipts.py
uv run python load_item_vectors.py
uv run python bench.py --all
```

Generate saved benchmark charts through the `app/` uv environment:

```sh
cd app
uv run python ../benchmark-results/generate_benchmark_charts.py
```
