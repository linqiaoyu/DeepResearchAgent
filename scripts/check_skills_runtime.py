from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from deepresearch_agent.settings import Settings, project_root
from deepresearch_agent.skills import SkillPackLoader
from deepresearch_agent.trajectory import load_trajectory
from deepresearch_agent.trajectory_replay import replay_trajectory
from deepresearch_agent.workflow import DeepResearchEngine


FINANCE_TOPIC = "宁德时代 2024 年营收与归母净利润研究"
SKILL_NAME = "finance-metric-normalization"


def _settings(root: Path, *, enabled: bool, manifest: bool = False) -> Settings:
    return Settings(
        storage_path=root / "research.db",
        runs_root=root / "runs",
        skill_packs_enabled=enabled,
        trajectory_record_enabled=True,
        run_manifest_enabled=manifest,
        structured_logging_enabled=False,
        max_critic_iter=1,
    )


def _content_digest(skill_root: Path) -> str:
    digest = hashlib.sha256()
    digest.update((skill_root / "SKILL.md").read_bytes())
    for path in sorted((skill_root / "resources").iterdir()):
        if not path.is_file() or path.is_symlink():
            continue
        digest.update(b"\0")
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_incompatible_skill(root: Path) -> None:
    skill_root = root / SKILL_NAME
    resources = skill_root / "resources"
    resources.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\n"
        f"name: {SKILL_NAME}\n"
        "description: incompatible finance test pack\n"
        "version: 999.0.0\n"
        "harness_api_version: 999\n"
        "---\n",
        encoding="utf-8",
    )
    (resources / "capability.json").write_text("{}", encoding="utf-8")


def measure() -> dict[str, int | float]:
    with tempfile.TemporaryDirectory(prefix="skills-runtime-") as temp_dir:
        root = Path(temp_dir)
        enabled_root = root / "enabled"
        enabled_settings = _settings(enabled_root, enabled=True, manifest=True)
        with DeepResearchEngine(settings=enabled_settings) as enabled_engine:
            loaded_state = enabled_engine.run(topic=FINANCE_TOPIC, depth_level=1)
            metadata_reads = len(enabled_engine.skill_loader.metadata_reads)
            resource_reads = len(enabled_engine.skill_loader.resource_reads)

        skill_state = loaded_state.metadata["skill_packs"]
        loaded_entries = skill_state["loaded_skills"]
        manifest_path = (
            enabled_settings.runs_root
            / loaded_state.research_id
            / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_skills = manifest.get("skills", [])
        expected_digest = _content_digest(
            project_root() / "skills" / SKILL_NAME
        )
        manifest_coverage = sum(
            set(item) == {"name", "version", "content_sha256"}
            for item in manifest_skills
        ) / max(1, len(loaded_entries))
        manifest_content_matches = int(
            manifest_skills
            == [
                {
                    "name": SKILL_NAME,
                    "version": "1.0.0",
                    "content_sha256": expected_digest,
                }
            ]
        )

        trajectory_path = (
            enabled_settings.runs_root
            / loaded_state.research_id
            / "trajectory.json"
        )
        replay = replay_trajectory(
            load_trajectory(trajectory_path),
            mode="strict",
        )

        disabled_root = root / "disabled"
        disabled_settings = _settings(disabled_root, enabled=False)
        with DeepResearchEngine(settings=disabled_settings) as disabled_engine:
            disabled_state = disabled_engine.run(topic=FINANCE_TOPIC, depth_level=1)
            disabled_reads = (
                len(disabled_engine.skill_loader.metadata_reads)
                + len(disabled_engine.skill_loader.resource_reads)
            )

        default_root = root / "default"
        default_settings = Settings(
            storage_path=default_root / "research.db",
            runs_root=default_root / "runs",
            trajectory_record_enabled=True,
            run_manifest_enabled=False,
            structured_logging_enabled=False,
            max_critic_iter=1,
        )
        with DeepResearchEngine(settings=default_settings) as default_engine:
            default_state = default_engine.run(topic=FINANCE_TOPIC, depth_level=1)

        failed_root = root / "failed"
        bad_skills = failed_root / "bad-skills"
        _write_incompatible_skill(bad_skills)
        failed_settings = _settings(failed_root, enabled=True)
        with DeepResearchEngine(settings=failed_settings) as failed_engine:
            failed_engine.skill_loader = SkillPackLoader(bad_skills)
            failed_state = failed_engine.run(topic=FINANCE_TOPIC, depth_level=1)

        observed_states = {
            *skill_state["states"],
            *disabled_state.metadata["skill_packs"]["states"],
            *failed_state.metadata["skill_packs"]["states"],
        }
        return {
            "observable_skill_states": len(observed_states),
            "metadata_reads_when_enabled": metadata_reads,
            "resource_reads_when_loaded": resource_reads,
            "disabled_skill_reads": disabled_reads,
            "manifest_skill_coverage": manifest_coverage,
            "manifest_content_matches": manifest_content_matches,
            "recorded_skill_snapshot_present": int(
                "skill_packs" in load_trajectory(trajectory_path).request
            ),
            "recorded_strict_replay_match": float(
                replay.status == "reproduced"
                and replay.artifact_matches == {"report.md": True}
            ),
            "disabled_report_byte_match": float(
                disabled_state.final_report == default_state.final_report
            ),
            "failed_state_degradation_events": sum(
                item.get("tool") == "skill_packs"
                for item in failed_state.metadata.get("degradation_events", [])
            ),
            "failed_run_retained_report": int(bool(failed_state.final_report)),
        }


def validate(metrics: dict[str, int | float]) -> None:
    expected = {
        "observable_skill_states": 4,
        "metadata_reads_when_enabled": 1,
        "resource_reads_when_loaded": 2,
        "disabled_skill_reads": 0,
        "manifest_skill_coverage": 1.0,
        "manifest_content_matches": 1,
        "recorded_skill_snapshot_present": 1,
        "recorded_strict_replay_match": 1.0,
        "disabled_report_byte_match": 1.0,
        "failed_state_degradation_events": 1,
        "failed_run_retained_report": 1,
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
    print("skills_runtime_self_test=PASS cases=11")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
