# Kirana Technical Documentation

This folder contains technical documentation for Kirana's architecture, infrastructure, and implementation decisions.

Kirana is still an early-stage research prototype, so these docs should stay close to the code and record decisions as they become concrete. The goal is to make the retrieval design, infrastructure shape, evaluation assumptions, and setup requirements easy to inspect without overloading the project README.

## Current Documents

- [Setup](./setup.md): infrastructure setup, required credentials, and the resources created by `app/setup.py`.
- [Architecture](./architecture.md): chat graph, registered tools, finance store, vector indexes, and retrieval modalities.
- [Data Model](./data-model.md): D1 tables, views, SQL indexes, Vectorize indexes, metadata fields, and local SQLite tables.
- [Ingestion Pipeline](./ingestion.md): receipt CLI flow, Splitwise import separation, storage responsibilities, observability, and error handling.
- [API Endpoints](./api.md): FastAPI Swagger/OpenAPI locations and the current chat API request/response contracts.
- [Evaluation](./evaluation.md): query families, ablation boundaries, benchmark commands, correctness rules, and runtime telemetry.
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
