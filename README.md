# Kirana


## Introduction & Motivation
Personal grocery spending is fragmented across three structurally distinct layers: unstructured receipts encoding what was bought, structured expense splits encoding who paid what, and real-world visual context encoding what is currently in the pantry. Users naturally ask questions that span precise financial aggregation, fuzzy semantic recall, and cross-modal grounding — query types that expose a fundamental mismatch between LLM strengths (semantic understanding, vision parsing) and LLM weaknesses (exact arithmetic, cross-source reconciliation).

This project frames a systems research question: does deterministic, tool-mediated retrieval neutralise the performance gap between model tiers for personal finance QA? We hypothesize that externalising reasoning into structured tool orchestration — SQL for aggregation, semantic RAG for fuzzy retrieval, and cross-modal vector search for visual grounding — makes retrieval strategy the primary driver of answer quality, not raw model scale.

A second, technically distinctive claim motivates the retrieval design: using a single multimodal embedding model (Qwen3-VL-Embedding-2B) to embed both OCR-derived receipt summaries and user-provided pantry photos into a shared vector space makes cross-modal retrieval semantically meaningful — a query about current pantry contents can retrieve historically relevant receipts without requiring a modality boundary in the index. We test whether this unified embedding space provides retrieval signal beyond a text-only index.

Against a plain-LLM baseline (no tools, receipts injected as context), the ablation isolates how much of the performance delta is attributable to the harness itself versus model scale.

## Goals

- Answer grocery finance questions accurately across four query families (factual, cross-modal, analytical/multi-hop, conversational follow-up), with a plain-LLM baseline as the lower bound.

- Support hybrid retrieval over two persistent modalities (receipt text + validated JSON; Splitwise CSV) and one query-time modality (pantry/item images), with all three embedded into a shared vector space via Qwen3-VL-Embedding-2B.

- Implement and evaluate a single, strong ablation: a 2×2 factorial over retrieval strategy × model tier, plus a plain-LLM baseline — testing whether the harness closes the performance gap between models.

- Capture full query traces via Pydantic Logfire (token burn, tool calls, routing decisions, latency as a sum of parts — e.g. embedding accounts for 2s, retrieval 5s, synthesis 3s) with zero persistent local telemetry overhead.

- Expose inline query stats in the UI (latency, tokens, tool hops, model) with full traces available in Logfire.

## Non-Goals

- Cross-session memory persistence
- Live receipt scanning or real-time camera ingestion
- Multi-user support or budget advisory features
- Automatic Splitwise API sync (manual CSV export only)
- Persistent local telemetry processes (Prometheus, Grafana, local OTel collectors)
- A polished production UI

## Knowledge Base & Modalities

### Modality 1 — Receipt Images (Persistent)
Raw grocery receipt photographs. At ingestion, a hosted vision model extracts and structures text into validated JSON (store, date, address, line items with inferred category, subtotal, GST, discounts, total). A natural-language summary of the shop's semantic character is generated and embedded alongside the receipt image into Qwen3-VL-Embedding-2B's shared vector space. This unified embedding enables retrieval from both text queries and image queries against the same index — the key technical claim of the retrieval design.

### Modality 2 — Splitwise Structured Export (Persistent)
CSV mapping each shared grocery shop to per-person payment amounts, dates, and descriptions. Stored in a relational database. Provides the financial attribution dimension (personal vs. household share) that receipt images cannot answer alone. Cross-source reconciliation between receipts and Splitwise entries — matched on date proximity and total amount — is the primary multi-hop retrieval pattern.

### Modality 3 — Pantry/Item Images (Query-Time)
Photos of the user's current pantry, fridge, or cupboard, provided at query time. Embedded via Qwen3-VL-Embedding-2B into the same vector space as receipt summaries. Enables semantic retrieval of historically relevant receipts based on visual pantry context, without requiring a separate image→text transcription step before retrieval.


## Ablation Study

Single axis, 2×2 factorial design with a plain-LLM baseline:

| Condition | Retrieval Strategy | Model | Purpose |
|---|---|---|---|
| C0 | None (plain LLM) | Strong (Gemini Flash) | Lower bound; establishes what tool-free reasoning achieves with a strong model |
| C1 | SQL-only | Weak (Gemma 4B) | Single-mode, weak model |
| C2 | SQL-only | Strong (Gemini Flash) | Single-mode, strong model; isolates model effect without hybrid retrieval |
| C3 | Hybrid (SQL + RAG + cross-modal) | Weak (Gemma 4B) | Full harness, weak model |
| C4 | Hybrid (SQL + RAG + cross-modal) | Strong (Gemini Flash) | Full harness, strong model; expected ceiling |

- **Primary claim (H1):** C3 ≈ C4 on task success rate and groundedness — hybrid retrieval closes the model-tier gap. The performance delta (C2 − C1) should be larger than (C4 − C3).
- **Secondary claim (H2):** C3 > C2 — hybrid retrieval with a weak model outperforms SQL-only retrieval with a strong model — demonstrating retrieval strategy dominates model scale.
- **Baseline comparison (spec requirement):** C4 >> C0 — the full agent substantially outperforms plain-LLM prompting, establishing the harness's contribution.

All conditions selectable via environment variables with no code changes.

## Query Families

| Family | Example | Expected Path | Capability Tested |
|---|---|---|---|
| QF-1: Factual | "How much did I spend at Woolworths last week?" | Router → SQL (parameterised template) → Synthesis | Date filtering, aggregation, single-source lookup |
| QF-2: Cross-Modal | "What was my personal share of the big Coles shop on Mar 12?" | Router → SQL (parameterised receipt JOIN splits template, date/amount slot-filled) → Synthesis | Cross-source reconciliation, fuzzy matching, financial attribution |
| QF-3: Analytical / Multi-Hop | "Over 3 months, am I spending more on fresh or packaged food, and how does that track against my share?" | Router → RAG (semantic filter on receipt summaries) → SQL (schema-grounded LLM generation on matched IDs) → Synthesis → Optional chart | Multi-tool chaining, semantic → structured bridge, LLM SQL generation for variable aggregation logic |
| QF-4: Conversational Follow-Up | T1: "Show March spend." T2: "What about February?" | Router → State-aware retrieval → Synthesis (resolves references against session history) | Within-session memory, reference resolution, context pruning |

Minimum corpus: 36 receipts, 12+ labelled test cases (≥3 per family). Ground truth answers hand-verified against source data before any eval runs, with fixed numerical tolerance (see OQ-5).

## SQL Generation Design

The agent uses two distinct SQL strategies depending on query shape, keeping the ablation's confounds isolated.

**Parameterised templates (QF-1, QF-2):** Query shapes for factual and cross-modal retrieval are fully predictable at design time — date range filters on the receipts table, receipt-to-splits joins matched on date proximity and total amount, single-store aggregations. These are enumerated as parameterised templates; the LLM selects a template and fills slots (date ranges, store names, receipt IDs extracted from prior retrieval steps). The SQL itself is deterministic and never LLM-generated, which keeps QF-1 and QF-2 results clean for ablation comparison.

**Schema-grounded LLM SQL generation (QF-3 only):** Analytical multi-hop queries involve aggregation logic that varies too much to template — grouping by inferred item category, multi-month window construction, joining aggregated receipt data against splits. For these, the agent passes the full table schema to a strongly-routed model and generates SQL directly. This step is instrumented as a separate Logfire span (`sql_generation`) so failures are isolatable from retrieval and synthesis failures. If SQL generation produces a malformed or unsafe query, the span logs the error and the agent falls back to returning partial results with an explanation rather than silently failing.

The template path is the default. Schema-grounded generation is an explicitly routed exception, not a fallback.

## Metrics

### Quality (per test case)

- **Task Success Rate** (binary). Numerical answers accept ±5% or ±$3 tolerance.
- **Groundedness Score** (1–5, LLM-as-judge). Evaluates source citation, hallucination absence, and correct personal vs. household attribution.
- **Retrieval Recall@k.** Whether correct receipt IDs appear in top-k before SQL filtering; measures retrieval quality independently of synthesis.
- **Tool Call Accuracy.** Proportion of queries where the router selected the correct tool sequence for the query family.

### Efficiency (auto-captured via Logfire spans)

- End-to-end latency (ms) and latency broken down by stage (embedding, retrieval, SQL generation where applicable, synthesis)
- Token burn (prompt + completion, broken down by model)
- Tool call count per query
- Retrieval precision: proportion of injected receipt IDs that were relevant to the ground-truth answer (connects retrieval quality to synthesis quality)

## Open Questions

- **OQ-1 — Fuzzy join tolerance:** How should receipts match Splitwise entries? (±2 days + ±5% amount?) What does the agent do when a single Splitwise entry spans multiple receipts? Rule-based first; flag ambiguous matches for LLM mediation only when confidence is below threshold.

- **OQ-2 — Pantry vision reliability:** VLM item extraction will miss occluded or ambiguous items. Should the agent always surface a confirmation step ("I detected: milk, eggs, pasta — correct?") or only when item count is below a minimum? Confirmation step adds a round-trip; skipping it reduces QF trust. Decide before evaluation to avoid post-hoc design changes.

- **OQ-3 — Context baseline fairness:** Is injecting all 36 receipts into a 128k context window a realistic plain-LLM baseline (C0), or should we sample a rolling window? Rolling window better simulates practical limits but introduces selection bias. Fix this before running C0 to avoid a strawman comparison.

- **OQ-4 — Cross-modal retrieval signal:** Does embedding receipt images and pantry photos in the same Qwen3-VL-Embedding-2B space produce meaningful cross-modal similarity, or does the model conflate visual food content with packaging/brand noise? Retrieval Recall@k on QF-2/QF-3 answers this empirically.

- **OQ-5 — Numerical tolerance:** What counts as "correct" for financial aggregation? This must be fixed before any evaluation run to prevent post-hoc grading bias. Proposed: ±$3 or ±5%, whichever is larger, with boundary cases documented.

- **OQ-6 — LLM SQL generation safety:** For QF-3, what constraints bound LLM-generated SQL? Read-only queries only (no INSERT/UPDATE/DELETE); queries must reference only the known schema tables; malformed output falls back gracefully. Should a query validator run before execution, or is schema-prompting sufficient?