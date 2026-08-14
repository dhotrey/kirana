# Evaluation

Kirana's benchmark is organized around grocery finance query families and ablation conditions that compare retrieval strategy against model tier.

## Query Families

| Family | Query Shape | Implemented Capability |
|---|---|---|
| QF1: Household aggregation | Single-turn date-window totals. | Date-filtered receipt aggregation over `receipts.total_cents`. |
| QF2: Uploaded image purchase recall | Query-time item image matched against historical purchases. | Image embedding, item-vector search, and SQL confirmation against historical receipt line items. |
| QF3: Date and semantic trip analysis | Date-specific receipt totals, semantic trip discovery, and item inspection within identified trips. | Combination of D1 lookup, receipt-summary vector search, receipt ID narrowing, and line-item inspection. |
| QF4: Conversational drill-down | Multi-turn refinement from totals into receipts, grouped dates, stores, item counts, and personal share. | Threaded follow-up over prior context, structured receipt breakdowns, and Splitwise personal-share lookup. |

## Example Queries

- QF1: How much did my household spend on groceries in the month of April?
- QF2: Upload an item image and ask: have we ever bought this or something similar to this in our grocery trips before?
- QF3: How much did I spend on 18th April? Can you list the receipts and the total amount spent?
- QF3: What were all the fresh veggies shopping trips in March?
- QF3: Can you tell me what I got at Woolworths in these identified trips?
- QF4: How much did my household spend on groceries in the month of March?
- QF4: Can you list the different receipts involved in this as a list?
- QF4: Can you group them by date, list each date's total spend, and tell me which stores were involved on that day and how many items were in each store?
- QF4: Can you tell me what my contribution was for the groceries purchased on 18th March?

## Ablation Study

Research question: how much answer quality comes from retrieval strategy versus model tier?

Preserve these project-level comparison boundaries:

| Boundary | Conditions | Purpose |
|---|---|---|
| Retrieval strategy | SQL-only retrieval vs. hybrid SQL + Vectorize retrieval. | Isolates deterministic structured lookup from semantic receipt and item retrieval. |
| Model tier | Weak model vs. strong model with the same retrieval condition. | Measures whether better model reasoning changes outcomes after evidence is retrieved. |
| Baseline | Plain LLM with tools disabled. | Measures behavior without SQL or Vectorize access. |

Current benchmark support in `app/bench.py`:

- With no family flags, `bench.py` runs **QF-1 only** (`selected_query_families` defaults to `["QF-1"]`). Use `--all` or `--QF2` / `--QF3` / `--QF4` to select other families.
- Default runs use the first model alias in `app/config.toml` with tools enabled.
- `--no-tools` disables SQL and Vectorize tools for the plain-LLM baseline.
- `--system_prompt` sends a per-request prompt override, for example `system_icl.md`, without modifying prompt files.
- `--out` writes each condition to a distinct result JSON.

When comparing conditions, keep the knowledge base, benchmark cases, setup state, and evaluation rubric fixed.

## Running Benchmarks

Run the app from one shell:

```sh
cd app
uv run python main.py
```

Run benchmarks from a second shell:

```sh
cd app
uv run python bench.py --all
uv run python bench.py --all --system_prompt system_icl.md --out ../benchmark-results/kirana_agent_icl.json
uv run python bench.py --all --no-tools --out ../benchmark-results/kirana-agent-raw-no-tools.json
```

Generate benchmark charts from saved result JSON files:

```sh
cd app
uv run python ../benchmark-results/generate_benchmark_charts.py
```

The benchmark harness is documented in [app/utils/benchmarks/README.md](../app/utils/benchmarks/README.md).

## Metrics

`app/bench.py` writes results to `app/kirana_agent_tools_and_instruction_following.json` by default, or to the `--out` path when provided. Each query family records `test_cases_passed`, `test_cases_total`, `model`, and per-case `details`.

### Correctness

- QF1 numeric correctness: extracts the first numeric value from the answer and requires exact equality with the expected value.
- QF2 image recall correctness: normalizes the answer to `yes` or `no` and compares it with the expected label.
- QF3 judged semantic correctness: sends the question, expected answer, and agent response to the configured judge model. The case passes only when the judge returns exactly `YES`.
- QF4 conversational numeric correctness: runs follow-up turns in one thread, extracts the first numeric value from each answer, and requires exact equality with the expected value.
- Case failures and errors: each case stores `passed`, `actual`, `expected` or `expectation`, and `error` when the benchmark call or judge call fails.

For financial answer evaluation, preserve the project tolerance unless an experiment explicitly changes it: `+$3/-$3` or `+/-5%`, whichever is larger. Current exact-match benchmark cases are narrower than that project-level tolerance.

### Runtime Telemetry

Each stored `agent_response` includes cumulative telemetry across the turns in that response:

- `latency_seconds`: sum of chat turn `total_tat_seconds` values from the streamed end events.
- `input_tokens`, `output_tokens`, and `total_tokens`.
- `tool_calls`: total tool-call count.
- `tools_called`: ordered list of tool names reported by the app.
- `rate_limit_retries`: total retries reported in chat message stats.
- `turns`: number of turns represented in the response, including prior turns for QF4 follow-ups.

For QF3, `judge_telemetry` separately records judge-call `latency_seconds`, `input_tokens`, `output_tokens`, and `total_tokens`.
