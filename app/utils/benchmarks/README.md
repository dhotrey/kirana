# Benchmark Harness

The benchmark harness wraps the existing chat streaming API. A fresh
`BenchmarkClient.query(...)` call starts a new conversation. Calling
`AgentResponse.follow_up(...)` sends another turn to the same API thread and
returns a new response object with cumulative telemetry for the whole
conversation.

Run the app first from `app/`:

```sh
uv run python main.py
```

Run the repository benchmark CLI from a second shell in `app/`:

```sh
uv run python bench.py --all
uv run python bench.py --QF1
uv run python bench.py --all --no-tools --out ../benchmark-results/kirana-agent-raw-no-tools.json
uv run python bench.py --all --system_prompt system_icl.md --out ../benchmark-results/kirana_agent_icl.json
```

See [docs/evaluation.md](../../../docs/evaluation.md) for `bench.py` flags (including the default QF-1-only run when no family is selected) and QF-3 judge pacing.

Then use the harness:

```python
from utils.benchmarks import BenchmarkClient

with BenchmarkClient(model="mistral") as benchmark:
    response = benchmark.query("How much did we spend on groceries in March?")
    response = response.follow_up("List the receipts behind that total.")

print(response.content)
print(response.latency_seconds)
print(response.input_tokens, response.output_tokens, response.total_tokens)
print(response.tools_called)
print(response.telemetry.model_dump())
```

Telemetry is aggregated across the current conversation only. A separate
`query(...)` call creates a fresh conversation and therefore a fresh telemetry
window.
