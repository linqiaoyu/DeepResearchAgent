"""Make an unfinished capability expire instead of resting.

R125.  Every enforcement surface this repository had was shaped the same way:
``import_sites`` 不得增加, 字面量棘轮只减不增, deferred 计数只减不增, 未登记
skip 即失败, ``tracked_files_unchanged``.  All of them refuse a step backwards.
Not one of them requires a step forward.

The result is visible in the shipped defaults.  Seven content-affecting
capabilities -- RAG, the MCP client, skill packs, the research loop, reflection,
procedural and prior memory -- are implemented, documented, tested, and off.
A capability can sit at ``default=false`` for a hundred rounds while the full
gate stays green every single time, because nothing in the gate can tell the
difference between "not yet proven" and "abandoned".

So this guard gives every unproven capability an expiry.  Each
content-affecting flag that ships ``false`` must be registered with:

* ``graduation_criterion`` -- a quantified claim, not a description.  §2 already
  requires acceptance to be "可用一条命令跑出的数字"; the same standard applies to
  the claim that would justify turning the capability on.
* ``measured_by`` -- the command that produces that number.  Its script must
  exist on disk, so a criterion cannot cite a measurement nobody wrote.
* ``decision_round`` -- the round by which the capability must be resolved.
  Once that round is published, this check goes red until somebody resolves it.

Resolution means one of four things, and "keep waiting" is deliberately not
among them:

* ``graduated`` -- the default flipped to ``true``,
* ``removed`` -- the implementation was deleted, and the flag with it,
* ``opt_in`` -- ``false`` is the *correct* default (an outbound dependency, a
  security posture, a pack the operator supplies), which requires a stated
  design reason **and** a recorded proof that the capability works when turned
  on.  This exists because forcing every flag to default-true would be its own
  dishonesty, and it is not a free exit: without the proof it fails like
  anything else, which is what stops it becoming the universal escape hatch.
* one more deferral, of which each capability gets ``MAX_DEFERRALS`` and no
  more, each carrying the round and the reason.

The deferral cap is a constant in this file rather than a number in the
registry, precisely so that raising it is an edit to a guard under review and
not a data change that reads as bookkeeping.  When a capability's deferrals run
out, the only remaining moves are to prove it or to delete it.  That is the
point: a project is allowed to postpone a decision, and is not allowed to
postpone it forever.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deepresearch_agent.provenance.manifest import FLAG_CLASSIFICATIONS  # noqa: E402
from deepresearch_agent.settings import boolean_setting_defaults  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "data/capability_graduation.json"
DECISIONS_DIR = ROOT / "docs/decisions"

#: Each capability may be postponed this many times. Not configurable by data.
MAX_DEFERRALS = 2
DEFERRAL_ROUNDS = 4

VALID_STATUSES = {"pending", "graduated", "removed", "opt_in"}
#: Statuses that still describe a flag shipping false, and so must match reality.
OFF_STATUSES = {"pending", "opt_in"}

#: A criterion must carry a number and a comparison, the way §2 requires.
_QUANTIFIED = re.compile(r"[<>≥≤=]\s*-?\d|\d+\s*(?:/|之|个|条|题)|\d+(?:\.\d+)?%")


def last_published_round(decisions_dir: Path = DECISIONS_DIR) -> int:
    """The highest round with a published decision record.

    Deadlines are compared against this rather than against a date, because the
    unit of work in this repository is a round and nothing else advances.
    """

    rounds = [
        int(path.name)
        for path in decisions_dir.iterdir()
        if path.is_dir() and path.name.isdigit()
    ]
    return max(rounds, default=0)


def unproven_flags() -> set[str]:
    """Content-affecting capabilities that ship off."""

    defaults = boolean_setting_defaults()
    return {
        name
        for name, value in defaults.items()
        if value is False and FLAG_CLASSIFICATIONS.get(name) == "content_affecting"
    }


def _entry_failures(name: str, entry: Any, *, horizon: int) -> list[str]:
    failures: list[str] = []
    if not isinstance(entry, dict):
        return [f"{name}: registry entry must be an object"]

    status = entry.get("status")
    if status not in VALID_STATUSES:
        failures.append(f"{name}: status must be one of {sorted(VALID_STATUSES)}, got {status!r}")

    criterion = str(entry.get("graduation_criterion", ""))
    if not _QUANTIFIED.search(criterion):
        failures.append(
            f"{name}: graduation_criterion must state a number a command can produce, "
            f'not a description. Got: "{criterion[:70]}"'
        )

    measured_by = str(entry.get("measured_by", ""))
    if not measured_by:
        failures.append(f"{name}: measured_by must name the command that produces the number")
    else:
        referenced = re.findall(r"(scripts/[A-Za-z0-9_./]+\.py)", measured_by)
        if not referenced:
            failures.append(f"{name}: measured_by must name a scripts/*.py command, got {measured_by!r}")
        for script in referenced:
            if not (ROOT / script).exists():
                failures.append(f"{name}: measured_by cites {script}, which is not on disk")

    deferrals = entry.get("deferrals", [])
    if not isinstance(deferrals, list):
        failures.append(f"{name}: deferrals must be a list")
        deferrals = []
    for index, deferral in enumerate(deferrals):
        if not isinstance(deferral, dict) or not str(deferral.get("reason", "")).strip():
            failures.append(f"{name}: deferral #{index} must carry a non-empty reason")
        elif not isinstance(deferral.get("round"), int):
            failures.append(f"{name}: deferral #{index} must record the round that granted it")
    if len(deferrals) > MAX_DEFERRALS:
        failures.append(
            f"{name}: {len(deferrals)} deferrals granted, cap is {MAX_DEFERRALS}. "
            "Prove the capability or delete it -- the postponements are spent."
        )

    if status == "pending":
        initial_round = entry.get("initial_decision_round")
        decision_round = entry.get("decision_round")
        if not isinstance(initial_round, int):
            failures.append(f"{name}: initial_decision_round must be an integer")
        if not isinstance(decision_round, int):
            failures.append(f"{name}: decision_round must be an integer round number")
        elif isinstance(initial_round, int) and decision_round != initial_round + len(deferrals) * DEFERRAL_ROUNDS:
            failures.append(
                f"{name}: decision_round moved without the registered deferrals; expected "
                f"{initial_round + len(deferrals) * DEFERRAL_ROUNDS}, got {decision_round}"
            )
        elif decision_round <= horizon:
            remaining = MAX_DEFERRALS - len(deferrals)
            failures.append(
                f"{name}: decision_round={decision_round} has arrived (last published round "
                f"is {horizon}). Flip the default, delete the implementation, declare it "
                f"opt_in with a proof, or spend one of the {remaining} deferral(s) left "
                "with a recorded reason."
            )

    if status == "opt_in":
        # An opt-in default is a claim that false is right, not that the
        # capability is unfinished -- so it owes a reason and a working proof.
        if not str(entry.get("design_reason", "")).strip():
            failures.append(
                f"{name}: opt_in requires design_reason -- why false is the correct default, "
                "not merely the current one"
            )
        proof = entry.get("proof")
        if not isinstance(proof, dict):
            failures.append(f"{name}: opt_in requires proof{{round, command}} that it works when on")
        else:
            if not isinstance(proof.get("round"), int):
                failures.append(f"{name}: opt_in proof must cite the round that produced it")
            artifact = str(proof.get("artifact", ""))
            if not artifact.startswith("docs/decisions/") or not (ROOT / artifact).is_file():
                failures.append(
                    f"{name}: opt_in proof.artifact must name an existing published decision artifact"
                )
            command = str(proof.get("command", ""))
            scripts = re.findall(r"(scripts/[A-Za-z0-9_./]+\.py)", command)
            if not scripts:
                failures.append(f"{name}: opt_in proof.command must name a scripts/*.py command")
            for script in scripts:
                if not (ROOT / script).exists():
                    failures.append(f"{name}: opt_in proof cites {script}, which is not on disk")
    return failures


def evaluate(
    registry: dict[str, Any],
    observed: set[str],
    *,
    horizon: int,
) -> list[str]:
    """Bidirectional: an unregistered capability fails, and so does a stale entry."""

    failures: list[str] = []
    entries = registry.get("capabilities", {})
    if not isinstance(entries, dict):
        return ["registry: 'capabilities' must be an object keyed by flag name"]

    declared_off = {
        name for name, entry in entries.items()
        if isinstance(entry, dict) and entry.get("status") in OFF_STATUSES
    }
    for name in sorted(observed - declared_off):
        failures.append(
            f"unregistered capability: {name} ships content-affecting and false but has no "
            f"pending or opt_in entry in {REGISTRY_PATH.relative_to(ROOT)}. Register it with "
            "a quantified graduation criterion and the round it must be decided by."
        )
    for name in sorted(declared_off - observed):
        failures.append(
            f"stale entry: {name} is registered as still shipping false, but it no longer is. "
            "Mark it graduated or removed."
        )
    for name in sorted(set(entries) - declared_off):
        entry = entries[name]
        if isinstance(entry, dict) and entry.get("status") == "removed" and name in FLAG_CLASSIFICATIONS:
            failures.append(f"{name}: marked removed but the flag is still classified in the manifest")
    for name in sorted(entries):
        failures.extend(_entry_failures(name, entries[name], horizon=horizon))
    return failures


def _load(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _self_test() -> None:
    """Every failure mode must actually fail, including the deadline itself."""

    registry = _load()
    observed = unproven_flags()
    horizon = last_published_round()
    if evaluate(registry, observed, horizon=horizon):
        print("graduation_self_test=FAIL registry is not currently clean", file=sys.stderr)
        raise SystemExit(1)

    entries = registry["capabilities"]
    sample = next(name for name, entry in entries.items() if entry.get("status") == "pending")

    cases = {
        "unregistered": (
            {"capabilities": {k: v for k, v in entries.items() if k != sample}},
            observed,
            horizon,
            "unregistered capability",
        ),
        "stale": (registry, observed - {sample}, horizon, "stale entry"),
        "deadline_arrived": (
            {
                "capabilities": {
                    **entries,
                    sample: {
                        **entries[sample],
                        "initial_decision_round": horizon,
                        "decision_round": horizon,
                    },
                }
            },
            observed,
            horizon,
            "has arrived",
        ),
        "silent_deadline_move": (
            {
                "capabilities": {
                    **entries,
                    sample: {**entries[sample], "decision_round": entries[sample]["decision_round"] + 1},
                }
            },
            observed,
            horizon,
            "moved without the registered deferrals",
        ),
        "vague_criterion": (
            {
                "capabilities": {
                    **entries,
                    sample: {**entries[sample], "graduation_criterion": "已接线并可用"},
                }
            },
            observed,
            horizon,
            "must state a number",
        ),
        "missing_measurement": (
            {
                "capabilities": {
                    **entries,
                    sample: {**entries[sample], "measured_by": "scripts/does_not_exist.py"},
                }
            },
            observed,
            horizon,
            "not on disk",
        ),
        "deferrals_spent": (
            {
                "capabilities": {
                    **entries,
                    sample: {
                        **entries[sample],
                        "deferrals": [
                            {"round": 100 + index, "reason": "spent"}
                            for index in range(MAX_DEFERRALS + 1)
                        ],
                    },
                }
            },
            observed,
            horizon,
            "postponements are spent",
        ),
        # opt_in must not be a free exit: dropping either half of its evidence
        # has to fail, or a stuck capability could be relabelled into silence.
        "opt_in_without_reason": (
            {
                "capabilities": {
                    **entries,
                    sample: {
                        **entries[sample],
                        "status": "opt_in",
                        "proof": {"round": 125, "command": "scripts/run_demo.py"},
                    },
                }
            },
            observed,
            horizon,
            "requires design_reason",
        ),
        "opt_in_without_proof": (
            {
                "capabilities": {
                    **entries,
                    sample: {
                        **entries[sample],
                        "status": "opt_in",
                        "design_reason": "outbound dependency",
                    },
                }
            },
            observed,
            horizon,
            "requires proof",
        ),
    }
    for label, (broken, flags, cutoff, expected) in cases.items():
        failures = evaluate(broken, flags, horizon=cutoff)
        if not any(expected in line for line in failures):
            print(
                f"graduation_self_test=FAIL case={label} accepted; expected {expected!r}",
                file=sys.stderr,
            )
            raise SystemExit(1)

    print(f"graduation_self_test=PASS cases={len(cases)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()

    registry = _load()
    observed = unproven_flags()
    horizon = last_published_round()
    failures = evaluate(registry, observed, horizon=horizon)

    entries = registry.get("capabilities", {})
    pending = [name for name, entry in entries.items() if entry.get("status") == "pending"]
    spent = sum(len(entry.get("deferrals", [])) for entry in entries.values())
    print(
        f"pending_capabilities={len(pending)} last_published_round={horizon} "
        f"deferrals_spent={spent} deferrals_available={len(pending) * MAX_DEFERRALS - spent}"
    )
    for name in sorted(pending):
        entry = entries[name]
        left = MAX_DEFERRALS - len(entry.get("deferrals", []))
        print(f"  {name} decides_by={entry.get('decision_round')} deferrals_left={left}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
