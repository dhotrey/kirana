# Prompt Files

Prompt text lives under `app/prompts/`. The directory path is configured as `[ingestion].prompts_dir` (default `prompts` relative to `app/`).

## Chat and evaluation

| File | Used by | Role |
|---|---|---|
| `system_prompt.md` | Default chat system message | Tool-routing and finance rules for the LangGraph agent. Loaded on every model call with a prepended `Today's date is YYYY-MM-DD.` line. Not stored in conversation history. |
| `system_icl.md` | Benchmark ablations | Sparse in-context examples for the same tool surface as `system_prompt.md`. Pass via `system_prompt` on chat APIs or `bench.py --system_prompt system_icl.md`. |

Per-request overrides (`ChatRequest.system_prompt`, form field on image stream, or `bench.py --system_prompt`) send the **file contents** as the override; they do not change files on disk.

## Ingestion

| File | Used by | Role |
|---|---|---|
| `receipt_extraction.md` | `app/ingestion/gemini.py` | Structured JSON extraction from receipt images through AI Gateway. |
| `receipt_summary.md` | `app/ingestion/mistral.py` | Short semantic summary of a validated receipt for Vectorize indexing. |

Ingestion prompts are versioned with the repo. Chat system prompts are the main lever for retrieval ablations documented in [evaluation](./evaluation.md).
