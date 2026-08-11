from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import Field

from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.orchestration import (
    ContractField,
    DecisionGate,
    NodeContract,
)
from deepresearch_agent.schemas import (
    AgentDecision,
    ResearchState,
    StrictModel,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools.capability_registry import (
    CapabilityMetadata,
    CapabilityRegistry,
)
from deepresearch_agent.tools.contracts import ToolSpec

SkillApplicability = Callable[["SkillMetadata", str], bool]
SUPPORTED_SKILL_API_VERSION = "1"

SKILL_SELECTION_NODE_CONTRACT = NodeContract(
    name="skill_selection",
    consumes={
        "research_state.agent_decisions": ContractField(list),
    },
    produces=frozenset({"research_state.agent_decisions"}),
    decision_node=True,
)
SKILL_LOAD_NODE_CONTRACT = NodeContract(
    name="skill_load",
    consumes={
        "research_state.agent_decisions": ContractField(list),
    },
    produces=frozenset({"research_state.agent_decisions"}),
    decision_node=True,
)


class SkillMetadata(StrictModel):
    name: str
    description: str
    version: str
    harness_api_version: str
    root: Path


class SkillCapabilityDefinition(StrictModel):
    name: str
    applicable_subquestion_types: tuple[str, ...] = Field(min_length=1)
    cost_level: str
    has_side_effect: bool
    tool_spec: ToolSpec
    resource: str


class LoadedSkill(StrictModel):
    metadata: SkillMetadata
    resources: dict[str, str]
    capability: SkillCapabilityDefinition

    def resource_text(self, name: str | None = None) -> str:
        target = name or self.capability.resource
        try:
            return self.resources[target]
        except KeyError as exc:
            raise KeyError(
                f"Skill resource is not loaded: {target}"
            ) from exc

    def resource_json(self, name: str | None = None) -> Any:
        return json.loads(self.resource_text(name))

    def __call__(self, arguments: dict[str, Any]) -> Any:
        requested = arguments.get(
            "resource",
            self.capability.resource,
        )
        if not isinstance(requested, str):
            raise ValueError("resource must be a string")
        return {
            "skill": self.metadata.name,
            "resource": requested,
            "content": self.resource_text(requested),
        }


class SkillLoadOutcome(StrictModel):
    selected_skills: tuple[str, ...] = ()
    loaded_skills: tuple[LoadedSkill, ...] = ()
    registered_capabilities: tuple[str, ...] = ()


class SkillPackLoader:
    """Load metadata first and resources only after deterministic selection."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.metadata_reads: list[Path] = []
        self.resource_reads: list[Path] = []

    def discover(self) -> list[SkillMetadata]:
        if not self.root.exists():
            return []
        metadata: list[SkillMetadata] = []
        for skill_file in sorted(self.root.glob("*/SKILL.md")):
            metadata.append(self._read_metadata(skill_file))
        return metadata

    def load_for_context(
        self,
        context: str,
        *,
        registry: CapabilityRegistry,
        state: ResearchState,
        is_applicable: SkillApplicability,
    ) -> SkillLoadOutcome:
        before_selection = state.model_copy(deep=True)
        discovered = self.discover()
        selected = [
            item for item in discovered if is_applicable(item, context)
        ]
        selection_decision = AgentDecision(
            decision_type="skill_selection",
            made_by="SkillPackLoader",
            inputs={
                "context": context,
                "discovered_skills": [
                    item.name for item in discovered
                ],
                "selected_skills": [item.name for item in selected],
                "resource_reads_before_selection": len(
                    self.resource_reads
                ),
            },
            criterion=(
                "evaluate only SKILL.md name/description metadata before "
                "opening any resource file"
            ),
            outcome=(
                "selected=" + str([item.name for item in selected])
            ),
            alternatives_considered=[
                "load every skill resource eagerly",
                "skip skill discovery",
            ],
        )
        record_agent_decision(state, selection_decision)
        DecisionGate.validate(
            SKILL_SELECTION_NODE_CONTRACT.name,
            {"research_state": before_selection},
            {"research_state": state},
        )

        if not selected:
            return SkillLoadOutcome()

        before_load = state.model_copy(deep=True)
        loaded = [self._load_resources(metadata) for metadata in selected]
        registered: list[str] = []
        existing = {item.name for item in registry.query()}
        incoming = [skill.capability.name for skill in loaded]
        collisions = sorted(
            name
            for name in set(incoming)
            if name in existing or incoming.count(name) > 1
        )
        if collisions:
            raise ValueError(
                "Skill capability collision: " + ", ".join(collisions)
            )
        for skill in loaded:
            capability = skill.capability
            if capability.name in existing:  # pragma: no cover - preflight invariant
                raise ValueError(
                    f"Skill capability collision: {capability.name}"
                )
            registry.register(
                CapabilityMetadata(
                    name=capability.name,
                    applicable_subquestion_types=(
                        capability.applicable_subquestion_types
                    ),
                    cost_level=_cost_level(capability.cost_level),
                    has_side_effect=capability.has_side_effect,
                    tool_spec=capability.tool_spec,
                ),
                skill,
            )
            existing.add(capability.name)
            registered.append(capability.name)

        load_decision = AgentDecision(
            decision_type="skill_load",
            made_by="SkillPackLoader",
            inputs={
                "loaded_skills": [
                    item.metadata.name for item in loaded
                ],
                "loaded_resources": [
                    sorted(item.resources) for item in loaded
                ],
                "registered_capabilities": registered,
            },
            criterion=(
                "load resources only for selected skills and register each "
                "declared capability in CapabilityRegistry"
            ),
            outcome=(
                f"loaded={[item.metadata.name for item in loaded]}; "
                f"registered={registered}"
            ),
            alternatives_considered=[
                "load metadata only",
                "create a parallel skill capability registry",
            ],
        )
        record_agent_decision(state, load_decision)
        DecisionGate.validate(
            SKILL_LOAD_NODE_CONTRACT.name,
            {"research_state": before_load},
            {"research_state": state},
        )
        return SkillLoadOutcome(
            selected_skills=tuple(
                item.metadata.name for item in loaded
            ),
            loaded_skills=tuple(loaded),
            registered_capabilities=tuple(registered),
        )

    def _read_metadata(self, skill_file: Path) -> SkillMetadata:
        self._require_within(skill_file, self.root, "Skill metadata escapes root")
        self.metadata_reads.append(skill_file)
        with skill_file.open("r", encoding="utf-8") as handle:
            if handle.readline().rstrip("\r\n") != "---":
                raise ValueError(
                    f"SKILL.md must start with YAML frontmatter: {skill_file}"
                )
            fields: dict[str, str] = {}
            for line in handle:
                stripped = line.rstrip("\r\n")
                if stripped == "---":
                    break
                key, separator, value = stripped.partition(":")
                if separator:
                    fields[key.strip()] = value.strip().strip("\"'")
            else:
                raise ValueError(
                    f"SKILL.md frontmatter is not closed: {skill_file}"
                )
        required_fields = {
            "name",
            "description",
            "version",
            "harness_api_version",
        }
        if set(fields) != required_fields:
            raise ValueError(
                "SKILL.md frontmatter must contain exactly name, description, "
                f"version and harness_api_version: {skill_file}"
            )
        if any(not fields[name] for name in required_fields):
            raise ValueError(
                f"SKILL.md metadata values must be non-empty: {skill_file}"
            )
        if fields["harness_api_version"] != SUPPORTED_SKILL_API_VERSION:
            raise ValueError(
                "Incompatible Skill harness API version: "
                f"{fields['harness_api_version']}"
            )
        if skill_file.parent.name != fields["name"]:
            raise ValueError(
                "Skill directory name must match frontmatter name: "
                f"{skill_file}"
            )
        return SkillMetadata(
            name=fields["name"],
            description=fields["description"],
            version=fields["version"],
            harness_api_version=fields["harness_api_version"],
            root=skill_file.parent,
        )

    def _load_resources(self, metadata: SkillMetadata) -> LoadedSkill:
        resource_root = metadata.root / "resources"
        if not resource_root.is_dir():
            raise ValueError(
                f"Skill has no resources directory: {metadata.name}"
            )
        resources: dict[str, str] = {}
        for path in sorted(resource_root.iterdir()):
            if path.is_symlink():
                raise ValueError(
                    f"Skill resource symlinks are forbidden: {path}"
                )
            if not path.is_file():
                continue
            self._require_within(path, resource_root, "Skill resource escapes its pack")
            self.resource_reads.append(path)
            resources[path.name] = path.read_text(encoding="utf-8")
        raw_definition = resources.get("capability.json")
        if raw_definition is None:
            raise ValueError(
                f"Skill has no resources/capability.json: {metadata.name}"
            )
        capability = SkillCapabilityDefinition.model_validate_json(
            raw_definition
        )
        if capability.name != capability.tool_spec.name:
            raise ValueError(
                "Skill capability name must match ToolSpec name"
            )
        if capability.cost_level != capability.tool_spec.cost_class:
            raise ValueError(
                "Skill capability cost must match ToolSpec cost"
            )
        if (
            capability.has_side_effect
            != capability.tool_spec.has_side_effect
        ):
            raise ValueError(
                "Skill capability side effect must match ToolSpec"
            )
        if capability.resource not in resources:
            raise ValueError(
                f"Skill capability resource is missing: "
                f"{capability.resource}"
            )
        return LoadedSkill(
            metadata=metadata,
            resources=resources,
            capability=capability,
        )

    @staticmethod
    def _require_within(path: Path, root: Path, message: str) -> None:
        resolved_root = root.resolve()
        resolved_path = path.resolve()
        if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
            raise ValueError(f"{message}: {path}")


def load_skills_if_enabled(
    settings: Settings,
    loader: SkillPackLoader,
    context: str,
    *,
    registry: CapabilityRegistry,
    state: ResearchState,
    is_applicable: SkillApplicability,
) -> SkillLoadOutcome:
    if not settings.skill_packs_enabled:
        return SkillLoadOutcome()
    return loader.load_for_context(
        context,
        registry=registry,
        state=state,
        is_applicable=is_applicable,
    )


def _cost_level(value: str) -> str:
    if value not in {"free", "low", "medium", "high"}:
        raise ValueError(f"Unknown skill capability cost level: {value}")
    return value
