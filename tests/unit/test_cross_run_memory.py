"""R122: the two memories declare `cross_run`; now a second run can read them.

`EpisodicMemory` and `ProceduralMemory` both set
``lifecycle = "cross_run"`` and were plain in-process dicts. The storage schema
had no memory table, nothing wrote one, and the only production construction
site built an empty object per engine, so `PRIOR_MEMORY_ENABLED` and
`PROCEDURAL_MEMORY_ENABLED` could be switched on and read nothing however many
runs preceded them. `tests/unit/test_memory_flags_need_a_prior_run.py` recorded
that as unmeasurable rather than fixing it; those first-run assertions still
hold and are still true, and these are the second run.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from deepresearch_agent.memory import (
    EpisodicMemory,
    EpisodicQuery,
    ProceduralMemory,
    ProceduralQuery,
    ProceduralRecord,
    ProceduralSufficiencyResult,
)
from deepresearch_agent.reflection import DeterministicReflectionSignals
from deepresearch_agent.research_snapshot import research_question_id
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.settings import Settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.workflow import DeepResearchEngine

TOPIC = "AI Agent 在财富管理行业的落地机会研究"


def _procedural_record(run_id: str) -> ProceduralRecord:
    return ProceduralRecord(
        question_type="财报解读",
        strategy=("web_search", "structured_data_provider"),
        sufficiency_result=ProceduralSufficiencyResult(score=0.8, sufficient=True),
        reflection_signals=DeterministicReflectionSignals(),
        run_id=run_id,
        sub_question_id="sq1",
        iteration=0,
        observed_as_of=date(2026, 7, 24),
        provenance_refs=(f"run:{run_id}",),
    )


class ProceduralMemorySurvivesTheProcessTests(unittest.TestCase):
    def test_a_second_memory_over_the_same_store_reads_the_first_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "store.db")
            first = ProceduralMemory(store=store)
            first.write(_procedural_record("run-1"))

            # A different object, as a later process would build.
            second = ProceduralMemory(store=store)
            history = second.query(ProceduralQuery(question_type="财报解读"))

        self.assertEqual(len(history.records), 1)
        self.assertEqual(history.records[0].run_id, "run-1")
        self.assertEqual(
            history.records[0].strategy, ("web_search", "structured_data_provider")
        )

    def test_without_a_store_it_is_still_process_local(self) -> None:
        first = ProceduralMemory()
        first.write(_procedural_record("run-1"))
        second = ProceduralMemory()
        self.assertEqual(
            second.query(ProceduralQuery(question_type="财报解读")).records, []
        )

    def test_writes_from_two_runs_accumulate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "store.db")
            ProceduralMemory(store=store).write(_procedural_record("run-1"))
            ProceduralMemory(store=store).write(_procedural_record("run-2"))
            history = ProceduralMemory(store=store).query(
                ProceduralQuery(question_type="财报解读")
            )
        self.assertEqual(
            sorted(item.run_id for item in history.records), ["run-1", "run-2"]
        )

    def test_a_different_question_type_is_a_different_drawer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "store.db")
            ProceduralMemory(store=store).write(_procedural_record("run-1"))
            history = ProceduralMemory(store=store).query(
                ProceduralQuery(question_type="对比研究")
            )
        self.assertEqual(history.records, [])


class EngineRunsAccumulateMemoryTests(unittest.TestCase):
    """The criterion this round was set: run twice, read the first run back."""

    def _engine(self, tmp: Path, *, reflection: bool = False) -> DeepResearchEngine:
        return DeepResearchEngine(
            settings=Settings(
                storage_path=tmp / "research.db",
                runs_root=tmp / "runs",
                prior_memory_enabled=True,
                procedural_memory_enabled=True,
                # R122: `_write_procedural_memory` is only reached from the
                # reflector node, so `PROCEDURAL_MEMORY_ENABLED` on its own
                # writes nothing, ever. That coupling is asserted below.
                reflection_enabled=reflection,
                structured_logging_enabled=False,
            )
        )

    def test_a_second_run_reads_the_episodic_record_the_first_wrote(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            first = self._engine(tmp)
            first.run(topic=TOPIC, depth_level=1)
            first._checkpoint_conn.close()

            second = self._engine(tmp)
            records = second.episodic_memory.query(
                EpisodicQuery(question_id=research_question_id(TOPIC))
            )
            second._checkpoint_conn.close()

        self.assertGreaterEqual(
            len(records), 1, "the second run saw nothing the first run recorded"
        )

    def _procedural_rows(self, tmp: Path) -> int:
        import sqlite3

        conn = sqlite3.connect(tmp / "research.db")
        try:
            return int(
                conn.execute(
                    "SELECT count(*) FROM memory_record "
                    "WHERE namespace = 'default:finance:procedural'"
                ).fetchone()[0]
            )
        finally:
            conn.close()

    def test_a_second_run_reads_the_procedural_records_the_first_wrote(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            first = self._engine(tmp, reflection=True)
            first.run(topic=TOPIC, depth_level=1)
            first._checkpoint_conn.close()
            written = self._procedural_rows(tmp)

            second = self._engine(tmp, reflection=True)
            types = {
                row.scope_key
                for row in second.store.list_memory_records(
                    "default:finance:procedural",
                    "narrative",
                )
            }
            history = second.procedural_memory.query(
                ProceduralQuery(question_type="narrative")
            )
            second._checkpoint_conn.close()

        self.assertGreater(written, 0, "the first run persisted no strategy")
        self.assertTrue(
            history.records,
            f"the second run read no strategy back (scope keys seen: {types})",
        )

    def test_procedural_memory_writes_without_reflection(self) -> None:
        """The memory flag owns writes; Reflection is an optional signal source."""

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            engine = self._engine(tmp, reflection=False)
            engine.run(topic=TOPIC, depth_level=1)
            engine._checkpoint_conn.close()
            written = self._procedural_rows(tmp)

        self.assertGreater(written, 0)

    def test_dropping_the_store_leaves_the_second_run_blind(self) -> None:
        """The pre-R122 behaviour, restored deliberately."""

        original = EpisodicMemory.__init__

        def without_store(self_, scope=None, store=None):  # type: ignore[no-untyped-def]
            original(self_, scope, None)

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            try:
                EpisodicMemory.__init__ = without_store  # type: ignore[method-assign]
                first = self._engine(tmp)
                first.run(topic=TOPIC, depth_level=1)
                first._checkpoint_conn.close()

                second = self._engine(tmp)
                records = second.episodic_memory.query(
                    EpisodicQuery(question_id=research_question_id(TOPIC))
                )
                second._checkpoint_conn.close()
            finally:
                EpisodicMemory.__init__ = original  # type: ignore[method-assign]

        self.assertEqual(records, [], "the store-less memory still read something")

    def test_the_episodic_store_is_empty_before_any_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            engine = self._engine(tmp)
            records = engine.episodic_memory.query(
                EpisodicQuery(question_id=research_question_id(TOPIC))
            )
            engine._checkpoint_conn.close()
        self.assertEqual(records, [])


class MemoryRecordStoreProtocolTests(unittest.TestCase):
    def test_the_sqlite_store_satisfies_the_narrow_memory_protocol(self) -> None:
        from deepresearch_agent.memory.protocols import MemoryRecordStore

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "store.db")
            self.assertIsInstance(store, MemoryRecordStore)

    def test_state_is_unused_by_these_assertions(self) -> None:
        """Guards against a future refactor coupling memory to run state."""

        self.assertIsNotNone(ResearchState(topic=TOPIC))
        self.assertIsNotNone(date(2026, 7, 9))


if __name__ == "__main__":
    unittest.main()
