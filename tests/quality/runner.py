"""Runner for the Campbell AI response-quality suite.

Executes each case against the real service and scores the answer against the
expectations in `expectations.py`. It calls OpenAI, so it is opt-in: enable it with
``CAMPBELL_AI_QUALITY_SUITE=1`` under pytest, or run this module directly.

Direct run, from the repository root:

    python -m dotenv run -- python -m tests.quality.runner --client cda

Options: ``--client``, ``--case`` (repeatable), ``--tag`` (repeatable),
``--report PATH`` to write the full JSON, ``--concurrency`` (default 3).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from src.campbell_ai.concurrency import ConcurrencyGuard
from src.campbell_ai.config import get_campbell_settings
from src.campbell_ai.service import CampbellAIService
from tests.quality.expectations import (
    BOLD_PATTERN,
    CASES,
    CASE_MAP,
    PERIOD_PATTERN,
    DataFacts,
    QualityCase,
    available_capabilities,
    date_variants,
    fold,
    partition_cases,
    question_placeholders,
    render_question,
    resolve_facts,
)


@dataclass
class CaseResult:
    case_id: str
    question: str
    passed: bool
    seconds: float
    failures: list[str] = field(default_factory=list)
    request_type: str = ""
    response: str = ""
    charts: list[str] = field(default_factory=list)
    facts: dict[str, str] = field(default_factory=dict)
    grounding: dict = field(default_factory=dict)
    error: str | None = None
    prior_turns: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "passed": self.passed,
            "seconds": round(self.seconds, 1),
            "failures": self.failures,
            "request_type": self.request_type,
            "charts": self.charts,
            "facts": self.facts,
            "grounding": self.grounding,
            "error": self.error,
            "response": self.response,
            "prior_turns": self.prior_turns,
        }


def _matches(haystack: str, needle) -> bool:
    """A string must appear; a tuple means any of its members may appear."""
    if isinstance(needle, tuple):
        return any(_matches(haystack, item) for item in needle)
    return fold(needle) in haystack


def _matches_fact(response: str, value: str) -> bool:
    """Compare integer facts across presentation formats without matching substrings."""
    if re.fullmatch(r"-?\d+\.\d+", value):
        normalized = value.rstrip("0").rstrip(".")
        if "." not in normalized and not normalized.startswith("-"):
            return _matches_fact(response, normalized)
        return bool(re.search(
            r"(?<![\w.,])" + re.escape(normalized).replace(r"\.", "[.,]")
            + r"0*(?![\w]|[.,]\d)", response,
        ))
    if re.fullmatch(r"\d+", value):
        grouped = f"{int(value):,}"
        variants = {value, grouped, grouped.replace(",", "."), grouped.replace(",", " ")}
        return bool(re.search(
            r"(?<![\w.,])(?:" + "|".join(re.escape(v) for v in variants)
            + r")(?:[.,]0+)?(?![\w]|[.,]\d)",
            response.replace("\u00a0", " ").replace("\u202f", " "),
        ))
    return _matches(response, date_variants(value))


def evaluate(
    case: QualityCase,
    response: str,
    request_type: str,
    charts: list[dict],
    facts: dict[str, str],
    grounding: dict | None = None,
) -> list[str]:
    """Return the list of expectation failures for one answer."""
    failures: list[str] = []
    folded = fold(response)

    if case.expect_request_type and request_type != case.expect_request_type:
        failures.append(
            f"request_type={request_type!r}, se esperaba {case.expect_request_type!r}"
        )

    for needle in case.must_include:
        if not _matches(folded, needle):
            failures.append(f"falta mencionar {needle!r}")

    for pattern in case.must_include_regex:
        if not re.search(pattern, folded):
            failures.append(f"no satisface el patrón {pattern!r}")

    for name, value in facts.items():
        if not value:
            failures.append(f"el dato esperado {name} vino vacío")
        elif not _matches_fact(folded, value):
            failures.append(f"no cita {name}={value!r}")

    for needle in case.must_not_include:
        if _matches(folded, needle):
            failures.append(f"no debería mencionar {needle!r}")
    for pattern in case.must_not_include_regex:
        if re.search(pattern, folded):
            failures.append(f"afirmación no permitida: {pattern!r}")

    if case.expect_bold and not BOLD_PATTERN.search(response):
        failures.append("sin negrita en los datos clave")

    if case.expect_period and not PERIOD_PATTERN.search(response):
        failures.append("no declara el periodo analizado")

    if case.expect_chart and not charts:
        failures.append("no generó ninguna figura")

    if case.expect_chart_ids:
        produced = {str(chart.get("chart_id", "")) for chart in charts}
        if not any(
            expected in identifier
            for expected in case.expect_chart_ids
            for identifier in produced
        ):
            failures.append(
                f"chart_id {sorted(produced)} no coincide con {list(case.expect_chart_ids)}"
            )

    if case.expect_grounded:
        report = grounding or {}
        unverified = report.get("unverified_numbers") or []
        units = report.get("invented_units") or []
        if unverified:
            failures.append(f"cifras sin origen en los datos: {unverified}")
        if units:
            failures.append(f"unidades de medida inventadas: {units}")
        if not report:
            failures.append("la respuesta no trae auditoría de trazabilidad")

    return failures


class QualityRunner:
    def __init__(self, client: str = "cda", username: str | None = None):
        self.service = CampbellAIService()
        self.client = client
        self.username = username or self._pick_username(client)
        self.facts = DataFacts(self.service.repository, client)

    @staticmethod
    def _pick_username(client: str) -> str:
        """First dashboard user authorized for this client, so the suite needs no secrets."""
        from config.users import USERS

        for username, user in USERS.items():
            allowed = {str(item).strip().lower() for item in user.get("clients", [])}
            if client.strip().lower() in allowed:
                return username
        raise RuntimeError(f"Ningun usuario del dashboard tiene acceso a {client}")

    async def run_case(self, case: QualityCase) -> CaseResult:
        started = time.time()
        prior_turns: list[dict[str, str]] = []
        try:
            # Placeholders in the question are resolved too, so a case can name a real unit
            # without hardcoding a machine code that may not exist next month.
            needed = tuple(
                dict.fromkeys(case.must_include_facts + question_placeholders(case.question))
            )
            facts = resolve_facts(self.facts, needed)
            question = render_question(case, facts)
            ancestors: list[QualityCase] = []
            seen = {case.case_id}
            parent_id = case.follow_up_of
            while parent_id:
                if parent_id in seen:
                    raise ValueError(f"Ciclo de follow-ups: {parent_id}")
                seen.add(parent_id)
                previous = CASE_MAP[parent_id]
                ancestors.append(previous)
                parent_id = previous.follow_up_of
        except Exception as exc:
            return CaseResult(
                case_id=case.case_id,
                question=case.question,
                passed=False,
                seconds=time.time() - started,
                error=f"no se pudo anclar el caso en los datos: {exc}",
            )

        try:
            session = await self.service.initialize(self.username, self.client)
            session_id = session.session_id
            # Replay the whole chain oldest-first, not just the immediate predecessor:
            # turn three otherwise receives a pronoun without the original entity.
            for previous in reversed(ancestors):
                previous_facts = resolve_facts(
                    self.facts, question_placeholders(previous.question)
                )
                previous_question = render_question(previous, previous_facts)
                previous_result = await self.service.send_message(
                    self.username,
                    self.client,
                    session_id,
                    previous_question,
                )
                prior_turns.append({"case_id": previous.case_id,
                                    "question": previous_question,
                                    "response": previous_result.response})
            result = await self.service.send_message(
                self.username, self.client, session_id, question
            )
        except Exception as exc:
            return CaseResult(
                case_id=case.case_id,
                question=question,
                passed=False,
                seconds=time.time() - started,
                error=f"{type(exc).__name__}: {exc}",
                facts=facts,
                prior_turns=prior_turns,
            )

        charts = [item.model_dump(mode="json") for item in result.visualizations]
        failures = evaluate(
            case,
            result.response,
            result.request_type,
            charts,
            {name: facts[name] for name in case.must_include_facts},
            result.grounding,
        )
        return CaseResult(
            case_id=case.case_id,
            question=question,
            passed=not failures,
            seconds=time.time() - started,
            failures=failures,
            request_type=result.request_type,
            response=result.response,
            charts=[str(chart.get("chart_id", "")) for chart in charts],
            facts=facts,
            grounding=result.grounding,
            prior_turns=prior_turns,
        )

    def _admit_batch(self, concurrency: int) -> None:
        """Let the batch through the per-user admission cap.

        The service admits two simultaneous answers per user, which is right for a person
        with two tabs and wrong for this runner: every case runs as the same dashboard
        user, so a suite with `--concurrency 4` would see cases rejected as "busy" and
        scored as failures. The guard stays in place, resized to the requested batch, so a
        real bug in admission control still surfaces instead of being bypassed.
        """
        limits = self.service.concurrency.limits
        width = max(1, concurrency)
        self.service.concurrency = ConcurrencyGuard(
            replace(
                limits,
                max_concurrent=max(limits.max_concurrent, width),
                max_concurrent_per_user=max(limits.max_concurrent_per_user, width),
            )
        )

    async def run(
        self, cases: list[QualityCase], concurrency: int = 3
    ) -> list[CaseResult]:
        self._admit_batch(concurrency)
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def guarded(case: QualityCase) -> CaseResult:
            async with semaphore:
                result = await self.run_case(case)
                mark = "PASS" if result.passed else "FAIL"
                print(f"[{mark}] {result.case_id} ({result.seconds:.0f}s)", flush=True)
                for failure in result.failures:
                    print(f"        - {failure}", flush=True)
                if result.error:
                    print(f"        ! {result.error}", flush=True)
                return result

        return list(await asyncio.gather(*(guarded(case) for case in cases)))


def select_cases(case_ids: list[str], tags: list[str]) -> list[QualityCase]:
    selected = list(CASES)
    if case_ids:
        selected = [case for case in selected if case.case_id in set(case_ids)]
    if tags:
        wanted = set(tags)
        selected = [case for case in selected if wanted & set(case.tags)]
    # A follow-up replays its predecessor itself, so ordering does not matter.
    return selected


def summarize(
    results: list[CaseResult], not_applicable: list[tuple[QualityCase, str]] | None = None
) -> dict:
    """Score the run, keeping "not applicable" outside the pass rate.

    A case the client has no source for is not evidence about the assistant, so counting it
    as passed would inflate the rate with untested behaviour - and counting it as failed would
    blame the assistant for a missing file. It is listed separately, with its reason.
    """
    passed = [item for item in results if item.passed]
    skipped = not_applicable or []
    return {
        "total": len(results),
        "passed": len(passed),
        "failed": len(results) - len(passed),
        "pass_rate": round(len(passed) / len(results) * 100, 1) if results else 0.0,
        "seconds": round(sum(item.seconds for item in results), 1),
        "not_applicable": [
            {"case_id": case.case_id, "question": case.question, "reason": reason}
            for case, reason in skipped
        ],
        "cases": [item.as_dict() for item in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", default="cda")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--report", default="")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY no configurada; la suite de calidad requiere el modelo real")
        return 2
    if not get_campbell_settings().internal_token:
        print("Aviso: CAMPBELL_AI_INTERNAL_TOKEN no configurado (no requerido en modo directo)")

    cases = select_cases(args.case, args.tag)
    if not cases:
        print("Ningun caso coincide con el filtro")
        return 2

    runner = QualityRunner(client=args.client)
    # A client without a source cannot answer the questions that need it. Those are reported
    # as not applicable instead of being sent and failing for a reason that says nothing
    # about the assistant.
    capabilities = available_capabilities(runner.service.repository, args.client)
    cases, not_applicable = partition_cases(cases, capabilities)
    for case, reason in not_applicable:
        print(f"  - {case.case_id}: NO APLICA · {reason}")
    if not cases:
        print("Ningun caso aplicable para este cliente")
        return 2

    print(f"Ejecutando {len(cases)} casos para {args.client.upper()} como {runner.username}\n")
    results = asyncio.run(runner.run(cases, concurrency=args.concurrency))
    summary = summarize(results, not_applicable)

    print()
    print(
        f"{summary['passed']}/{summary['total']} casos aprobados "
        f"({summary['pass_rate']}%) en {summary['seconds']}s"
    )
    if not_applicable:
        print(f"{len(not_applicable)} casos no aplicables para {args.client.upper()}")
    if args.report:
        Path(args.report).write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"Reporte completo en {args.report}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
