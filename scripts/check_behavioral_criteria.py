"""Refuse a golden behavioural criterion that nothing can fail.

R115. ``gold.behavioral`` froze two requirements -- ``refute_premise`` on Q08 and
Q16, ``counterview`` on seven more -- and no scoring code read either.
``false_premise_failed`` nominally covered the first by substring-matching
``gold.must_not_assert``, whose entries are prose behaviour descriptions, so it
could not return ``True`` on any input. R113 published ``0/30`` from it and
``docs/evaluation.md`` recorded both cases as "refuted".

The instance was one metric. The class is a behavioural requirement in the
frozen set with no evaluator, or with one that no report can fail. This guard
closes the class:

* a criterion required anywhere in the golden set and absent from
  ``data/behavioral_criteria.json`` fails the gate -- a new behavioural key
  cannot be added silently unenforced;
* the questions a criterion applies to are asserted in both directions against
  the frozen set, so the registry cannot drift from the data;
* an ``implemented`` criterion must have an evaluator and fixtures its evaluator
  *separates* -- at least one report it accepts and one it rejects, with the
  recorded verdict reproduced. AGENTS.md section 2 requires every acceptance
  criterion to be falsifiable by a deliberate wrong implementation; a criterion
  whose fixtures all fall on one side proves nothing;
* a ``deferred`` criterion must name a reason and an owning round, and their
  count is a ratchet that may only shrink.

``--self-test`` proves the guard itself bites, by running the two deliberate
wrong implementations -- always-satisfied and never-satisfied -- past the
fixture check and requiring both to be rejected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from deepresearch_agent.evaluation.behavioral import (  # noqa: E402
    BEHAVIORAL_EVALUATORS,
    BehavioralVerdict,
    asserts_false_premise,
    report_body,
)

REGISTRY_PATH = PROJECT_ROOT / "data" / "behavioral_criteria.json"
VALID_STATUSES = {"implemented", "deferred"}

Evaluator = Callable[[str, dict[str, Any]], BehavioralVerdict]


class CriteriaError(AssertionError):
    pass


def _load_questions(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    path = PROJECT_ROOT / str(registry["golden_set"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(item["id"]): item for item in payload["questions"]}


def required_criteria(questions: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Criteria the frozen golden set actually requires, and where."""

    required: dict[str, list[str]] = {}
    for qid, question in sorted(questions.items()):
        behavioral = question.get("gold", {}).get("behavioral", {})
        if not isinstance(behavioral, dict):
            continue
        for name, value in behavioral.items():
            if value is True:
                required.setdefault(str(name), []).append(qid)
    return required


def check_registry_covers_golden_set(
    registry: dict[str, Any], questions: dict[str, dict[str, Any]]
) -> list[str]:
    errors: list[str] = []
    criteria = registry["criteria"]
    required = required_criteria(questions)
    for name, qids in required.items():
        entry = criteria.get(name)
        if entry is None:
            errors.append(f"criterion {name} is required by {qids} and is not registered")
            continue
        registered = [str(item) for item in entry.get("questions", [])]
        if registered != qids:
            errors.append(f"criterion {name} registered for {registered}, golden set requires {qids}")
    for name in criteria:
        if name not in required:
            errors.append(f"criterion {name} is registered and no golden question requires it")
    return errors


def check_criterion_fixtures(
    name: str,
    entry: dict[str, Any],
    questions: dict[str, dict[str, Any]],
    evaluator: Evaluator,
) -> list[str]:
    """An implemented criterion must accept one report and reject another."""

    errors: list[str] = []
    fixtures = entry.get("discrimination", [])
    if not isinstance(fixtures, list) or not fixtures:
        return [f"criterion {name} is implemented with no discrimination fixtures"]
    outcomes: list[bool] = []
    outcomes_by_question: dict[str, list[bool]] = {}
    for fixture in fixtures:
        path = PROJECT_ROOT / str(fixture["fixture"])
        qid = str(fixture["question"])
        expected = bool(fixture["expected_satisfied"])
        if not path.exists():
            errors.append(f"criterion {name} fixture is missing: {fixture['fixture']}")
            continue
        if qid not in questions:
            errors.append(f"criterion {name} fixture names unknown question {qid}")
            continue
        verdict = evaluator(path.read_text(encoding="utf-8"), questions[qid]["gold"])
        outcomes.append(expected)
        outcomes_by_question.setdefault(qid, []).append(expected)
        if entry.get("require_real_discrimination") is True and not str(
            fixture.get("provenance", "")
        ).startswith("real "):
            errors.append(
                f"criterion {name} fixture {fixture['fixture']} is not a real-run artifact"
            )
        if verdict.satisfied is not expected:
            errors.append(
                f"criterion {name} fixture {fixture['fixture']} expected "
                f"satisfied={expected}, evaluator returned {verdict.satisfied} ({verdict.detail})"
            )
    if errors:
        return errors
    if not (any(outcomes) and not all(outcomes)):
        errors.append(
            f"criterion {name} fixtures do not separate it: every fixture expects "
            f"satisfied={outcomes[0] if outcomes else None}; a criterion needs one "
            "report it accepts and one it rejects"
        )
    if entry.get("require_real_discrimination") is True:
        for qid in entry.get("questions", []):
            question_outcomes = outcomes_by_question.get(str(qid), [])
            if not (any(question_outcomes) and not all(question_outcomes)):
                errors.append(
                    f"criterion {name} question {qid} needs real accepted and rejected reports"
                )
    return errors


def check_criteria(
    registry: dict[str, Any],
    questions: dict[str, dict[str, Any]],
    evaluators: dict[str, Evaluator],
) -> list[str]:
    errors = check_registry_covers_golden_set(registry, questions)
    deferred = 0
    for name, entry in sorted(registry["criteria"].items()):
        status = entry.get("status")
        if status not in VALID_STATUSES:
            errors.append(f"criterion {name} has unknown status {status!r}")
            continue
        if status == "deferred":
            deferred += 1
            if not str(entry.get("reason", "")).strip():
                errors.append(f"deferred criterion {name} must record why")
            if not str(entry.get("owner_round", "")).strip():
                errors.append(f"deferred criterion {name} must name the round that owns it")
            if name in evaluators:
                errors.append(
                    f"criterion {name} is deferred but an evaluator is registered; "
                    "mark it implemented and give it fixtures"
                )
            continue
        evaluator = evaluators.get(name)
        if evaluator is None:
            errors.append(f"criterion {name} is implemented with no evaluator in BEHAVIORAL_EVALUATORS")
            continue
        errors.extend(check_criterion_fixtures(name, entry, questions, evaluator))
    ratchet = int(registry["deferred_criteria_ratchet"])
    if deferred > ratchet:
        errors.append(f"deferred criteria {deferred} exceeds ratchet {ratchet}")
    return errors


def _self_test(registry: dict[str, Any], questions: dict[str, dict[str, Any]]) -> int:
    """Prove the guard rejects a deliberately wrong implementation."""

    implemented = sorted(
        name for name, entry in registry["criteria"].items() if entry.get("status") == "implemented"
    )
    failures = 0
    for label, satisfied in (("always_satisfied", True), ("never_satisfied", False)):
        def wrong(_report: str, _gold: dict[str, Any], _value: bool = satisfied) -> BehavioralVerdict:
            return BehavioralVerdict(criterion="wrong", satisfied=_value, detail=label)

        errors = check_criteria(registry, questions, {name: wrong for name in implemented})
        print(f"[self-test] {label}: {len(errors)} error(s)")
        for error in errors:
            print(f"[self-test]   {error}")
        if not errors:
            print(f"[self-test] FAIL: {label} was accepted", file=sys.stderr)
            failures += 1
    honest = check_criteria(registry, questions, BEHAVIORAL_EVALUATORS)
    print(f"[self-test] shipped evaluators: {len(honest)} error(s)")
    for error in honest:
        print(f"[self-test]   {error}")
    if honest:
        failures += 1
    print(f"behavioral_criteria_self_test={'PASS' if not failures else 'FAIL'} cases=3")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--proof-out", type=Path)
    args = parser.parse_args()

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    questions = _load_questions(registry)
    if args.self_test:
        return _self_test(registry, questions)

    errors = check_criteria(registry, questions, BEHAVIORAL_EVALUATORS)
    for error in errors:
        print(f"behavioral_criteria_error: {error}", file=sys.stderr)
    required = required_criteria(questions)
    implemented = sorted(
        name for name, entry in registry["criteria"].items() if entry.get("status") == "implemented"
    )
    deferred = sorted(
        name for name, entry in registry["criteria"].items() if entry.get("status") == "deferred"
    )
    print(
        f"behavioral_criteria={'PASS' if not errors else 'FAIL'} "
        f"required={len(required)} implemented={len(implemented)}{implemented} "
        f"deferred={len(deferred)}{deferred} "
        f"ratchet={registry['deferred_criteria_ratchet']}"
    )
    if args.proof_out is not None:
        cases: list[dict[str, Any]] = []
        for name, entry in sorted(registry["criteria"].items()):
            evaluator = BEHAVIORAL_EVALUATORS.get(name)
            if evaluator is None:
                continue
            for fixture in entry.get("discrimination", []):
                if not str(fixture.get("provenance", "")).startswith("real "):
                    continue
                path = PROJECT_ROOT / str(fixture["fixture"])
                report = path.read_text(encoding="utf-8")
                qid = str(fixture["question"])
                verdict = evaluator(report, questions[qid]["gold"])
                cases.append(
                    {
                        "criterion": name,
                        "question": qid,
                        "fixture": str(fixture["fixture"]),
                        "sha256": hashlib.sha256(report.encode()).hexdigest(),
                        "expected_satisfied": bool(fixture["expected_satisfied"]),
                        "satisfied": verdict.satisfied,
                        "asserts_false_premise": asserts_false_premise(report_body(report)),
                        "detail": verdict.detail,
                    }
                )
        accepted = [item for item in cases if item["expected_satisfied"]]
        rejected = [item for item in cases if not item["expected_satisfied"]]
        proof = {
            "round": 152,
            "source": "real registered report artifacts only",
            "metrics": {
                "registered_questions": len({item["question"] for item in cases}),
                "real_accepted_reports": len(accepted),
                "real_rejected_reports": len(rejected),
                "accepted_false_premise_assertions": sum(
                    bool(item["asserts_false_premise"]) for item in accepted
                ),
                "verdict_mismatches": sum(
                    item["satisfied"] is not item["expected_satisfied"] for item in cases
                ),
            },
            "cases": cases,
        }
        args.proof_out.parent.mkdir(parents=True, exist_ok=True)
        args.proof_out.write_text(
            json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"behavioral_criteria_proof={args.proof_out}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
