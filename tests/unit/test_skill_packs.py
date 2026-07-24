from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.settings import Settings
from deepresearch_agent.skills import (
    SKILL_LOAD_NODE_CONTRACT,
    SKILL_SELECTION_NODE_CONTRACT,
    SkillPackLoader,
    load_skills_if_enabled,
)
from deepresearch_agent.tools import CapabilityRegistry


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


if __name__ == "__main__":
    unittest.main()
