from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.skills import SkillPackLoader
from deepresearch_agent.tools import CapabilityRegistry
from deepresearch_agent.tools.calling_loop import (
    RecordedToolIntentProposer,
    ToolCallIntent,
    ToolCallingLoop,
)


def _write_skill(
    root: Path,
    name: str,
    *,
    capability_name: str,
    cost: str = "free",
    harness_api_version: str = "1",
) -> Path:
    skill_root = root / name
    resources = skill_root / "resources"
    resources.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: Test metadata for {name}.\n"
        "version: 1.0.0\n"
        f"harness_api_version: {harness_api_version}\n"
        "---\n",
        encoding="utf-8",
    )
    (resources / "payload.json").write_text('{"ok":true}\n', encoding="utf-8")
    (resources / "capability.json").write_text(
        json.dumps(
            {
                "name": capability_name,
                "applicable_subquestion_types": ["*"],
                "cost_level": cost,
                "has_side_effect": False,
                "tool_spec": {
                    "name": capability_name,
                    "version": "1",
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                    "timeout_s": 1.0,
                    "cost_class": cost,
                    "idempotent": True,
                    "has_side_effect": False,
                },
                "resource": "payload.json",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return skill_root


def _expect_rejection(action: Any, expected: str) -> int:
    try:
        action()
    except ValueError as exc:
        return int(expected in str(exc))
    return 0


def measure() -> dict[str, int | float]:
    with tempfile.TemporaryDirectory(prefix="skills-contract-") as temp_dir:
        base = Path(temp_dir)

        progressive_root = base / "progressive"
        _write_skill(
            progressive_root,
            "selected",
            capability_name="skill.selected",
        )
        _write_skill(
            progressive_root,
            "unselected",
            capability_name="skill.unselected",
        )
        progressive_loader = SkillPackLoader(progressive_root)
        progressive_registry = CapabilityRegistry()
        outcome = progressive_loader.load_for_context(
            "selected",
            registry=progressive_registry,
            state=ResearchState(topic="selected"),
            is_applicable=lambda metadata, _context: metadata.name == "selected",
        )
        metadata_count = len(progressive_loader.metadata_reads)
        metadata_first = int(
            metadata_count == 2
            and outcome.selected_skills == ("selected",)
        )
        unselected_reads = sum(
            path.parents[1].name == "unselected"
            for path in progressive_loader.resource_reads
        )

        incompatible_root = base / "incompatible"
        _write_skill(
            incompatible_root,
            "future",
            capability_name="skill.future",
            harness_api_version="999",
        )
        incompatible_loader = SkillPackLoader(incompatible_root)
        incompatible_rejected = _expect_rejection(
            incompatible_loader.discover,
            "Incompatible Skill harness API version",
        )
        incompatible_resource_reads = len(incompatible_loader.resource_reads)

        escape_root = base / "escape"
        escape_skill = _write_skill(
            escape_root,
            "escape",
            capability_name="skill.escape",
        )
        outside = base / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        os.symlink(outside, escape_skill / "resources" / "escape.txt")
        escape_loader = SkillPackLoader(escape_root)
        escape_rejected = _expect_rejection(
            lambda: escape_loader.load_for_context(
                "escape",
                registry=CapabilityRegistry(),
                state=ResearchState(topic="escape"),
                is_applicable=lambda _metadata, _context: True,
            ),
            "symlinks are forbidden",
        )

        conflict_root = base / "conflict"
        _write_skill(
            conflict_root,
            "first",
            capability_name="skill.collision",
        )
        _write_skill(
            conflict_root,
            "second",
            capability_name="skill.collision",
        )
        conflict_registry = CapabilityRegistry()
        conflict_loader = SkillPackLoader(conflict_root)
        conflict_rejected = _expect_rejection(
            lambda: conflict_loader.load_for_context(
                "all",
                registry=conflict_registry,
                state=ResearchState(topic="all"),
                is_applicable=lambda _metadata, _context: True,
            ),
            "Skill capability collision",
        )

        paid_root = base / "paid"
        _write_skill(
            paid_root,
            "paid",
            capability_name="skill.paid",
            cost="high",
        )
        paid_registry = CapabilityRegistry()
        paid_loader = SkillPackLoader(paid_root)
        paid_loader.load_for_context(
            "paid",
            registry=paid_registry,
            state=ResearchState(topic="paid"),
            is_applicable=lambda _metadata, _context: True,
        )
        paid_metadata = paid_registry.get("skill.paid")
        loop_result = ToolCallingLoop(
            paid_registry,
            RecordedToolIntentProposer(
                [[ToolCallIntent(call_id="skill-1", name="skill.paid")]]
            ),
        ).run([{"role": "user", "content": "load"}])

        return {
            "metadata_first_read_rate": float(metadata_first),
            "unselected_resource_reads": unselected_reads,
            "path_escape_rejection_rate": float(escape_rejected),
            "version_incompatibility_rejection_rate": float(incompatible_rejected),
            "incompatible_resource_reads": incompatible_resource_reads,
            "capability_conflict_rejection_rate": float(conflict_rejected),
            "partial_registrations_after_conflict": len(conflict_registry.query()),
            "skill_tool_spec_match_rate": float(
                paid_metadata.name == paid_metadata.tool_spec.name
                and paid_metadata.cost_level == paid_metadata.tool_spec.cost_class
            ),
            "unauthorized_skill_executions": loop_result.executed_calls,
        }


def validate(metrics: dict[str, int | float]) -> None:
    expected = {
        "metadata_first_read_rate": 1.0,
        "unselected_resource_reads": 0,
        "path_escape_rejection_rate": 1.0,
        "version_incompatibility_rejection_rate": 1.0,
        "incompatible_resource_reads": 0,
        "capability_conflict_rejection_rate": 1.0,
        "partial_registrations_after_conflict": 0,
        "skill_tool_spec_match_rate": 1.0,
        "unauthorized_skill_executions": 0,
    }
    failures = [
        f"{name}: expected {target!r}, got {metrics.get(name)!r}"
        for name, target in expected.items()
        if metrics.get(name) != target
    ]
    if failures:
        raise AssertionError("; ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.self_test:
        parser.error("--self-test is required")
    metrics = measure()
    validate(metrics)
    for name, value in sorted(metrics.items()):
        print(f"{name}={value}")
    print("skills_contract_self_test=PASS cases=9")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
