from __future__ import annotations

import argparse
import json
import random
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

from chat.gateway import build_chat_model
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from utils.benchmarks import BenchmarkClient
from utils.config import load_config
from utils.types import Config

load_dotenv(Path(__file__).with_name(".env"))

BASE_URL = "http://127.0.0.1:8000"
RESULTS_PATH = Path(__file__).with_name(
    "kirana_agent_tools_and_instruction_following.json"
)
PROMPTS_DIR = Path(__file__).parent / "prompts"
TEST_IMAGES_DIR = Path(__file__).parent / "utils" / "benchmarks" / "test-images"
QF3_MIN_SLEEP_SECONDS = 30.0
QF3_MAX_SLEEP_SECONDS = 60.0


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    prompt: str
    expected: str


@dataclass(frozen=True)
class ConversationBenchmarkCase(BenchmarkCase):
    is_follow_up: bool = True


@dataclass(frozen=True)
class JudgedBenchmarkCase:
    id: str
    prompt: str
    expectation: str


@dataclass(frozen=True)
class ImageBenchmarkCase(BenchmarkCase):
    image_path: Path


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

IMAGE_PROMPT = (
    "Have I ever purchased something like this, only reply in a single word "
    "with a definitive yes or no"
)

QF2_CASES = [
    ImageBenchmarkCase(
        id="qf2_001_image_purchase_recall",
        prompt=IMAGE_PROMPT,
        expected="yes",
        image_path=TEST_IMAGES_DIR / "1.jpg",
    ),
    ImageBenchmarkCase(
        id="qf2_002_image_purchase_recall",
        prompt=IMAGE_PROMPT,
        expected="yes",
        image_path=TEST_IMAGES_DIR / "2.jpg",
    ),
    ImageBenchmarkCase(
        id="qf2_003_image_purchase_recall",
        prompt=IMAGE_PROMPT,
        expected="no",
        image_path=TEST_IMAGES_DIR / "3.jpg",
    ),
    ImageBenchmarkCase(
        id="qf2_004_image_purchase_recall",
        prompt=IMAGE_PROMPT,
        expected="no",
        image_path=TEST_IMAGES_DIR / "4.jpg",
    ),
    ImageBenchmarkCase(
        id="qf2_005_image_purchase_recall",
        prompt=IMAGE_PROMPT,
        expected="yes",
        image_path=TEST_IMAGES_DIR / "5.jpg",
    ),
]

QF3_CASES = [
    JudgedBenchmarkCase(
        id="qf3_001_april_18_receipts_and_contribution",
        prompt=(
            "How much did i spend on 18th April , can you list the receipts and "
            "the total amount spent"
        ),
        expectation="""Receipts on 18th April 2026
Household grocery spend (from receipts table):

Receipt ID Store Date Items Total ($)
25 THE FRUIT TEMPLE 2026-04-18 5 18.84
20 Woolworths 2026-04-18 12 75.64
Total household spend for 18th April: $94.48

Personal Contribution (Splitwise/accounting)
From me_expenses table (17th-18th April, accounting window):

Description Date Total ($) My Share ($)
Wooliez 2026-04-18 65.34 21.78
Veg 2026-04-18 18.84 6.28
Mints + tonic water 2026-04-18 5.30 0.00
Tim tam 2026-04-18 5.00 0.00
Accounting total for nearby entries: $94.48
My total contribution: $28.06

Reconciliation Notes
The household receipt total ($94.48) matches the sum of nearby Splitwise entries ($65.34 + $18.84 + $5.30 + $5.00 = $94.48) exactly.
The Woolworths receipt ($75.64) is split into two accounting rows: Wooliez ($65.34), Tim tam ($5.00), and Mints + tonic water ($5.30). The remaining $0.32 gap is within tolerance.
The THE FRUIT TEMPLE receipt ($18.84) matches the Veg accounting row ($18.84) exactly.
Reconciliation: Strong. All receipts are accounted for in Splitwise, and my share is $28.06.""",
    ),
    JudgedBenchmarkCase(
        id="qf3_002_march_fresh_veggies_trips",
        prompt="What were all the fresh veggies shopping trips in March",
        expectation="""Here are the fresh vegetables shopping trips in March 2026, identified using semantic vector search for "fresh vegetables shopping trips" and confirmed via SQL:

Date Store Items Total (AUD)
2026-03-18 Woolworths 17 $85.36
2026-03-18 THE FRUIT TEMPLE 6 $17.70
2026-03-20 Woolworths 10 $57.17
2026-03-20 THE FRUIT TEMPLE 6 $25.18
2026-03-24 Woolworths 7 $37.20
2026-03-25 THE FRUIT TEMPLE 2 $10.54
2026-03-28 THE FRUIT TEMPLE 5 $17.92
2026-03-31 Woolworths 18 $87.81
Household total for March fresh veggies trips: $338.88 (sum of all 8 receipts).""",
    )
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

JUDGE_SYSTEM_PROMPT = (
    "You are a pragmatic benchmark judge for a grocery finance QA agent. "
    "Pass answers that have the same gist as the expected answer and include the "
    "critical facts needed to answer the user's question, even if formatting, "
    "wording, table columns, or nonessential reconciliation details differ. "
    "Do not require every supporting row from the expected answer when the user did "
    "not explicitly ask for that supporting detail. Fail answers that miss or alter "
    "the main numeric answer, omit required receipts/trips, confuse household spend "
    "with personal spend, or invent unsupported facts. Reply with exactly YES if "
    "the response satisfies this rubric, or exactly NO otherwise. Do not include "
    "explanations, punctuation, or any other text."
)

JUDGE_USER_TEMPLATE = """Question:
{question}

Expected answer:
{expectation}

Agent response:
{actual}

Judge by the user's question first. The expected answer may contain extra
supporting reconciliation detail; treat that as helpful context, not mandatory
unless it is necessary to answer the question.

Does the agent response satisfy the expected answer's critical facts and gist?
Reply with exactly YES or NO."""


def normalize_numeric_answer(value: str) -> Decimal | None:
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?", value)
    if match is None:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def normalize_yes_no_answer(value: str) -> str | None:
    normalized = value.strip().lower()
    match = re.search(r"\b(yes|no)\b", normalized)
    return match.group(1) if match else None


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


def run_image_case(
    benchmark: BenchmarkClient, case: ImageBenchmarkCase
) -> dict[str, Any]:
    try:
        response = benchmark.query_image(case.prompt, case.image_path)
    except Exception as exc:
        return {
            "id": case.id,
            "prompt": case.prompt,
            "image_path": str(case.image_path),
            "expected": case.expected,
            "actual": None,
            "passed": False,
            "error": str(exc),
            "agent_response": None,
        }

    actual = response.content.strip()
    return {
        "id": case.id,
        "prompt": case.prompt,
        "image_path": str(case.image_path),
        "expected": case.expected,
        "actual": actual,
        "passed": normalize_yes_no_answer(actual)
        == normalize_yes_no_answer(case.expected),
        "error": None,
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


def extract_token_usage(message: Any) -> dict[str, int]:
    usage = getattr(message, "usage_metadata", None) or {}
    response_metadata = getattr(message, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage") or {}

    input_tokens = (
        usage.get("input_tokens")
        or token_usage.get("prompt_tokens")
        or token_usage.get("input_tokens")
        or 0
    )
    output_tokens = (
        usage.get("output_tokens")
        or token_usage.get("completion_tokens")
        or token_usage.get("output_tokens")
        or 0
    )
    total_tokens = (
        usage.get("total_tokens")
        or token_usage.get("total_tokens")
        or int(input_tokens) + int(output_tokens)
    )
    return {
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(total_tokens),
    }


def message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else str(content)


def judge_response(
    *,
    cfg: Config,
    judge_model_identifier: str,
    case: JudgedBenchmarkCase,
    actual: str,
) -> dict[str, Any]:
    judge_model = build_chat_model(judge_model_identifier, cfg)
    started_at = perf_counter()
    judge_message = judge_model.invoke(
        [
            SystemMessage(content=JUDGE_SYSTEM_PROMPT),
            HumanMessage(
                content=JUDGE_USER_TEMPLATE.format(
                    question=case.prompt,
                    expectation=case.expectation,
                    actual=actual,
                )
            ),
        ]
    )
    latency_seconds = round(perf_counter() - started_at, 3)
    raw_decision = message_text(judge_message).strip()
    normalized_decision = raw_decision.upper()
    passed = normalized_decision == "YES"
    judge_decision = (
        normalized_decision if normalized_decision in {"YES", "NO"} else raw_decision
    )
    return {
        "passed": passed,
        "judge_decision": judge_decision,
        "judge_raw_response": raw_decision,
        "judge_model": judge_model_identifier,
        "judge_telemetry": {
            "latency_seconds": latency_seconds,
            **extract_token_usage(judge_message),
        },
    }


def load_existing_results() -> dict[str, Any]:
    if not RESULTS_PATH.exists():
        return {}
    try:
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_results(results: dict[str, Any]) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )


def log_progress(message: str) -> None:
    print(message, flush=True)


def sleep_for_qf3_rate_limit(reason: str) -> None:
    sleep_seconds = random.uniform(QF3_MIN_SLEEP_SECONDS, QF3_MAX_SLEEP_SECONDS)
    log_progress(f"QF-3 rate-limit sleep before {reason}: {sleep_seconds:.1f}s")
    sleep(sleep_seconds)


def resolve_output_path(raw_path: str | None) -> Path:
    if raw_path is None:
        return RESULTS_PATH
    path = Path(raw_path)
    return path if path.is_absolute() else Path.cwd() / path


def resolve_system_prompt_path(raw_path: str) -> Path:
    path = Path(raw_path)
    candidates = (
        [path]
        if path.is_absolute()
        else [Path.cwd() / path, PROMPTS_DIR / path]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def read_system_prompt_override(prompt_path: Path | None) -> str | None:
    if prompt_path is None:
        return None
    if not prompt_path.exists():
        raise FileNotFoundError(f"system prompt override not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


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
    log_progress(f"\nRunning QF-1: {len(QF1_CASES)} test cases")

    for index, case in enumerate(QF1_CASES, start=1):
        log_progress(f"QF-1 {index}/{len(QF1_CASES)} running: {case.id}")
        case_result = run_case(benchmark, case)
        results["QF-1"]["details"].append(case_result)
        if case_result["passed"]:
            results["QF-1"]["test_cases_passed"] += 1
        write_results(results)
        status = "PASS" if case_result["passed"] else "FAIL"
        log_progress(
            f"QF-1 {index}/{len(QF1_CASES)} {status}: "
            f"actual={case_result['actual']!r}"
        )
        log_progress(f"Wrote results to {RESULTS_PATH}")

    log_progress(
        "Finished QF-1: "
        f"{results['QF-1']['test_cases_passed']}/{results['QF-1']['test_cases_total']} passed"
    )


def run_qf2(
    *,
    benchmark: BenchmarkClient,
    results: dict[str, Any],
    model: str,
) -> None:
    results["QF-2"] = qf_result_template(model=model, total=len(QF2_CASES))
    log_progress(f"\nRunning QF-2: {len(QF2_CASES)} image test cases")

    for index, case in enumerate(QF2_CASES, start=1):
        log_progress(
            f"QF-2 {index}/{len(QF2_CASES)} running: "
            f"{case.id} image={case.image_path.name}"
        )
        case_result = run_image_case(benchmark, case)
        results["QF-2"]["details"].append(case_result)
        if case_result["passed"]:
            results["QF-2"]["test_cases_passed"] += 1
        write_results(results)
        status = "PASS" if case_result["passed"] else "FAIL"
        log_progress(
            f"QF-2 {index}/{len(QF2_CASES)} {status}: "
            f"expected={case.expected!r} actual={case_result['actual']!r}"
        )
        if case_result.get("error"):
            log_progress(f"QF-2 {index}/{len(QF2_CASES)} error: {case_result['error']}")
        log_progress(f"Wrote results to {RESULTS_PATH}")

    log_progress(
        "Finished QF-2: "
        f"{results['QF-2']['test_cases_passed']}/{results['QF-2']['test_cases_total']} passed"
    )


def run_qf3(
    *,
    benchmark: BenchmarkClient,
    results: dict[str, Any],
    model: str,
    cfg: Config,
) -> None:
    judge_model_identifier = cfg.kirana.model_identifiers[model]
    results["QF-3"] = qf_result_template(model=model, total=len(QF3_CASES))
    results["QF-3"]["judge_model"] = judge_model_identifier
    log_progress(f"\nRunning QF-3: {len(QF3_CASES)} test cases")

    for index, case in enumerate(QF3_CASES, start=1):
        if index > 1:
            sleep_for_qf3_rate_limit("next case")
        log_progress(f"QF-3 {index}/{len(QF3_CASES)} running: {case.id}")
        try:
            response = benchmark.query(case.prompt)
        except Exception as exc:
            case_result = {
                "id": case.id,
                "prompt": case.prompt,
                "expectation": case.expectation,
                "actual": None,
                "passed": False,
                "judge": None,
                "error": str(exc),
                "agent_response": None,
            }
        else:
            actual = response.content.strip()
            agent_response = response.model_dump()
            try:
                sleep_for_qf3_rate_limit("judge call")
                judge_result = judge_response(
                    cfg=cfg,
                    judge_model_identifier=judge_model_identifier,
                    case=case,
                    actual=actual,
                )
                error = None
            except Exception as exc:
                judge_result = None
                error = f"judge failed: {exc}"
            case_result = {
                "id": case.id,
                "prompt": case.prompt,
                "expectation": case.expectation,
                "actual": actual,
                "passed": bool(judge_result and judge_result["passed"]),
                "judge": judge_result,
                "error": error,
                "agent_response": agent_response,
            }

        results["QF-3"]["details"].append(case_result)
        if case_result["passed"]:
            results["QF-3"]["test_cases_passed"] += 1
        write_results(results)
        status = "PASS" if case_result["passed"] else "FAIL"
        judge_decision = (case_result.get("judge") or {}).get("judge_decision")
        judge_suffix = f" judge={judge_decision}" if judge_decision else ""
        log_progress(f"QF-3 {index}/{len(QF3_CASES)} {status}:{judge_suffix}")
        if case_result.get("error"):
            log_progress(f"QF-3 {index}/{len(QF3_CASES)} error: {case_result['error']}")
        log_progress(f"Wrote results to {RESULTS_PATH}")

    log_progress(
        "Finished QF-3: "
        f"{results['QF-3']['test_cases_passed']}/{results['QF-3']['test_cases_total']} passed"
    )


def run_qf4(
    *,
    benchmark: BenchmarkClient,
    results: dict[str, Any],
    model: str,
) -> None:
    results["QF-4"] = qf_result_template(model=model, total=len(QF4_CASES))
    response = None
    log_progress(f"\nRunning QF-4: {len(QF4_CASES)} test cases")

    for index, case in enumerate(QF4_CASES, start=1):
        turn_type = "follow-up" if case.is_follow_up else "fresh query"
        log_progress(
            f"QF-4 {index}/{len(QF4_CASES)} running: {case.id} ({turn_type})"
        )
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
        status = "PASS" if case_result["passed"] else "FAIL"
        log_progress(
            f"QF-4 {index}/{len(QF4_CASES)} {status}: "
            f"actual={case_result['actual']!r}"
        )
        if case_result.get("error"):
            log_progress(f"QF-4 {index}/{len(QF4_CASES)} error: {case_result['error']}")
        log_progress(f"Wrote results to {RESULTS_PATH}")

    log_progress(
        "Finished QF-4: "
        f"{results['QF-4']['test_cases_passed']}/{results['QF-4']['test_cases_total']} passed"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Kirana agent benchmarks.")
    parser.add_argument("--QF1", action="store_true", help="Run QF1 benchmarks.")
    parser.add_argument("--QF2", action="store_true", help="Run QF2 image benchmarks.")
    parser.add_argument("--QF3", action="store_true", help="Run QF3 benchmarks.")
    parser.add_argument("--QF4", action="store_true", help="Run QF4 benchmarks.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run every benchmark family currently defined in this file.",
    )
    parser.add_argument(
        "--system_prompt",
        default=None,
        help=(
            "Use this prompt file as a per-request system prompt override while "
            "benchmarks run. The repo prompt file is not modified. Relative paths "
            "are resolved from the current directory, then app/prompts/."
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        help=(
            "Output JSON path. Defaults to "
            "app/kirana_agent_tools_and_instruction_following.json."
        ),
    )
    return parser.parse_args()


def selected_query_families(args: argparse.Namespace) -> list[str]:
    if args.all:
        return ["QF-1", "QF-2", "QF-3", "QF-4"]
    selected = []
    if args.QF1:
        selected.append("QF-1")
    if args.QF2:
        selected.append("QF-2")
    if args.QF3:
        selected.append("QF-3")
    if args.QF4:
        selected.append("QF-4")
    return selected or ["QF-1"]


def main() -> int:
    global RESULTS_PATH

    args = parse_args()
    RESULTS_PATH = resolve_output_path(args.out)
    prompt_override = (
        resolve_system_prompt_path(args.system_prompt) if args.system_prompt else None
    )
    system_prompt = read_system_prompt_override(prompt_override)
    cfg = load_config("config.toml")
    model = cfg.kirana.available_models[0]
    results = load_existing_results()
    query_families = selected_query_families(args)
    log_progress(
        f"Running benchmark families: {', '.join(query_families)} "
        f"with model={model}"
    )
    log_progress(f"Results file: {RESULTS_PATH}")
    if prompt_override is not None:
        log_progress(f"System prompt override sent per request: {prompt_override}")

    with BenchmarkClient(
        base_url=BASE_URL,
        model=model,
        system_prompt=system_prompt,
    ) as benchmark:
        if "QF-1" in query_families:
            run_qf1(benchmark=benchmark, results=results, model=model)
        if "QF-2" in query_families:
            run_qf2(benchmark=benchmark, results=results, model=model)
        if "QF-3" in query_families:
            run_qf3(benchmark=benchmark, results=results, model=model, cfg=cfg)
        if "QF-4" in query_families:
            run_qf4(benchmark=benchmark, results=results, model=model)

    log_progress("\nBenchmark run complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
