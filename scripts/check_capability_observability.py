"""Report, per declared capability, whether a run proves what it did.

R109 asked a simple question of an archived run -- did this capability actually
run? -- and answering it meant knowing which metadata key or artifact to look
in. Two of the answers I gave were wrong: the run manifest and the trajectory
are written under `runs/<research_id>/`, not into the state, so capabilities
that were plainly working were reported as unobservable.

That is the gap this closes. The locator table below is the harness's own
answer, in one place, checkable against a real run:

* ``state``    -- a key in `ResearchState.metadata` that only exists when the
                  capability did something.
* ``field``    -- a top-level `ResearchState` field. Structured output lives
                  here, not in metadata; the first version of this table
                  looked in the wrong place and reported a capability that
                  ran in all 24 archived runs as absent in all 24.
* ``activity`` -- a component in `metadata.component_activity`, which records
                  enabled/completed/bypassed and so distinguishes *ran* from
                  *was switched off*.
* ``artifact`` -- a file the capability writes under the run directory.
* ``None``     -- no per-run evidence exists. R110 measured 9 of 25 here;
                  R111 drove that to 0 by recording composition-time
                  capabilities as `composed`. A locator may return to
                  ``None`` only with the reason written down.

`--self-test` runs the table against a synthetic run so the gate exercises the
checker without depending on an archived artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deepresearch_agent.settings import boolean_setting_defaults  # noqa: E402


@dataclass(frozen=True)
class Locator:
    kind: str | None
    name: str | None = None


#: What proves a capability ran, for every flag the project declares.
LOCATORS: dict[str, Locator] = {
    "BRANCH_BUDGET_ENABLED": Locator("state", "branch_budget"),
    "CONFIG_FAIL_FAST_ENABLED": Locator("activity", "config_fail_fast"),
    "CONTEXT_PACKER_ENABLED": Locator("state", "context_events"),
    "CRITIC_ENABLED": Locator("activity", "critic"),
    "DECISION_WEAVING_ENABLED": Locator("state", "run_trace"),
    "DYNAMIC_CAPABILITY_ENABLED": Locator("state", "capability_selections"),
    "EXTRACTOR_ENABLED": Locator("activity", "extractor"),
    "INJECTION_GUARD_ENABLED": Locator("activity", "injection_guard"),
    "LLM_TOOL_SELECTION_ENABLED": Locator("state", "capability_selections"),
    "MCP_CLIENT_ENABLED": Locator("state", "mcp_registration"),
    "NUMERIC_CHECK_ENABLED": Locator("activity", "numeric_check"),
    "PRIOR_MEMORY_ENABLED": Locator("activity", "episodic_memory"),
    "PROCEDURAL_MEMORY_ENABLED": Locator("activity", "procedural_memory_read"),
    "PROGRESSIVE_DELIVERY_ENABLED": Locator("activity", "progressive_delivery"),
    "RAG_ENABLED": Locator("state", "provider_fidelity"),
    "REFLECTION_ENABLED": Locator("activity", "reflector"),
    "RERANK_ENABLED": Locator("activity", "rerank"),
    "RERANK_FAIL_OPEN": Locator("activity", "rerank_fail_open"),
    "RESEARCH_LOOP_ENABLED": Locator("activity", "research_loop"),
    "RUN_MANIFEST_ENABLED": Locator("artifact", "manifest.json"),
    "SEMANTIC_JUDGE_ENABLED": Locator("state", "semantic_judge"),
    "SKILL_PACKS_ENABLED": Locator("state", "skill_packs"),
    "STRUCTURED_LOGGING_ENABLED": Locator("activity", "structured_logging"),
    "STRUCTURED_OUTPUT_ENABLED": Locator("field", "structured_output"),
    "TOOL_CONTRACT_ENABLED": Locator("activity", "tool_contract"),
    "TRAJECTORY_RECORD_ENABLED": Locator("artifact", "trajectory.json"),
}

#: R111: `active` is what a composition-time capability can honestly claim.
#: It was wired into the run; it has no unit of work to have completed.
ACTIVE = "active"
RAN = "ran"
BYPASSED = "bypassed"
ABSENT = "absent"
UNPROVABLE = "unprovable"


class ObservabilityError(AssertionError):
    pass


def classify(
    flag: str,
    state: dict,
    run_directory: Path | None,
) -> str:
    """What this one run proves about this one capability."""

    locator = LOCATORS.get(flag)
    if locator is None:
        raise ObservabilityError(f"no locator declared for {flag}")
    if locator.kind is None:
        return UNPROVABLE
    metadata = state.get("metadata") or {}
    if locator.kind == "state":
        value = metadata.get(locator.name)
        return RAN if value else ABSENT
    if locator.kind == "field":
        return RAN if state.get(locator.name) else ABSENT
    if locator.kind == "activity":
        row = (metadata.get("component_activity") or {}).get(locator.name)
        if not row:
            return ABSENT
        if row.get("completed"):
            return RAN
        if row.get("composed"):
            return ACTIVE
        return BYPASSED if row.get("bypassed") else ABSENT
    if locator.kind == "artifact":
        if run_directory is None:
            return ABSENT
        return RAN if (run_directory / locator.name).is_file() else ABSENT
    raise ObservabilityError(f"unknown locator kind {locator.kind!r} for {flag}")


def report(state: dict, run_directory: Path | None) -> dict[str, str]:
    return {flag: classify(flag, state, run_directory) for flag in sorted(LOCATORS)}


def validate_locator_table() -> None:
    """Every declared flag needs an answer, even if the answer is `unprovable`."""

    declared = set(boolean_setting_defaults())
    missing = sorted(declared - set(LOCATORS))
    extra = sorted(set(LOCATORS) - declared)
    if missing:
        raise ObservabilityError(f"flags with no locator: {missing}")
    if extra:
        raise ObservabilityError(f"locators naming no flag: {extra}")


def _sample_state() -> dict:
    return {
        "metadata": {
            "branch_budget": {"unit": "search_calls"},
            "context_events": [{"node": "reporter"}],
            "run_trace": {"agent_decisions": []},
            "capability_selections": {"q": {}},
            "semantic_judge": {"status": "scored"},
            "skill_packs": {"selection_complete": True},
            "provider_fidelity": {"search": "real"},
            "component_activity": {
                "critic": {"enabled": True, "completed": 2, "bypassed": 0},
                "extractor": {"enabled": True, "completed": 1, "bypassed": 0},
                "reflector": {"enabled": False, "completed": 0, "bypassed": 1},
                "episodic_memory": {"enabled": False, "completed": 0, "bypassed": 1},
                "procedural_memory_read": {
                    "enabled": False,
                    "completed": 0,
                    "bypassed": 1,
                },
                # Composition-time: wired in, with nothing to have completed.
                "tool_contract": {"enabled": True, "completed": 0, "composed": 1},
                "config_fail_fast": {"enabled": True, "completed": 0, "composed": 1},
                "rerank": {"enabled": False, "completed": 0, "bypassed": 1},
            },
        },
        # Top level, not metadata: the distinction the `field` kind exists for.
        "structured_output": {"comparison_table": {}},
    }


def self_test() -> None:
    validate_locator_table()
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        run_directory = Path(tmp)
        (run_directory / "manifest.json").write_text("{}", encoding="utf-8")
        observed = report(_sample_state(), run_directory)

    expected = {
        "CRITIC_ENABLED": RAN,
        "REFLECTION_ENABLED": BYPASSED,
        "RUN_MANIFEST_ENABLED": RAN,
        "TRAJECTORY_RECORD_ENABLED": ABSENT,
        "CONFIG_FAIL_FAST_ENABLED": ACTIVE,
        "TOOL_CONTRACT_ENABLED": ACTIVE,
        "RERANK_ENABLED": BYPASSED,
        "BRANCH_BUDGET_ENABLED": RAN,
        "STRUCTURED_OUTPUT_ENABLED": RAN,
    }
    for flag, want in expected.items():
        if observed[flag] != want:
            raise ObservabilityError(
                f"self-test: {flag} expected {want}, got {observed[flag]}"
            )
    empty = report({"metadata": {}}, None)
    if empty["CRITIC_ENABLED"] != ABSENT:
        raise ObservabilityError("self-test: an empty run must prove nothing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--state", type=Path)
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    args = parser.parse_args()
    try:
        self_test()
        if args.self_test:
            print("capability_observability=PASS self-test")
            return 0
        if not args.state:
            parser.error("choose --self-test or --state")
        state = json.loads(args.state.read_text(encoding="utf-8"))
        run_directory = args.runs_root / str(state.get("research_id", ""))
        rows = report(state, run_directory if run_directory.is_dir() else None)
    except ObservabilityError as exc:
        print(f"capability_observability=FAIL {exc}", file=sys.stderr)
        return 1
    counts: dict[str, int] = {}
    for status in rows.values():
        counts[status] = counts.get(status, 0) + 1
    for flag, status in rows.items():
        print(f"{flag:32s} {status}")
    print(
        "capability_observability="
        + " ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
