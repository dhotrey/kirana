from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from utils.benchmarks import BenchmarkClient
from utils.config import load_config

BASE_URL = "http://127.0.0.1:8000"
RESULTS_PATH = Path(__file__).with_name(
    "kirana_agent_tools_and_instruction_following.json"
)
SLEEP_SECONDS_BETWEEN_QUERIES = 30


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    prompt: str
    expected: str


@dataclass(frozen=True)
class ConversationBenchmarkCase(BenchmarkCase):
    is_follow_up: bool = True


QF1_CASES = [
    BenchmarkCase(
        id="qf1_001_personal_march_spend",
        prompt=(
            "How much money did I spend in the month of March ? "
            "Reply with just the amount and nothing else."
        ),
        expected="385.06",
    ),
    BenchmarkCase(
        id="qf1_002_household_april_grocery_spend",
        prompt=(
            "How much money did my household spend on groceries in the month of April ? "
            "Reply with just the amount and nothing else."
        ),
        expected="643.91",
    ),
    BenchmarkCase(
        id="qf1_003_household_march_trip_count",
        prompt=(
            "How many grocery trips did my household do in the month of March. "
            "Reply with just the number and nothing else."
        ),
        expected="11",
    ),
    BenchmarkCase(
        id="qf1_004_feb_woolworths_visit_count",
        prompt=(
            "How many times did we visit Woolworths in the month of Feb. "
            "Reply with just the number and nothing else."
        ),
        expected="0",
    ),
    BenchmarkCase(
        id="qf1_005_april_fruit_temple_visit_count",
        prompt=(
            "How many times did we visit THE FRUIT TEMPLE in April. "
            "Reply with just the number and nothing else."
        ),
        expected="6",
    ),
]

QF4_CASES = [
    ConversationBenchmarkCase(
        id="qf4_001_household_last_month_spend",
        prompt=(
            "In this conversation I am going to ask you really specific and pointed "
            "questions about my grocery shopping based on the data you have. For the "
            "duration of this conversation only reply with the amount / number that "
            "answers the question and nothing else. To start, can you tell me how "
            "much money my household spent on groceries last month."
        ),
        expected="643.91",
        is_follow_up=False,
    ),
    ConversationBenchmarkCase(
        id="qf4_002_last_month_trip_count",
        prompt="How many grocery trips did we do in that month",
        expected="19",
    ),
    ConversationBenchmarkCase(
        id="qf4_003_last_month_fruit_temple_trip_count",
        prompt="how many of those were to THE FRUIT TEMPLE",
        expected="6",
    ),
    ConversationBenchmarkCase(
        id="qf4_004_last_month_woolworths_trip_count",
        prompt="and to Woolworths ?",
        expected="8",
    ),
    ConversationBenchmarkCase(
        id="qf4_005_last_month_woolworths_total",
        prompt="and what's the total amount we spent at Woolworths that month",
        expected="370.46",
    ),
]


def normalize_numeric_answer(value: str) -> Decimal | None:
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?", value)
    if match is None:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def run_case(benchmark: BenchmarkClient, case: BenchmarkCase) -> dict[str, Any]:
    try:
        response = benchmark.query(case.prompt)
    except Exception as exc:
        return {
            "id": case.id,
            "prompt": case.prompt,
            "expected": case.expected,
            "actual": None,
            "passed": False,
            "error": str(exc),
            "agent_response": None,
        }

    actual = response.content.strip()
    expected_number = normalize_numeric_answer(case.expected)
    actual_number = normalize_numeric_answer(actual)
    return {
        "id": case.id,
        "prompt": case.prompt,
        "expected": case.expected,
        "actual": actual,
        "passed": actual_number == expected_number,
        "agent_response": response.model_dump(),
    }


def evaluate_response(
    *,
    case: BenchmarkCase,
    actual: str | None,
    agent_response: dict[str, Any] | None,
    error: str | None = None,
) -> dict[str, Any]:
    actual_number = normalize_numeric_answer(actual or "")
    expected_number = normalize_numeric_answer(case.expected)
    return {
        "id": case.id,
        "prompt": case.prompt,
        "expected": case.expected,
        "actual": actual,
        "passed": actual_number == expected_number,
        "error": error,
        "agent_response": agent_response,
    }


def load_existing_results() -> dict[str, Any]:
    if not RESULTS_PATH.exists():
        return {}
    try:
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_results(results: dict[str, Any]) -> None:
    RESULTS_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )


def qf_result_template(*, model: str, total: int) -> dict[str, Any]:
    return {
        "test_cases_passed": 0,
        "test_cases_total": total,
        "model": model,
        "details": [],
    }


def run_qf1(
    *,
    benchmark: BenchmarkClient,
    results: dict[str, Any],
    model: str,
) -> None:
    results["QF-1"] = qf_result_template(model=model, total=len(QF1_CASES))

    for case in QF1_CASES:
        case_result = run_case(benchmark, case)
        results["QF-1"]["details"].append(case_result)
        if case_result["passed"]:
            results["QF-1"]["test_cases_passed"] += 1
        write_results(results)
        time.sleep(SLEEP_SECONDS_BETWEEN_QUERIES)


def run_qf4(
    *,
    benchmark: BenchmarkClient,
    results: dict[str, Any],
    model: str,
) -> None:
    results["QF-4"] = qf_result_template(model=model, total=len(QF4_CASES))
    response = None

    for case in QF4_CASES:
        try:
            if case.is_follow_up and response is None:
                raise RuntimeError("cannot run follow-up before conversation starts")
            response = (
                response.follow_up(case.prompt)
                if case.is_follow_up and response is not None
                else benchmark.query(case.prompt)
            )
            case_result = evaluate_response(
                case=case,
                actual=response.content.strip(),
                agent_response=response.model_dump(),
            )
        except Exception as exc:
            case_result = evaluate_response(
                case=case,
                actual=None,
                agent_response=None,
                error=str(exc),
            )

        results["QF-4"]["details"].append(case_result)
        if case_result["passed"]:
            results["QF-4"]["test_cases_passed"] += 1
        write_results(results)
        time.sleep(SLEEP_SECONDS_BETWEEN_QUERIES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Kirana agent benchmarks.")
    parser.add_argument("--QF1", action="store_true", help="Run QF1 benchmarks.")
    parser.add_argument("--QF4", action="store_true", help="Run QF4 benchmarks.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run every benchmark family currently defined in this file.",
    )
    return parser.parse_args()


def selected_query_families(args: argparse.Namespace) -> list[str]:
    if args.all:
        return ["QF-1", "QF-4"]
    selected = []
    if args.QF1:
        selected.append("QF-1")
    if args.QF4:
        selected.append("QF-4")
    return selected or ["QF-1"]


def main() -> int:
    args = parse_args()
    cfg = load_config("config.toml")
    model = cfg.kirana.available_models[0]
    results = load_existing_results()
    query_families = selected_query_families(args)

    with BenchmarkClient(base_url=BASE_URL, model=model) as benchmark:
        if "QF-1" in query_families:
            run_qf1(benchmark=benchmark, results=results, model=model)
        if "QF-4" in query_families:
            run_qf4(benchmark=benchmark, results=results, model=model)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
