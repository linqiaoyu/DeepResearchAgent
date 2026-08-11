"""Everything a finished run leaves behind, and the failure paths that leave it anyway.

R125 extracted this from ``engine.py``, which had grown to 983 lines against the
900-line bound in ``scripts/check_workflow_module_size.py``.  That guard was red
and unread: it was wired into no gate and no CI job, so a bound nobody ran had
been exceeded for an unknown number of rounds.  Raising the bound would have
moved the threshold rather than fixed anything, so the module was split instead.

The grouping is not arbitrary.  Every method here answers the same question --
what must survive this run, and does it still get written when the run fails?
-- which is why ``_persist_failed_run`` sits beside the sidecar writer it calls
rather than beside the graph code that raised.
"""

from __future__ import annotations

import traceback
from datetime import datetime
from typing import Any

from deepresearch_agent.orchestration import RunScope
from deepresearch_agent.provenance import build_run_manifest, write_run_manifest
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.trajectory import TrajectoryRecorder, TrajectoryTermination


class RunPersistence:
    """Manifest, trajectory, episodic snapshot and terminal-failure persistence."""

    def _record_episodic_snapshot(self, state: ResearchState, manifest: Any) -> None:
        """Write what a later run's prior-memory read is supposed to find.

        R122: nothing in production ever called `episodic_memory.write`, so
        `PRIOR_MEMORY_ENABLED` read an empty store no matter how many runs
        preceded it -- persistence alone would have left it inert. The write is
        skipped when the capability is off, so a run that will never read it
        does not pay to build a snapshot.
        """

        if not self.settings.prior_memory_enabled or not state.final_report:
            return
        try:
            from deepresearch_agent.memory import EpisodicRecord
            from deepresearch_agent.research_snapshot import build_research_snapshot

            snapshot = build_research_snapshot(
                state=state,
                settings=self.settings,
                manifest=manifest,
                as_of=self.research_as_of,
                domain_pack=self.domain_pack,
            )
            self.episodic_memory.write(EpisodicRecord(snapshot=snapshot))
        except Exception as exc:
            state.metadata.setdefault("degradation_events", []).append(
                {
                    "tool": "episodic_memory",
                    "reason": "snapshot_write_failed",
                    "impact": "this run will not be visible to a later prior-memory read",
                    "attempts": 1,
                }
            )
            self.logger.event(
                "episodic_snapshot_failed", error_type=type(exc).__name__
            )

    def _persist_run_sidecars(
        self,
        *,
        state: ResearchState,
        run_scope: RunScope,
        research_id: str,
        recorder: TrajectoryRecorder | None,
        manifest_started_at: datetime,
        termination: TrajectoryTermination,
    ) -> None:
        self._capture_external_request_budget(state, run_scope=run_scope)
        self._capture_llm_run_cost(state)
        manifest_path = None
        if self.settings.run_manifest_enabled:
            try:
                manifest = build_run_manifest(
                    state,
                    self.settings,
                    started_at=manifest_started_at,
                    llm_config=getattr(self.llm_client, "config", None),
                )
                manifest_path = write_run_manifest(
                    manifest,
                    self.settings.runs_root,
                )
                self._record_episodic_snapshot(state, manifest)
            except Exception as exc:
                state.metadata.setdefault(
                    "degradation_events",
                    [],
                ).append(
                    {
                        "tool": "run_manifest",
                        "reason": "write_failed",
                        "impact": (
                            "run manifest sidecar unavailable"
                        ),
                        "attempts": 1,
                    }
                )
                self.logger.event(
                    "manifest_write_failed",
                    error_type=type(exc).__name__,
                )
        if recorder and self.settings.trajectory_record_enabled:
            artifacts = (
                {"report.md": state.final_report or ""}
                if (
                    termination.status
                    in {"completed", "budget_exceeded"}
                    or state.final_report is not None
                )
                else {}
            )
            recorder.finalize(
                manifest_ref=(
                    str(manifest_path) if manifest_path else None
                ),
                artifacts=artifacts,
                termination=termination,
            )
            recorder.write(
                self.settings.runs_root
                / research_id
                / "trajectory.json"
            )

    def _capture_llm_run_cost(
        self,
        state: ResearchState,
    ) -> float | None:
        total_method = getattr(
            self.llm_client,
            "run_total_cny",
            None,
        )
        if not callable(total_method):
            return None
        try:
            total = round(
                float(total_method(state.research_id)),
                8,
            )
        except (OSError, TypeError, ValueError):
            return None
        state.metadata["llm_run_total_cny"] = total
        return total

    def _persist_failed_run(
        self,
        *,
        state: ResearchState,
        run_scope: RunScope,
        research_id: str,
        config: dict[str, Any],
        recorder: TrajectoryRecorder | None,
        manifest_started_at: datetime,
        error: Exception,
    ) -> None:
        try:
            state = self.load_state(research_id) or state
        except Exception as checkpoint_exc:
            # A stale checkpoint schema must not mask the workflow failure that
            # caused this terminal persistence attempt.
            self.logger.event(
                "terminal_checkpoint_load_failed",
                error_type=type(checkpoint_exc).__name__,
            )
        state.status = "failed"
        terminal = state.metadata.get("terminal_failure", {})
        if not isinstance(terminal, dict):
            terminal = {}
        state.metadata["terminal_failure"] = {
            **terminal,
            "phase": state.current_phase,
            "error_type": type(error).__name__,
            "error_message": str(error) or type(error).__name__,
        }
        self._capture_external_request_budget(state, run_scope=run_scope)
        try:
            self.graph.update_state(
                config,
                self._state_output(state),
            )
        except Exception as checkpoint_exc:
            self.logger.event(
                "terminal_checkpoint_write_failed",
                error_type=type(checkpoint_exc).__name__,
            )
        self.logger.event(
            "run_failed",
            error_type=type(error).__name__,
            error=str(error),
            traceback=traceback.format_exc(),
        )
        try:
            self._persist_run_sidecars(
                state=state,
                run_scope=run_scope,
                research_id=research_id,
                recorder=recorder,
                manifest_started_at=manifest_started_at,
                termination=TrajectoryTermination(
                    status="failed",
                    phase=state.current_phase,
                    error_type=type(error).__name__,
                    error_message=(
                        str(error) or type(error).__name__
                    ),
                ),
            )
        except Exception as sidecar_exc:
            self.logger.event(
                "terminal_sidecar_write_failed",
                error_type=type(sidecar_exc).__name__,
            )

    def load_state(self, research_id: str) -> ResearchState | None:
        snapshot = self.graph.get_state(self._config(research_id))
        if not snapshot.values or "research_state" not in snapshot.values:
            return None
        return self._state_from_graph_values(snapshot.values)
