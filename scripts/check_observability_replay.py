"""Prove H2 activity locators, tamper evidence, replay, and terminal audits."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from check_capability_observability import (
    ACTIVE,
    BYPASSED,
    DEGRADED,
    FAILED,
    LOCATORS,
    RAN,
    classify,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.trajectory import (
    LLMCallTrace,
    TrajectoryRecorder,
    TrajectoryTermination,
    load_trajectory,
    validate_strict_replay_trajectory,
    verify_trajectory_offline,
)
from deepresearch_agent.trajectory_replay import replay_trajectory
from deepresearch_agent.workflow import DeepResearchEngine


TECHNOLOGY_LOCATORS: dict[str, tuple[str, ...]] = {
    "orchestration": ("CONFIG_FAIL_FAST_ENABLED", "BRANCH_BUDGET_ENABLED"),
    "tool_use": ("TOOL_CONTRACT_ENABLED",),
    "tool_calling": ("LLM_TOOL_SELECTION_ENABLED",),
    "planning_replanning": ("RESEARCH_LOOP_ENABLED",),
    "rag": ("RAG_ENABLED", "RERANK_ENABLED"),
    "mcp": ("MCP_CLIENT_ENABLED",),
    "skills": ("SKILL_PACKS_ENABLED",),
    "memory": ("PRIOR_MEMORY_ENABLED", "PROCEDURAL_MEMORY_ENABLED"),
    "reflection": ("REFLECTION_ENABLED",),
    "content_security": ("INJECTION_GUARD_ENABLED",),
    "observability_replay": (
        "STRUCTURED_LOGGING_ENABLED",
        "TRAJECTORY_RECORD_ENABLED",
    ),
    "storage_backends": ("RUN_MANIFEST_ENABLED",),
}


def _settings(root: Path) -> Settings:
    return Settings(
        storage_path=root / "research.db",
        runs_root=root / "runs",
        trajectory_record_enabled=True,
        run_manifest_enabled=False,
        structured_logging_enabled=False,
        max_critic_iter=1,
    )


def _status_vocabulary() -> set[str]:
    state = {
        "metadata": {
            "component_activity": {
                "critic": {"completed": 1},
                "config_fail_fast": {"composed": 1},
                "reflector": {"bypassed": 1},
                "numeric_check": {"degraded": 1},
                "research_loop": {"failed": 1},
            }
        }
    }
    return {
        classify("CRITIC_ENABLED", state, None),
        classify("CONFIG_FAIL_FAST_ENABLED", state, None),
        classify("REFLECTION_ENABLED", state, None),
        classify("NUMERIC_CHECK_ENABLED", state, None),
        classify("RESEARCH_LOOP_ENABLED", state, None),
    }


def _terminal_recorder(status: str) -> TrajectoryRecorder:
    request: dict[str, Any] = {
        "topic": f"offline-{status}",
        "mode": "deterministic",
        "depth_level": 1,
    }
    artifacts: dict[str, str] = {}
    if status == "budget_exceeded":
        request["recorded_plan"] = {}
        artifacts["report.md"] = "partial report"
    recorder = TrajectoryRecorder(run_id=f"offline-{status}", request=request)
    recorder.finalize(
        manifest_ref=None,
        artifacts=artifacts,
        termination=TrajectoryTermination(
            status=status,
            phase="researching",
            error_type="OfflineProbe",
            error_message=f"{status} terminal probe",
        ),
    )
    return recorder


def measure() -> dict[str, int | float]:
    locator_count = sum(
        bool(flags) and all(flag in LOCATORS for flag in flags)
        for flags in TECHNOLOGY_LOCATORS.values()
    )
    expected_states = {RAN, ACTIVE, BYPASSED, DEGRADED, FAILED}

    with tempfile.TemporaryDirectory(prefix="observability-replay-") as temp_dir:
        root = Path(temp_dir)
        settings = _settings(root)
        with DeepResearchEngine(settings=settings) as engine:
            state = engine.run(
                topic="宁德时代 2024 年营业收入研究",
                depth_level=1,
            )
        trajectory = load_trajectory(
            settings.runs_root / state.research_id / "trajectory.json"
        )
        replay = replay_trajectory(trajectory, mode="strict")

        terminal_verifications = [
            verify_trajectory_offline(_terminal_recorder(status).trajectory)
            for status in ("failed", "budget_exceeded")
        ]

        omitted = trajectory.model_copy(deep=True)
        omitted.node_transitions.pop()
        omitted_call_rejected = 0
        try:
            verify_trajectory_offline(omitted)
        except ValueError:
            omitted_call_rejected = 1

        prompt = TrajectoryRecorder(
            run_id="prompt-drift",
            request={
                "topic": "prompt drift",
                "mode": "llm",
                "depth_level": 1,
                "recorded_plan": {},
            },
        )
        prompt.record_llm_call(
            LLMCallTrace(
                role="planner",
                prompt=[{"role": "user", "content": "original"}],
                response="{}",
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                latency_seconds=0,
                model="recorded",
                attempt=1,
            )
        )
        prompt.finalize(manifest_ref=None, artifacts={"report.md": "report"})
        drifted = prompt.trajectory.model_copy(deep=True)
        drifted.llm_calls[0].prompt[0]["content"] = "changed"
        prompt_drift_rejected = 0
        try:
            verify_trajectory_offline(drifted)
        except ValueError:
            prompt_drift_rejected = 1

        legacy = trajectory.model_copy(
            deep=True,
            update={"schema_version": 6, "trace_commitment": None},
        )
        validate_strict_replay_trajectory(legacy)

    return {
        "harness_technology_locator_coverage": locator_count
        / len(TECHNOLOGY_LOCATORS),
        "activity_status_vocabulary_coverage": len(
            _status_vocabulary() & expected_states
        )
        / len(expected_states),
        "completed_report_byte_match": float(
            replay.status == "reproduced"
            and replay.artifact_matches == {"report.md": True}
        ),
        "offline_terminal_verification_rate": sum(
            item.trace_commitment_verified
            and item.termination_status in {"failed", "budget_exceeded"}
            for item in terminal_verifications
        )
        / len(terminal_verifications),
        "omitted_call_rejected": omitted_call_rejected,
        "prompt_drift_rejected": prompt_drift_rejected,
        "legacy_v6_validation_compatible": 1,
    }


def evaluate(metrics: dict[str, int | float]) -> list[str]:
    expected = {
        "harness_technology_locator_coverage": 1.0,
        "activity_status_vocabulary_coverage": 1.0,
        "completed_report_byte_match": 1.0,
        "offline_terminal_verification_rate": 1.0,
        "omitted_call_rejected": 1,
        "prompt_drift_rejected": 1,
        "legacy_v6_validation_compatible": 1,
    }
    return [
        f"{name}: expected {target}, got {metrics.get(name)}"
        for name, target in expected.items()
        if metrics.get(name) != target
    ]


def _self_test(metrics: dict[str, int | float]) -> None:
    if evaluate(metrics):
        raise SystemExit("observability_replay_self_test=FAIL production probe dirty")
    cases = {
        "missing_locator": {
            **metrics,
            "harness_technology_locator_coverage": 11 / 12,
        },
        "report_drift": {**metrics, "completed_report_byte_match": 0.0},
        "unverified_terminal": {
            **metrics,
            "offline_terminal_verification_rate": 0.5,
        },
        "omitted_call": {**metrics, "omitted_call_rejected": 0},
        "prompt_drift": {**metrics, "prompt_drift_rejected": 0},
    }
    for label, broken in cases.items():
        if not evaluate(broken):
            raise SystemExit(f"observability_replay_self_test=FAIL accepted {label}")
    print(f"observability_replay_self_test=PASS cases={len(cases) + 1}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    metrics = measure()
    if args.self_test:
        _self_test(metrics)
    print(json.dumps(metrics, sort_keys=True))
    failures = evaluate(metrics)
    if failures:
        print("\n".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
