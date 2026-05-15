from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parent

CONDITIONS = {
    "Plain LLM\n(no tools)": ROOT / "kirana-agent-raw-no-tools.json",
    "Procedural prompt\n+ tools": ROOT / "kirana_agent_tools_and_instruction_following.json",
    "Sparse ICL prompt\n+ tools": ROOT / "kirana_agent_icl.json",
}

QF_ORDER = ["QF-1", "QF-2", "QF-3", "QF-4"]


def load_result(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_cases(result: dict[str, Any]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for qf in QF_ORDER:
        cases.extend(result.get(qf, {}).get("details", []))
    return cases


def telemetry_value(case: dict[str, Any], key: str) -> float:
    telemetry = case.get("agent_response", {}).get("telemetry", {})
    value = telemetry.get(key)

    if value is None:
        # Older result payloads may only expose per-turn stats.
        turns = case.get("agent_response", {}).get("turns", [])
        if key == "latency_seconds":
            value = sum(
                turn.get("message", {})
                .get("stats", {})
                .get("total_tat_seconds", 0)
                for turn in turns
            )
        elif key == "tool_calls":
            value = sum(
                turn.get("message", {}).get("stats", {}).get("tool_calls", 0)
                for turn in turns
            )

    return float(value or 0)


def success_rates(result: dict[str, Any]) -> list[float]:
    rates: list[float] = []
    for qf in QF_ORDER:
        qf_result = result[qf]
        passed = qf_result["test_cases_passed"]
        total = qf_result["test_cases_total"]
        rates.append((passed / total) * 100)
    return rates


def average_metric(result: dict[str, Any], key: str) -> float:
    values = [telemetry_value(case, key) for case in test_cases(result)]
    return mean(values)


def total_metric(result: dict[str, Any], key: str) -> float:
    return sum(telemetry_value(case, key) for case in test_cases(result))


def overall_success_rate(result: dict[str, Any]) -> float:
    passed = sum(result[qf]["test_cases_passed"] for qf in QF_ORDER)
    total = sum(result[qf]["test_cases_total"] for qf in QF_ORDER)
    return (passed / total) * 100


def tokens_per_success(result: dict[str, Any]) -> float:
    passed = sum(result[qf]["test_cases_passed"] for qf in QF_ORDER)
    if passed == 0:
        return 0
    return total_metric(result, "total_tokens") / passed


def add_value_labels(ax: plt.Axes, fmt: str) -> None:
    for container in ax.containers:
        ax.bar_label(container, fmt=fmt, padding=3, fontsize=8)


def save_success_chart(results: dict[str, dict[str, Any]]) -> None:
    fig, ax = plt.subplots(figsize=(10, 6))
    x_positions = range(len(QF_ORDER))
    width = 0.25

    for idx, (label, result) in enumerate(results.items()):
        offset = (idx - 1) * width
        ax.bar(
            [x + offset for x in x_positions],
            success_rates(result),
            width,
            label=label,
        )

    ax.set_title("Task Success Rate by Query Family")
    ax.set_ylabel("Success rate (%)")
    ax.set_xlabel("Query family")
    ax.set_xticks(list(x_positions), QF_ORDER)
    ax.set_ylim(0, 110)
    ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.5)
    ax.legend()
    add_value_labels(ax, "%.0f%%")
    fig.tight_layout()
    fig.savefig(ROOT / "task_success_rate_by_qf.png", dpi=200)
    plt.close(fig)


def save_condition_metric_chart(
    results: dict[str, dict[str, Any]],
    metric_key: str,
    title: str,
    ylabel: str,
    output_name: str,
) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = list(results)
    values = [average_metric(result, metric_key) for result in results.values()]

    ax.bar(labels, values, width=0.55)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.5)
    add_value_labels(ax, "%.2f")
    fig.tight_layout()
    fig.savefig(ROOT / output_name, dpi=200)
    plt.close(fig)


def save_token_breakdown_chart(results: dict[str, dict[str, Any]]) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = list(results)
    input_tokens = [
        average_metric(result, "input_tokens") for result in results.values()
    ]
    output_tokens = [
        average_metric(result, "output_tokens") for result in results.values()
    ]

    ax.bar(labels, input_tokens, width=0.55, label="Input tokens")
    ax.bar(
        labels,
        output_tokens,
        width=0.55,
        bottom=input_tokens,
        label="Output tokens",
    )

    ax.set_title("Average Token Breakdown by Condition")
    ax.set_ylabel("Average tokens per test case")
    ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.5)
    ax.legend()

    totals = [i + o for i, o in zip(input_tokens, output_tokens)]
    for idx, total in enumerate(totals):
        ax.text(idx, total, f"{total:,.0f}", ha="center", va="bottom", fontsize=8)

    fig.tight_layout()
    fig.savefig(ROOT / "token_breakdown_by_condition.png", dpi=200)
    plt.close(fig)


def save_tokens_per_success_chart(results: dict[str, dict[str, Any]]) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = list(results)
    values = [tokens_per_success(result) for result in results.values()]

    ax.bar(labels, values, width=0.55)
    ax.set_title("Tokens per Successful Answer")
    ax.set_ylabel("Total tokens / passed test case")
    ax.grid(axis="y", linestyle="--", linewidth=0.6, alpha=0.5)
    add_value_labels(ax, "%.0f")
    fig.tight_layout()
    fig.savefig(ROOT / "tokens_per_successful_answer.png", dpi=200)
    plt.close(fig)


def save_accuracy_cost_frontier(results: dict[str, dict[str, Any]]) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))

    for label, result in results.items():
        x = average_metric(result, "total_tokens")
        y = overall_success_rate(result)
        ax.scatter(x, y, s=120)
        ax.annotate(
            label.replace("\n", " "),
            (x, y),
            textcoords="offset points",
            xytext=(8, 8),
            fontsize=9,
        )

    ax.set_title("Accuracy-Cost Frontier")
    ax.set_xlabel("Average total tokens per test case")
    ax.set_ylabel("Overall success rate (%)")
    ax.set_ylim(0, 105)
    ax.grid(True, linestyle="--", linewidth=0.6, alpha=0.5)
    fig.tight_layout()
    fig.savefig(ROOT / "accuracy_cost_frontier.png", dpi=200)
    plt.close(fig)


def main() -> None:
    results = {label: load_result(path) for label, path in CONDITIONS.items()}

    save_success_chart(results)
    save_condition_metric_chart(
        results,
        metric_key="latency_seconds",
        title="Average Latency by Condition",
        ylabel="Average latency (seconds)",
        output_name="average_latency_by_condition.png",
    )
    save_condition_metric_chart(
        results,
        metric_key="tool_calls",
        title="Average Tool Calls by Condition",
        ylabel="Average tool calls per test case",
        output_name="average_tool_calls_by_condition.png",
    )
    save_condition_metric_chart(
        results,
        metric_key="total_tokens",
        title="Average Token Burn by Condition",
        ylabel="Average total tokens per test case",
        output_name="average_tokens_by_condition.png",
    )
    save_token_breakdown_chart(results)
    save_tokens_per_success_chart(results)
    save_accuracy_cost_frontier(results)

    print("Saved task_success_rate_by_qf.png")
    print("Saved average_latency_by_condition.png")
    print("Saved average_tool_calls_by_condition.png")
    print("Saved average_tokens_by_condition.png")
    print("Saved token_breakdown_by_condition.png")
    print("Saved tokens_per_successful_answer.png")
    print("Saved accuracy_cost_frontier.png")


if __name__ == "__main__":
    main()
