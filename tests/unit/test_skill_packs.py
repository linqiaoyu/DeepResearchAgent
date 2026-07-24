from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.agents import CriticAgent
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.settings import Settings
from deepresearch_agent.skills import (
    FINANCE_METRIC_SKILL_NAME,
    SKILL_LOAD_NODE_CONTRACT,
    SKILL_SELECTION_NODE_CONTRACT,
    SkillPackLoader,
    finance_metric_resource_path,
    load_skills_if_enabled,
)
from deepresearch_agent.tools import CapabilityRegistry
from deepresearch_agent.workflow import DeepResearchEngine

ROOT = Path(__file__).resolve().parents[2]
MIGRATED_RULE_SHA256 = (
    "8e69cf6ce69201f803ae9cafcad5b74bab841be5b313f6edbcdc2f7d0e153baf"
)


def _write_demo_skill(root: Path) -> Path:
    skill_root = root / "demo-rules"
    resources = skill_root / "resources"
    resources.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\n"
        "name: demo-rules\n"
        "description: Use for demo numeric normalization research.\n"
        "---\n"
        "\n"
        "# Demo rules\n"
        "\n"
        "Load `resources/rules.json` only after selection.\n",
        encoding="utf-8",
    )
    (resources / "rules.json").write_text(
        '{"aliases":{"demo":"normalized"}}\n',
        encoding="utf-8",
    )
    (resources / "capability.json").write_text(
        json.dumps(
            {
                "name": "skill.demo.rules",
                "applicable_subquestion_types": ["financial_metric"],
                "cost_level": "free",
                "has_side_effect": False,
                "tool_spec": {
                    "name": "skill.demo.rules",
                    "version": "1",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "resource": {"type": "string"}
                        },
                        "additionalProperties": False,
                    },
                    "output_schema": {"type": "object"},
                    "timeout_s": 1.0,
                    "cost_class": "free",
                    "idempotent": True,
                    "has_side_effect": False,
                },
                "resource": "rules.json",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return skill_root


class SkillPackProgressiveDisclosureTest(unittest.TestCase):
    def test_not_applicable_reads_metadata_but_no_resources(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="deepresearch-skills-"
        ) as temp_dir:
            root = Path(temp_dir)
            _write_demo_skill(root)
            loader = SkillPackLoader(root)
            registry = CapabilityRegistry()
            state = ResearchState(topic="competitive landscape")

            outcome = loader.load_for_context(
                state.topic,
                registry=registry,
                state=state,
                is_applicable=lambda _metadata, _context: False,
            )

        self.assertEqual(("demo-rules",), tuple(
            path.parent.name for path in loader.metadata_reads
        ))
        self.assertEqual([], loader.resource_reads)
        self.assertEqual((), outcome.loaded_skills)
        self.assertEqual([], registry.query())
        self.assertEqual(
            "skill_selection",
            state.agent_decisions[-1].decision_type,
        )
        self.assertEqual(
            0,
            state.agent_decisions[-1].inputs[
                "resource_reads_before_selection"
            ],
        )

    def test_applicable_loads_resources_registers_and_records_decisions(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="deepresearch-skills-"
        ) as temp_dir:
            root = Path(temp_dir)
            _write_demo_skill(root)
            loader = SkillPackLoader(root)
            registry = CapabilityRegistry()
            state = ResearchState(topic="demo numeric research")

            outcome = loader.load_for_context(
                state.topic,
                registry=registry,
                state=state,
                is_applicable=lambda metadata, context: (
                    "numeric" in metadata.description
                    and "numeric" in context
                ),
            )

        self.assertEqual(("demo-rules",), outcome.selected_skills)
        self.assertEqual(
            ("skill.demo.rules",),
            outcome.registered_capabilities,
        )
        self.assertEqual(2, len(loader.resource_reads))
        implementation = registry.resolve("skill.demo.rules")
        self.assertEqual(
            {"aliases": {"demo": "normalized"}},
            implementation.resource_json(),
        )
        self.assertEqual(
            ["skill_selection", "skill_load"],
            [item.decision_type for item in state.agent_decisions],
        )
        self.assertTrue(SKILL_SELECTION_NODE_CONTRACT.decision_node)
        self.assertTrue(SKILL_LOAD_NODE_CONTRACT.decision_node)

    def test_disabled_switch_does_not_even_read_metadata(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="deepresearch-skills-"
        ) as temp_dir:
            root = Path(temp_dir)
            _write_demo_skill(root)
            loader = SkillPackLoader(root)
            registry = CapabilityRegistry()
            state = ResearchState(topic="demo numeric research")
            settings = Settings(storage_path=root / "research.db")

            outcome = load_skills_if_enabled(
                settings,
                loader,
                state.topic,
                registry=registry,
                state=state,
                is_applicable=lambda _metadata, _context: True,
            )

        self.assertFalse(settings.skill_packs_enabled)
        self.assertEqual([], loader.metadata_reads)
        self.assertEqual([], loader.resource_reads)
        self.assertEqual((), outcome.loaded_skills)
        self.assertEqual([], state.agent_decisions)


class FinanceMetricSkillMigrationTest(unittest.TestCase):
    def test_rule_bytes_match_pre_migration_sha256(self) -> None:
        migrated = finance_metric_resource_path()
        self.assertFalse(
            (ROOT / "data" / "finance_metric_normalization.json").exists()
        )
        self.assertEqual(
            MIGRATED_RULE_SHA256,
            hashlib.sha256(migrated.read_bytes()).hexdigest(),
        )
        self.assertEqual(1299, migrated.stat().st_size)

    def test_finance_topic_loads_same_rules_and_registers_capability(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="deepresearch-finance-skill-"
        ) as temp_dir:
            settings = Settings(
                storage_path=Path(temp_dir) / "research.db",
                runs_root=Path(temp_dir) / "runs",
                structured_logging_enabled=False,
                run_manifest_enabled=False,
                max_critic_iter=1,
                skill_packs_enabled=True,
            )
            engine = DeepResearchEngine(settings=settings)
            try:
                state = engine.run(
                    topic="宁德时代 2024 年营收与归母净利润研究",
                    depth_level=1,
                )
            finally:
                engine._checkpoint_conn.close()

        self.assertEqual(
            [FINANCE_METRIC_SKILL_NAME],
            state.metadata["skill_packs"]["selected_skills"],
        )
        self.assertEqual(
            ["skill.finance.metric_normalization"],
            state.metadata["skill_packs"][
                "registered_capabilities"
            ],
        )
        loaded = engine.capability_registry.resolve(
            "skill.finance.metric_normalization"
        )
        self.assertEqual(
            CriticAgent().metric_table,
            loaded.resource_json(),
        )
        skill_decisions = [
            item.decision_type
            for item in state.agent_decisions
            if item.decision_type.startswith("skill_")
        ]
        self.assertEqual(
            ["skill_selection", "skill_load"],
            skill_decisions,
        )
        self.assertIn("skill_selection", state.final_report or "")
        self.assertIn("skill_load", state.final_report or "")

    def test_non_financial_topic_does_not_load_resource(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="deepresearch-nonfinance-skill-"
        ) as temp_dir:
            settings = Settings(
                storage_path=Path(temp_dir) / "research.db",
                runs_root=Path(temp_dir) / "runs",
                structured_logging_enabled=False,
                run_manifest_enabled=False,
                max_critic_iter=1,
                skill_packs_enabled=True,
            )
            engine = DeepResearchEngine(settings=settings)
            try:
                state = engine.run(
                    topic="开源软件项目管理方法研究",
                    depth_level=1,
                )
            finally:
                engine._checkpoint_conn.close()

        self.assertEqual(
            [],
            state.metadata["skill_packs"]["selected_skills"],
        )
        self.assertEqual([], engine.skill_loader.resource_reads)
        self.assertEqual(
            ["skill_selection"],
            [
                item.decision_type
                for item in state.agent_decisions
                if item.decision_type.startswith("skill_")
            ],
        )
        self.assertNotIn(
            "skill.finance.metric_normalization",
            [item.name for item in engine.capability_registry.query()],
        )


if __name__ == "__main__":
    unittest.main()
