from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from deepresearch_agent.provenance import (
    FLAG_CLASSIFICATIONS,
    RunManifest,
    build_run_manifest,
    compare_manifests,
    format_manifest_comparison,
    settings_flag_snapshot,
    write_run_manifest,
)
from deepresearch_agent.provenance.manifest import _realness
from deepresearch_agent.llm_config import DEFAULT_LLM_CONFIG, RoleModelConfig
from deepresearch_agent.schemas import ResearchState, SearchRecord
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools.fixture_search import FixtureSearchTool
from deepresearch_agent.workflow import DeepResearchEngine


def manifest() -> RunManifest:
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    return RunManifest(
        run_id="run-1",
        started_at=now,
        ended_at=now,
        model_strings={"judge": "openai/qwen3.7-plus"},
        prompt_hashes={"judge.md": "abc"},
        retrieval_corpus_as_of=date(2026, 7, 9),
        evaluation_as_of=date(2026, 7, 9),
        config_hash="config-a",
        dependency_versions={"pydantic": "2.0"},
        domain="finance",
        mode="deterministic",
        flags={"RUN_MANIFEST_ENABLED": True},
        token_total=10,
        cost_cny_total=0.0,
    )


class RunManifestTests(unittest.TestCase):
    def test_retrieval_index_version_is_a_comparability_boundary(self) -> None:
        left = manifest().model_copy(update={"retrieval_index_version": "finance-v1"})
        right = manifest().model_copy(update={"retrieval_index_version": "finance-v2"})

        comparison = compare_manifests(left, right)

        self.assertFalse(comparison.comparable)
        self.assertIn("retrieval_index_version", comparison.incomparable_reasons)

    def test_realness_requires_explicit_fidelity_for_every_provider(self) -> None:
        self.assertEqual(_realness({}), "unknown")
        self.assertEqual(
            _realness({"search": "replay", "structured": "replay", "llm": "real"}),
            "mixed",
        )
        self.assertEqual(_realness({"search": "real", "llm": "unknown"}), "unknown")

    def test_default_settings_enable_manifest_and_record_all_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(storage_path=Path(tmp) / "research.db")
            built = build_run_manifest(
                ResearchState(topic="test"),
                settings,
                started_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
            )

        self.assertTrue(settings.run_manifest_enabled)
        self.assertEqual(
            built.flags,
            {
                "TOOL_CONTRACT_ENABLED": settings.tool_contract_enabled,
                "INJECTION_GUARD_ENABLED": settings.injection_guard_enabled,
                "RUN_MANIFEST_ENABLED": settings.run_manifest_enabled,
                "CONTEXT_PACKER_ENABLED": settings.context_packer_enabled,
                "STRUCTURED_LOGGING_ENABLED": settings.structured_logging_enabled,
                "CONFIG_FAIL_FAST_ENABLED": settings.config_fail_fast_enabled,
                "CRITIC_ENABLED": settings.critic_enabled,
                "EXTRACTOR_ENABLED": settings.extractor_enabled,
                "PROCEDURAL_MEMORY_ENABLED": (
                    settings.procedural_memory_enabled
                ),
                "STRUCTURED_OUTPUT_ENABLED": settings.structured_output_enabled,
                "BRANCH_BUDGET_ENABLED": settings.branch_budget_enabled,
                "DYNAMIC_CAPABILITY_ENABLED": settings.dynamic_capability_enabled,
                "RERANK_ENABLED": settings.rerank_enabled,
                "RERANK_FAIL_OPEN": settings.rerank_fail_open,
                "DECISION_WEAVING_ENABLED": settings.decision_weaving_enabled,
                "NUMERIC_CHECK_ENABLED": settings.numeric_check_enabled,
                "SEMANTIC_JUDGE_ENABLED": settings.semantic_judge_enabled,
                # R109: both moved to enabled by default. Neither changes the
                # Evidence set -- the golden snapshots moved by exactly these
                # two flag records and nothing else, which is the measurement
                # behind their `operational` classification.
                "PROGRESSIVE_DELIVERY_ENABLED": (
                    settings.progressive_delivery_enabled
                ),
                "TRAJECTORY_RECORD_ENABLED": settings.trajectory_record_enabled,
            },
        )
        self.assertEqual(
            FLAG_CLASSIFICATIONS["RUN_MANIFEST_ENABLED"],
            "operational",
        )
        self.assertEqual(
            FLAG_CLASSIFICATIONS["PROGRESSIVE_DELIVERY_ENABLED"],
            "operational",
        )
        self.assertEqual(
            FLAG_CLASSIFICATIONS["STRUCTURED_OUTPUT_ENABLED"],
            "additive_content",
        )

    def test_manifest_write_failure_degrades_without_losing_completed_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db",
                runs_root=Path(tmp) / "runs",
            )
            engine = DeepResearchEngine(
                settings=settings,
                search_tool=FixtureSearchTool(),
            )
            with patch(
                "deepresearch_agent.workflow.run_persistence.write_run_manifest",
                side_effect=OSError("disk unavailable"),
            ):
                state = engine.run(topic="AI Agent 财富管理研究", depth_level=1)
            engine._checkpoint_conn.close()

        self.assertEqual(state.status, "done")
        self.assertIn(
            "run manifest sidecar unavailable",
            [event["impact"] for event in state.metadata["degradation_events"]],
        )

    def test_manifest_builder_populates_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db",
                as_of=date(2026, 7, 9),
            )
            built = build_run_manifest(
                ResearchState(topic="test", token_used=12, cost_used=0.3),
                settings,
                started_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
            )
        self.assertEqual(built.domain, "finance")
        self.assertEqual(built.mode, "deterministic")
        self.assertEqual(built.token_total, 12)
        self.assertEqual(built.retrieval_corpus_as_of, date(2026, 7, 9))
        self.assertIn("planner", built.model_strings)
        self.assertIn("planner.md", built.prompt_hashes)
        self.assertIn("pydantic", built.dependency_versions)
        self.assertEqual(len(built.config_hash), 64)
        self.assertIsNone(built.cost_cny_total)

    def test_manifest_uses_explicit_provider_fidelity(self) -> None:
        settings = Settings(storage_path=Path("test.db"))
        built = build_run_manifest(
            ResearchState(
                topic="test",
                metadata={
                    "provider_fidelity": {
                        "search": "replay",
                        "structured_data": "replay",
                        "disclosure": "fixture",
                        "llm": "real",
                    }
                },
            ),
            settings,
            started_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        )
        self.assertEqual(built.realness, "mixed")

    def test_manifest_distinguishes_configured_from_actual_provider_use(self) -> None:
        settings = Settings(storage_path=Path("test.db"), execution_mode="llm")
        state = ResearchState(
            topic="test",
            search_records=[SearchRecord(query="query", source_ids=[])],
            metadata={
                "provider_fidelity": {
                    "search": "real",
                    "structured_data": "real",
                    "disclosure": "real",
                    "llm": "real",
                },
                "structured_data_stats": {
                    "q": {
                        "requests": 1,
                        "executed_requests": 1,
                        "records": 1,
                        "symbol_resolution_failures": 0,
                        "execution_failures": 0,
                    }
                },
                "llm_usage": {"by_role": {"planner": {"calls": 1}}},
            },
        )
        built = build_run_manifest(
            state,
            settings,
            started_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
            llm_config=DEFAULT_LLM_CONFIG,
        )

        self.assertEqual(built.provider_usage, {
            "search": 1, "structured_data": 1, "disclosure": 0, "rag_search": 0, "llm": 1,
        })
        self.assertEqual(built.actual_provider_fidelity["disclosure"], "unused")
        self.assertEqual(built.actual_realness, "mixed")

    def test_flag_snapshot_exactly_matches_classifications_when_expanded(self) -> None:
        flags = settings_flag_snapshot(
            Settings(storage_path=Path("test.db")),
            include_disabled_experimental=True,
        )
        self.assertEqual(set(flags), set(FLAG_CLASSIFICATIONS))

    def test_retrieval_records_do_not_inflate_web_search_usage(self) -> None:
        state = ResearchState(
            topic="test",
            search_records=[
                SearchRecord(query="ordinary query", source_ids=[]),
                SearchRecord(query="[rag_search] q", source_ids=[]),
                SearchRecord(query="[web_fetch] u", source_ids=[]),
                SearchRecord(query="[priority_url] u", source_ids=[]),
            ],
            metadata={
                "provider_fidelity": {
                    "search": "fixture", "structured_data": "fixture",
                    "disclosure": "fixture", "rag_search": "fixture", "llm": "fixture",
                }
            },
        )
        built = build_run_manifest(
            state, Settings(storage_path=Path("test.db")),
            started_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        )
        self.assertEqual(built.provider_usage["search"], 1)
        self.assertEqual(built.provider_usage["rag_search"], 1)
        self.assertEqual(built.actual_provider_fidelity["rag_search"], "fixture")

    def test_engine_records_rag_index_version_in_the_manifest_state(self) -> None:
        class IndexedRag:
            fidelity = "fixture"
            index_version = "vT2"

            def search(
                self, *, query: str, as_of: str, context: object | None = None
            ) -> dict[str, object]:
                del query, as_of, context
                return {"candidates": [], "trace": {"status": "empty_index"}}

        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                Settings(
                    storage_path=Path(tmp) / "state.db",
                    rag_enabled=True,
                    injection_guard_enabled=True,
                ),
                rag_search=IndexedRag(),
            )
            try:
                state = engine.run(topic="index version", stop_after_phase="planning")
            finally:
                engine.close()
        self.assertEqual(state.metadata["retrieval_index_version"], "vT2")

    def test_zero_record_structured_call_is_not_real(self) -> None:
        settings = Settings(storage_path=Path("test.db"), execution_mode="llm")
        state = ResearchState(
            topic="test",
            metadata={
                "provider_fidelity": {
                    "search": "real",
                    "structured_data": "real",
                    "disclosure": "real",
                    "llm": "real",
                },
                "structured_data_stats": {
                    "q": {
                        "requests": 1,
                        "executed_requests": 1,
                        "records": 0,
                        "symbol_resolution_failures": 0,
                        "execution_failures": 1,
                    }
                },
                "llm_usage": {"by_role": {"planner": {"calls": 1}}},
            },
        )

        built = build_run_manifest(
            state,
            settings,
            started_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
            llm_config=DEFAULT_LLM_CONFIG,
        )

        self.assertEqual(built.provider_usage["structured_data"], 0)
        self.assertEqual(built.actual_provider_fidelity["structured_data"], "unused")
        self.assertEqual(built.actual_realness, "mixed")

    def test_manifest_records_structured_data_stats(self) -> None:
        stats = {
            "q": {
                "requests": 2,
                "executed_requests": 2,
                "records": 1,
                "symbol_resolution_failures": 0,
                "execution_failures": 1,
            }
        }
        built = build_run_manifest(
            ResearchState(topic="test", metadata={"structured_data_stats": stats}),
            Settings(storage_path=Path("test.db")),
            started_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        )

        self.assertEqual(built.structured_data_stats, stats)

    def test_llm_manifest_uses_the_runtime_client_configuration(self) -> None:
        settings = Settings(
            storage_path=Path("test.db"),
            execution_mode="llm",
        )
        runtime_config = replace(
            DEFAULT_LLM_CONFIG,
            roles={
                **DEFAULT_LLM_CONFIG.roles,
                "reporter": RoleModelConfig(
                    model="openai/deepseek-v4-pro",
                    api_base="https://api.deepseek.com",
                ),
            },
        )

        built = build_run_manifest(
            ResearchState(topic="test"),
            settings,
            started_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
            llm_config=runtime_config,
        )

        self.assertEqual(
            built.model_strings["reporter"],
            "openai/deepseek-v4-pro",
        )

    def test_llm_manifest_rejects_an_unknown_runtime_configuration(self) -> None:
        settings = Settings(
            storage_path=Path("test.db"),
            execution_mode="llm",
        )

        with self.assertRaisesRegex(ValueError, "llm_config is required"):
            build_run_manifest(
                ResearchState(topic="test"),
                settings,
                started_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
            )

    def test_manifest_uses_cny_ledger_total_not_usd_state_cost(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db"
            )
            state = ResearchState(
                topic="real cost",
                cost_used=0.00506855,
                metadata={
                    "llm_usage": {
                        "total_cost_cny": 0.03620392,
                    }
                },
            )

            built = build_run_manifest(
                state,
                settings,
                started_at=datetime(
                    2026,
                    7,
                    24,
                    tzinfo=timezone.utc,
                ),
            )

        self.assertEqual(
            built.cost_cny_total,
            0.03620392,
        )

    def test_manifest_uses_terminal_run_cny_total_without_usage_summary(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db"
            )
            state = ResearchState(
                topic="budget exhausted",
                cost_used=0.005,
                metadata={
                    "llm_run_total_cny": 0.041,
                },
            )

            built = build_run_manifest(
                state,
                settings,
                started_at=datetime(
                    2026,
                    7,
                    24,
                    tzinfo=timezone.utc,
                ),
            )

        self.assertEqual(built.cost_cny_total, 0.041)

    def test_writer_creates_sidecar_and_redacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            item = manifest().model_copy(
                update={"degradation_events": [{"message": "sk-abcdefghijklmnop"}]}
            )
            output = write_run_manifest(item, Path(tmp))
            payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(output.name, "manifest.json")
        self.assertEqual(output.parent.name, "run-1")
        self.assertEqual(
            payload["degradation_events"][0]["message"],
            "[REDACTED_API_KEY]",
        )

    def test_equal_manifests_are_comparable(self) -> None:
        self.assertTrue(compare_manifests(manifest(), manifest()).comparable)

    def test_model_change_is_not_comparable(self) -> None:
        changed = manifest().model_copy(
            update={"model_strings": {"judge": "openai/another-judge"}}
        )
        comparison = compare_manifests(manifest(), changed)
        self.assertFalse(comparison.comparable)
        self.assertIn("model_strings", comparison.differences)

    def test_config_hash_change_is_not_comparable(self) -> None:
        changed = manifest().model_copy(
            update={"config_hash": "config-b"}
        )
        comparison = compare_manifests(manifest(), changed)
        self.assertFalse(comparison.comparable)
        self.assertIn("config_hash", comparison.differences)

    def test_prompt_change_is_not_comparable(self) -> None:
        changed = manifest().model_copy(update={"prompt_hashes": {"judge.md": "def"}})
        self.assertIn("prompt_hashes", compare_manifests(manifest(), changed).differences)

    def test_as_of_change_is_not_comparable(self) -> None:
        changed = manifest().model_copy(
            update={"retrieval_corpus_as_of": date(2026, 7, 10)}
        )
        self.assertIn(
            "retrieval_corpus_as_of",
            compare_manifests(manifest(), changed).differences,
        )

    def test_operational_flag_change_is_informational_and_comparable(self) -> None:
        changed = manifest().model_copy(
            update={"flags": {"RUN_MANIFEST_ENABLED": False}}
        )
        comparison = compare_manifests(manifest(), changed)
        self.assertTrue(comparison.comparable)
        self.assertEqual(comparison.incomparable_reasons, {})
        self.assertIn(
            "flags.RUN_MANIFEST_ENABLED",
            comparison.informational_differences,
        )

    def test_content_affecting_flag_change_is_not_comparable(self) -> None:
        changed = manifest().model_copy(
            update={
                "flags": {
                    "RUN_MANIFEST_ENABLED": True,
                    "CONTEXT_PACKER_ENABLED": True,
                }
            }
        )
        comparison = compare_manifests(manifest(), changed)
        self.assertFalse(comparison.comparable)
        self.assertIn(
            "flags.CONTEXT_PACKER_ENABLED",
            comparison.incomparable_reasons,
        )

    def test_additive_content_flag_change_is_explicit_and_comparable(self) -> None:
        changed = manifest().model_copy(
            update={
                "flags": {
                    "RUN_MANIFEST_ENABLED": True,
                    "STRUCTURED_OUTPUT_ENABLED": True,
                }
            }
        )
        comparison = compare_manifests(manifest(), changed)
        self.assertTrue(comparison.comparable)
        self.assertEqual(comparison.incomparable_reasons, {})
        self.assertIn(
            "flags.STRUCTURED_OUTPUT_ENABLED",
            comparison.additive_differences,
        )
        self.assertNotIn(
            "flags.STRUCTURED_OUTPUT_ENABLED",
            comparison.informational_differences,
        )

    def test_unknown_flag_change_is_conservatively_not_comparable(self) -> None:
        changed = manifest().model_copy(
            update={
                "flags": {
                    "RUN_MANIFEST_ENABLED": True,
                    "NEW_UNCLASSIFIED_FLAG": True,
                }
            }
        )
        comparison = compare_manifests(manifest(), changed)
        self.assertFalse(comparison.comparable)
        self.assertIn("flags.NEW_UNCLASSIFIED_FLAG", comparison.differences)

    def test_mixed_differences_are_split_into_four_output_sections(self) -> None:
        changed = manifest().model_copy(
            update={
                "model_strings": {"judge": "openai/another-judge"},
                "flags": {
                    "RUN_MANIFEST_ENABLED": False,
                    "CONTEXT_PACKER_ENABLED": True,
                    "STRUCTURED_OUTPUT_ENABLED": True,
                },
            }
        )
        payload = format_manifest_comparison(compare_manifests(manifest(), changed))
        self.assertEqual(
            list(payload),
            [
                "incomparable_reasons",
                "additive_differences",
                "informational_differences",
                "conclusion",
            ],
        )
        self.assertIn("model_strings", payload["incomparable_reasons"])
        self.assertIn(
            "flags.CONTEXT_PACKER_ENABLED",
            payload["incomparable_reasons"],
        )
        self.assertIn(
            "flags.RUN_MANIFEST_ENABLED",
            payload["informational_differences"],
        )
        self.assertIn(
            "flags.STRUCTURED_OUTPUT_ENABLED",
            payload["additive_differences"],
        )
        self.assertFalse(payload["conclusion"]["comparable"])

    def test_dependency_change_is_not_comparable(self) -> None:
        changed = manifest().model_copy(
            update={"dependency_versions": {"pydantic": "2.1"}}
        )
        self.assertIn(
            "dependency_versions",
            compare_manifests(manifest(), changed).differences,
        )

    def test_016_flags_are_content_affecting_and_present_when_on(
        self,
    ) -> None:
        settings = Settings(storage_path=Path("test.db"))
        default_flags = settings_flag_snapshot(settings)
        expanded = settings_flag_snapshot(
            settings,
            include_disabled_experimental=True,
        )

        for name in (
            "DECISION_WEAVING_ENABLED",
            "NUMERIC_CHECK_ENABLED",
            "DYNAMIC_CAPABILITY_ENABLED",
        ):
            self.assertEqual(
                FLAG_CLASSIFICATIONS[name],
                "content_affecting",
            )
            self.assertIs(default_flags[name], True)
            self.assertIs(expanded[name], True)

    def test_each_enabled_016_flag_makes_historical_run_incomparable(
        self,
    ) -> None:
        baseline = manifest()
        for name in (
            "DECISION_WEAVING_ENABLED",
            "NUMERIC_CHECK_ENABLED",
            "DYNAMIC_CAPABILITY_ENABLED",
        ):
            with self.subTest(flag=name):
                changed = baseline.model_copy(
                    update={
                        "flags": {
                            **baseline.flags,
                            name: True,
                        }
                    }
                )
                comparison = compare_manifests(baseline, changed)
                self.assertFalse(comparison.comparable)
                self.assertIn(
                    f"flags.{name}",
                    comparison.incomparable_reasons,
                )

    def test_enabled_dynamic_parameters_change_config_hash(
        self,
    ) -> None:
        started = datetime(2026, 7, 24, tzinfo=timezone.utc)
        baseline = build_run_manifest(
            ResearchState(topic="hash"),
            Settings(storage_path=Path("test.db")),
            started_at=started,
        )
        changed = build_run_manifest(
            ResearchState(topic="hash"),
            Settings(
                storage_path=Path("test.db"),
                decision_weaving_budget_remaining_ratio=0.9,
                decision_weaving_verify_min_allocation=9,
                numeric_check_relative_tolerance=0.5,
                numeric_check_absolute_tolerance=5.0,
                dynamic_capability_rules_json='{"narrative":[]}',
            ),
            started_at=started,
        )

        self.assertNotEqual(baseline.config_hash, changed.config_hash)

    def test_reflection_flag_is_content_affecting_and_omitted_when_off(
        self,
    ) -> None:
        settings = Settings(storage_path=Path("test.db"))
        default_flags = settings_flag_snapshot(settings)
        expanded = settings_flag_snapshot(
            settings,
            include_disabled_experimental=True,
        )

        self.assertEqual(
            FLAG_CLASSIFICATIONS["REFLECTION_ENABLED"],
            "content_affecting",
        )
        self.assertNotIn("REFLECTION_ENABLED", default_flags)
        self.assertIs(expanded["REFLECTION_ENABLED"], False)

        enabled = settings_flag_snapshot(
            Settings(
                storage_path=Path("test.db"),
                reflection_enabled=True,
            )
        )
        self.assertIs(enabled["REFLECTION_ENABLED"], True)

    def test_enabled_reflection_makes_historical_run_incomparable(
        self,
    ) -> None:
        changed = manifest().model_copy(
            update={
                "flags": {
                    **manifest().flags,
                    "REFLECTION_ENABLED": True,
                }
            }
        )

        comparison = compare_manifests(manifest(), changed)

        self.assertFalse(comparison.comparable)
        self.assertIn(
            "flags.REFLECTION_ENABLED",
            comparison.incomparable_reasons,
        )

    def test_skill_pack_flag_is_content_affecting_and_omitted_when_off(
        self,
    ) -> None:
        settings = Settings(storage_path=Path("test.db"))
        default_flags = settings_flag_snapshot(settings)
        expanded = settings_flag_snapshot(
            settings,
            include_disabled_experimental=True,
        )

        self.assertEqual(
            FLAG_CLASSIFICATIONS["SKILL_PACKS_ENABLED"],
            "content_affecting",
        )
        self.assertNotIn("SKILL_PACKS_ENABLED", default_flags)
        self.assertIs(expanded["SKILL_PACKS_ENABLED"], False)

        enabled = settings_flag_snapshot(
            Settings(
                storage_path=Path("test.db"),
                skill_packs_enabled=True,
            )
        )
        self.assertIs(enabled["SKILL_PACKS_ENABLED"], True)

    def test_enabled_skill_pack_makes_historical_run_incomparable(
        self,
    ) -> None:
        changed = manifest().model_copy(
            update={
                "flags": {
                    **manifest().flags,
                    "SKILL_PACKS_ENABLED": True,
                }
            }
        )

        comparison = compare_manifests(manifest(), changed)

        self.assertFalse(comparison.comparable)
        self.assertIn(
            "flags.SKILL_PACKS_ENABLED",
            comparison.incomparable_reasons,
        )

    def test_semantic_judge_flag_is_content_affecting_and_present_when_on(
        self,
    ) -> None:
        settings = Settings(storage_path=Path("test.db"))
        default_flags = settings_flag_snapshot(settings)
        expanded = settings_flag_snapshot(
            settings,
            include_disabled_experimental=True,
        )

        self.assertEqual(
            FLAG_CLASSIFICATIONS["SEMANTIC_JUDGE_ENABLED"],
            "content_affecting",
        )
        self.assertIs(default_flags["SEMANTIC_JUDGE_ENABLED"], True)
        self.assertIs(expanded["SEMANTIC_JUDGE_ENABLED"], True)

        enabled = settings_flag_snapshot(
            Settings(
                storage_path=Path("test.db"),
                semantic_judge_enabled=True,
            )
        )
        self.assertIs(enabled["SEMANTIC_JUDGE_ENABLED"], True)

    def test_enabled_semantic_judge_makes_historical_run_incomparable(
        self,
    ) -> None:
        changed = manifest().model_copy(
            update={
                "flags": {
                    **manifest().flags,
                    "SEMANTIC_JUDGE_ENABLED": True,
                }
            }
        )

        comparison = compare_manifests(manifest(), changed)

        self.assertFalse(comparison.comparable)
        self.assertIn(
            "flags.SEMANTIC_JUDGE_ENABLED",
            comparison.incomparable_reasons,
        )

    def test_default_manifest_includes_reachable_semantic_judge_prompt(
        self,
    ) -> None:
        started = datetime(2026, 7, 24, tzinfo=timezone.utc)
        default_manifest = build_run_manifest(
            ResearchState(topic="hash"),
            Settings(storage_path=Path("test.db")),
            started_at=started,
        )
        enabled_manifest = build_run_manifest(
            ResearchState(topic="hash"),
            Settings(
                storage_path=Path("test.db"),
                semantic_judge_enabled=True,
            ),
            started_at=started,
        )

        self.assertIn("semantic_judge.md", default_manifest.prompt_hashes)
        self.assertIn("semantic_judge.md", enabled_manifest.prompt_hashes)


if __name__ == "__main__":
    unittest.main()
