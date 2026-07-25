from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from deepresearch_agent.provenance import (
    ManifestComparison,
    RunManifest,
    compare_manifests,
    settings_flag_snapshot,
)
from deepresearch_agent.schemas import (
    ResearchState,
    StrictModel,
    StructuredResearchOutput,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.structured_output import build_structured_output

ChangeType = Literal[
    "added_claim",
    "disappeared_claim",
    "numeric_change",
    "evidence_replacement",
    "confidence_change",
    "scope_change",
]
Materiality = Literal["material", "minor"]


class NormalizedClaimKey(StrictModel):
    entity: str
    metric: str
    period: str
    scope: str

    def tuple(self) -> tuple[str, str, str, str]:
        return (self.entity, self.metric, self.period, self.scope)

    def without_scope(self) -> tuple[str, str, str]:
        return (self.entity, self.metric, self.period)


class DisplayClaimKey(StrictModel):
    entity: str
    metric: str
    period: str
    scope: str


class SnapshotClaim(StrictModel):
    claim_id: str
    key: NormalizedClaimKey
    display_key: DisplayClaimKey | None = None
    text: str
    value: float | None = None
    unit: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    thesis_direction: Literal[
        "positive",
        "negative",
        "neutral",
        "uncertain",
    ] = "neutral"


class ResearchSnapshot(StrictModel):
    schema_version: int = 1
    question_id: str
    question: str
    as_of: date
    claims: list[SnapshotClaim] = Field(default_factory=list)
    structured_objects: StructuredResearchOutput
    manifest_ref: str
    manifest: RunManifest
    flags: dict[str, bool]
    demo_constructed: bool = False
    demo_note: str | None = None


class MaterialityRules(StrictModel):
    numeric_relative_threshold: float = Field(default=0.1, ge=0)
    confidence_absolute_threshold: float = Field(default=0.1, ge=0, le=1)
    scope_change_is_material: bool = True
    directional_claim_change_is_material: bool = True


class SnapshotChange(StrictModel):
    change_type: ChangeType
    materiality: Materiality
    key: NormalizedClaimKey
    display_key: DisplayClaimKey
    old_text: str | None = None
    new_text: str | None = None
    old_value: float | None = None
    new_value: float | None = None
    old_unit: str | None = None
    new_unit: str | None = None
    old_sources: list[str] = Field(default_factory=list)
    new_sources: list[str] = Field(default_factory=list)
    old_confidence: float | None = None
    new_confidence: float | None = None
    old_as_of: date
    new_as_of: date
    detail: str


class SnapshotDiff(StrictModel):
    schema_version: int = 1
    question_id: str
    question: str
    old_as_of: date
    new_as_of: date
    demo_constructed: bool = False
    demo_note: str | None = None
    comparable: bool
    system_change_warning: bool
    system_change_reasons: list[str] = Field(default_factory=list)
    manifest_comparison: ManifestComparison
    changes: list[SnapshotChange] = Field(default_factory=list)
    paste_summary: str


def build_research_snapshot(
    *,
    state: ResearchState,
    settings: Settings,
    manifest: RunManifest,
    as_of: date,
    question_id: str | None = None,
) -> ResearchSnapshot:
    structured = state.structured_output or build_structured_output(state)
    evidence_by_id = {item.id: item for item in state.evidence_store}
    claims: list[SnapshotClaim] = []
    metric_evidence_ids: set[str] = set()
    for row in structured.comparison_table.rows:
        metric_evidence_ids.update(row.evidence_ids)
        sources = sorted(
            {
                evidence_by_id[evidence_id].source_url
                for evidence_id in row.evidence_ids
                if evidence_id in evidence_by_id
            }
        )
        key = NormalizedClaimKey(
            entity=_normalize(row.entity),
            metric=_normalize(row.normalized_metric),
            period=_normalize(row.period),
            scope=_normalize(row.scope),
        )
        display_key = DisplayClaimKey(
            entity=row.entity,
            metric=row.metric,
            period=row.period,
            scope=row.scope,
        )
        text = (
            f"{row.entity} {row.period} {row.scope}{row.normalized_metric} "
            f"{row.value:g}{row.unit}"
        )
        claims.append(
            SnapshotClaim(
                claim_id=_claim_id(key, text),
                key=key,
                display_key=display_key,
                text=text,
                value=row.value,
                unit=row.unit,
                evidence_ids=sorted(row.evidence_ids),
                source_urls=sources,
                confidence=row.confidence,
            )
        )
    for item in state.evidence_store:
        if item.id in metric_evidence_ids and item.claim_type == "data":
            continue
        normalized_text = _normalize(item.claim)
        key = NormalizedClaimKey(
            entity="",
            metric=f"claim:{hashlib.sha256(normalized_text.encode('utf-8')).hexdigest()[:16]}",
            period="",
            scope="",
        )
        claims.append(
            SnapshotClaim(
                claim_id=_claim_id(key, item.claim),
                key=key,
                display_key=DisplayClaimKey(
                    entity="论点",
                    metric=item.claim,
                    period=item.source_pub_date.isoformat() if item.source_pub_date else "unknown",
                    scope="定性",
                ),
                text=item.claim,
                evidence_ids=[item.id],
                source_urls=[item.source_url],
                confidence=item.confidence,
                thesis_direction=(
                    "uncertain" if item.claim_type == "projection" else "neutral"
                ),
            )
        )
    claims = _merge_duplicate_claims(claims)
    return ResearchSnapshot(
        question_id=question_id or research_question_id(state.topic),
        question=state.topic,
        as_of=as_of,
        claims=claims,
        structured_objects=structured,
        manifest_ref=_manifest_sha256(manifest),
        manifest=manifest,
        flags=settings_flag_snapshot(
            settings,
            include_disabled_experimental=True,
        ),
    )


def diff_research_snapshots(
    old: ResearchSnapshot,
    new: ResearchSnapshot,
    *,
    rules: MaterialityRules | None = None,
) -> SnapshotDiff:
    if old.question_id != new.question_id:
        raise ValueError("snapshot question_id values must match")
    rules = rules or MaterialityRules()
    manifest_comparison = compare_manifests(old.manifest, new.manifest)
    system_reasons = sorted(manifest_comparison.incomparable_reasons)
    if old.as_of != new.as_of and not any("as_of" in item for item in system_reasons):
        system_reasons.append("snapshot_as_of")

    changes: list[SnapshotChange] = []
    old_numeric = [claim for claim in old.claims if claim.value is not None]
    new_numeric = [claim for claim in new.claims if claim.value is not None]
    old_text = [claim for claim in old.claims if claim.value is None]
    new_text = [claim for claim in new.claims if claim.value is None]

    consumed_old: set[str] = set()
    consumed_new: set[str] = set()
    _detect_scope_changes(
        old_numeric,
        new_numeric,
        consumed_old,
        consumed_new,
        changes,
        old,
        new,
        rules,
    )
    _detect_exact_key_changes(
        old_numeric + old_text,
        new_numeric + new_text,
        consumed_old,
        consumed_new,
        changes,
        old,
        new,
        rules,
    )
    for claim in sorted(
        (item for item in old.claims if item.claim_id not in consumed_old),
        key=_claim_sort_key,
    ):
        changes.append(
            _claim_presence_change(
                "disappeared_claim",
                claim,
                old,
                new,
                rules,
            )
        )
    for claim in sorted(
        (item for item in new.claims if item.claim_id not in consumed_new),
        key=_claim_sort_key,
    ):
        changes.append(
            _claim_presence_change("added_claim", claim, old, new, rules)
        )
    changes.sort(
        key=lambda item: (
            0 if item.materiality == "material" else 1,
            _change_order(item.change_type),
            item.key.tuple(),
            item.old_text or "",
            item.new_text or "",
        )
    )
    paste_summary = _paste_summary(changes, old.as_of, new.as_of)
    return SnapshotDiff(
        question_id=old.question_id,
        question=old.question,
        old_as_of=old.as_of,
        new_as_of=new.as_of,
        demo_constructed=old.demo_constructed or new.demo_constructed,
        demo_note=new.demo_note or old.demo_note,
        comparable=not system_reasons,
        system_change_warning=bool(system_reasons),
        system_change_reasons=system_reasons,
        manifest_comparison=manifest_comparison,
        changes=changes,
        paste_summary=paste_summary,
    )


def render_snapshot_diff_json(diff: SnapshotDiff) -> str:
    return json.dumps(
        diff.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_snapshot_diff_markdown(diff: SnapshotDiff) -> str:
    labels = {
        "added_claim": "新增论点",
        "disappeared_claim": "消失论点",
        "numeric_change": "数值变化",
        "evidence_replacement": "证据更替",
        "confidence_change": "置信度变化",
        "scope_change": "口径变化",
    }
    lines = [
        "# 研究快照变更报告",
        "",
        f"- 研究问题：{diff.question}",
        f"- 比较区间：{diff.old_as_of.isoformat()} → {diff.new_as_of.isoformat()}",
        f"- 变更总数：{len(diff.changes)}",
        f"- 重大变更：{sum(1 for item in diff.changes if item.materiality == 'material')}",
    ]
    if diff.demo_constructed:
        lines.extend(
            [
                "",
                "> 🧪 演示数据声明："
                + (
                    diff.demo_note
                    or "本报告包含 fixture 派生的演示用构造数据。"
                ),
            ]
        )
    if diff.system_change_warning:
        lines.extend(
            [
                "",
                "> ⚠️ 本次比较跨越了系统变更，部分差异可能来自系统而非世界。",
                "> 跨越项：" + "、".join(diff.system_change_reasons),
            ]
        )
    lines.extend(["", "## 变更明细"])
    if not diff.changes:
        lines.append("- 无")
    for item in diff.changes:
        marker = "material" if item.materiality == "material" else "minor"
        lines.append(
            f"- **{marker}｜{labels[item.change_type]}**｜{item.detail}"
        )
        lines.append(
            f"  - 截止日：{item.old_as_of.isoformat()} → {item.new_as_of.isoformat()}"
        )
        if item.old_sources or item.new_sources:
            lines.append(
                "  - 来源："
                f"{', '.join(item.old_sources) or '无'} → "
                f"{', '.join(item.new_sources) or '无'}"
            )
    lines.extend(["", "## 可直接粘贴摘要", "", diff.paste_summary, ""])
    return "\n".join(lines)


def save_research_snapshot(snapshot: ResearchSnapshot, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            snapshot.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def load_research_snapshot(path: Path) -> ResearchSnapshot:
    return ResearchSnapshot.model_validate_json(path.read_text(encoding="utf-8"))


def build_demo_followup(
    baseline: ResearchSnapshot,
    *,
    as_of: date,
) -> ResearchSnapshot:
    """Construct a labelled fixture-only follow-up for workflow demonstration."""

    claims = [claim.model_copy(deep=True) for claim in baseline.claims]
    numeric = [claim for claim in claims if claim.value is not None]
    textual = [claim for claim in claims if claim.value is None]
    productivity_claims = [
        claim for claim in numeric if "advisorproductivity" in claim.key.metric
    ]
    numeric_change = (
        min(
            productivity_claims,
            key=lambda claim: float(claim.value or 0.0),
        )
        if productivity_claims
        else next(
            (claim for claim in numeric if "营业收入" in claim.key.metric),
            numeric[0] if numeric else None,
        )
    )
    if numeric_change is not None:
        numeric_change.value = round(float(numeric_change.value) * 1.12, 4)
        numeric_change.text = f"{numeric_change.text}（演示变体：数值更新）"
        numeric_change.claim_id = _claim_id(numeric_change.key, numeric_change.text)
    scope_change = next(
        (
            claim
            for claim in numeric
            if claim is not numeric_change
            and (
                "assetsundermanagementgrowth" in claim.key.metric
                or "扣非净利润" in claim.key.metric
            )
        ),
        next((claim for claim in numeric if claim is not numeric_change), None),
    )
    if scope_change is not None:
        scope_change.key.scope = f"{scope_change.key.scope}-调整口径"
        if scope_change.display_key is not None:
            scope_change.display_key.scope = (
                f"{scope_change.display_key.scope}（调整口径）"
            )
        scope_change.text = f"{scope_change.text}（演示变体：口径调整）"
        scope_change.claim_id = _claim_id(scope_change.key, scope_change.text)
    if textual:
        textual[0].source_urls = ["fixture-demo://followup/replacement-source"]
        textual[0].evidence_ids = ["fixture-demo-evidence-replacement"]
    if len(textual) > 1:
        textual[1].confidence = max(0.0, textual[1].confidence - 0.2)
    if len(textual) > 2:
        removed = textual[-1]
        claims = [claim for claim in claims if claim.claim_id != removed.claim_id]
    added_key = NormalizedClaimKey(
        entity="fixture-demo",
        metric="claim:followup-added",
        period=as_of.isoformat(),
        scope="演示构造",
    )
    added_text = (
        "该试点已进入生产验证阶段，下一步需评估运行稳定性与人工复核覆盖率。"
    )
    claims.append(
        SnapshotClaim(
            claim_id=_claim_id(added_key, added_text),
            key=added_key,
            display_key=DisplayClaimKey(
                entity="财富管理 AI 试点",
                metric="生产验证状态",
                period=as_of.isoformat(),
                scope="试点项目",
            ),
            text=added_text,
            evidence_ids=["fixture-demo-added-evidence"],
            source_urls=["fixture-demo://followup/added-source"],
            confidence=0.7,
            thesis_direction="positive",
        )
    )
    manifest = baseline.manifest.model_copy(
        update={
            "retrieval_corpus_as_of": as_of,
            "evaluation_as_of": as_of,
        }
    )
    return baseline.model_copy(
        update={
            "as_of": as_of,
            "claims": sorted(claims, key=_claim_sort_key),
            "manifest": manifest,
            "manifest_ref": _manifest_sha256(manifest),
            "demo_constructed": True,
            "demo_note": (
                "演示用构造数据：由既有 deterministic fixture 快照派生，"
                "不属于 Golden Set，不代表真实客户或真实市场更新。"
            ),
        }
    )


def _detect_scope_changes(
    old_claims: list[SnapshotClaim],
    new_claims: list[SnapshotClaim],
    consumed_old: set[str],
    consumed_new: set[str],
    changes: list[SnapshotChange],
    old: ResearchSnapshot,
    new: ResearchSnapshot,
    rules: MaterialityRules,
) -> None:
    old_groups = _group_claims(old_claims, without_scope=True)
    new_groups = _group_claims(new_claims, without_scope=True)
    for base_key in sorted(set(old_groups) & set(new_groups)):
        old_group = old_groups[base_key]
        new_group = new_groups[base_key]
        if len(old_group) != 1 or len(new_group) != 1:
            continue
        left, right = old_group[0], new_group[0]
        if left.key.scope == right.key.scope:
            continue
        consumed_old.add(left.claim_id)
        consumed_new.add(right.claim_id)
        changes.append(
            SnapshotChange(
                change_type="scope_change",
                materiality=(
                    "material" if rules.scope_change_is_material else "minor"
                ),
                key=right.key,
                display_key=_display_key(right),
                old_text=left.text,
                new_text=right.text,
                old_value=left.value,
                new_value=right.value,
                old_unit=left.unit,
                new_unit=right.unit,
                old_sources=left.source_urls,
                new_sources=right.source_urls,
                old_confidence=left.confidence,
                new_confidence=right.confidence,
                old_as_of=old.as_of,
                new_as_of=new.as_of,
                detail=(
                    f"{_key_label(_display_key(left))}：口径从"
                    f"“{_display_key(left).scope}”变为"
                    f"“{_display_key(right).scope}”；数值不并入数值变化。"
                ),
            )
        )


def _detect_exact_key_changes(
    old_claims: list[SnapshotClaim],
    new_claims: list[SnapshotClaim],
    consumed_old: set[str],
    consumed_new: set[str],
    changes: list[SnapshotChange],
    old: ResearchSnapshot,
    new: ResearchSnapshot,
    rules: MaterialityRules,
) -> None:
    old_groups = _group_claims(old_claims)
    new_groups = _group_claims(new_claims)
    for key in sorted(set(old_groups) & set(new_groups)):
        left_group = [
            item for item in old_groups[key] if item.claim_id not in consumed_old
        ]
        right_group = [
            item for item in new_groups[key] if item.claim_id not in consumed_new
        ]
        for left, right in zip(left_group, right_group):
            consumed_old.add(left.claim_id)
            consumed_new.add(right.claim_id)
            if left.value is not None and right.value is not None and (
                left.value != right.value or left.unit != right.unit
            ):
                relative = _relative_change(left.value, right.value)
                changes.append(
                    SnapshotChange(
                        change_type="numeric_change",
                        materiality=(
                            "material"
                            if relative >= rules.numeric_relative_threshold
                            else "minor"
                        ),
                        key=right.key,
                        display_key=_display_key(right),
                        old_text=left.text,
                        new_text=right.text,
                        old_value=left.value,
                        new_value=right.value,
                        old_unit=left.unit,
                        new_unit=right.unit,
                        old_sources=left.source_urls,
                        new_sources=right.source_urls,
                        old_confidence=left.confidence,
                        new_confidence=right.confidence,
                        old_as_of=old.as_of,
                        new_as_of=new.as_of,
                        detail=(
                            f"{_key_label(_display_key(right))}："
                            f"{left.value:g}{left.unit or ''}"
                            f" → {right.value:g}{right.unit or ''}"
                            f"（相对变化 {relative:.2%}）。"
                        ),
                    )
                )
            if left.source_urls != right.source_urls:
                changes.append(
                    _paired_change(
                        "evidence_replacement",
                        left,
                        right,
                        old,
                        new,
                        "minor",
                        "支撑来源发生更替，论点键保持不变。",
                    )
                )
            confidence_delta = abs(left.confidence - right.confidence)
            if confidence_delta > 0:
                changes.append(
                    _paired_change(
                        "confidence_change",
                        left,
                        right,
                        old,
                        new,
                        (
                            "material"
                            if confidence_delta
                            >= rules.confidence_absolute_threshold
                            else "minor"
                        ),
                        (
                            f"置信度 {left.confidence:.2f} → {right.confidence:.2f}"
                            f"（绝对变化 {confidence_delta:.2f}）。"
                        ),
                    )
                )


def _paired_change(
    change_type: Literal["evidence_replacement", "confidence_change"],
    left: SnapshotClaim,
    right: SnapshotClaim,
    old: ResearchSnapshot,
    new: ResearchSnapshot,
    materiality: Materiality,
    detail: str,
) -> SnapshotChange:
    return SnapshotChange(
        change_type=change_type,
        materiality=materiality,
        key=right.key,
        display_key=_display_key(right),
        old_text=left.text,
        new_text=right.text,
        old_value=left.value,
        new_value=right.value,
        old_unit=left.unit,
        new_unit=right.unit,
        old_sources=left.source_urls,
        new_sources=right.source_urls,
        old_confidence=left.confidence,
        new_confidence=right.confidence,
        old_as_of=old.as_of,
        new_as_of=new.as_of,
        detail=detail,
    )


def _claim_presence_change(
    change_type: Literal["added_claim", "disappeared_claim"],
    claim: SnapshotClaim,
    old: ResearchSnapshot,
    new: ResearchSnapshot,
    rules: MaterialityRules,
) -> SnapshotChange:
    directional = claim.thesis_direction in {"positive", "negative"}
    materiality: Materiality = (
        "material"
        if directional and rules.directional_claim_change_is_material
        else "minor"
    )
    added = change_type == "added_claim"
    return SnapshotChange(
        change_type=change_type,
        materiality=materiality,
        key=claim.key,
        display_key=_display_key(claim),
        old_text=None if added else claim.text,
        new_text=claim.text if added else None,
        old_value=None if added else claim.value,
        new_value=claim.value if added else None,
        old_unit=None if added else claim.unit,
        new_unit=claim.unit if added else None,
        old_sources=[] if added else claim.source_urls,
        new_sources=claim.source_urls if added else [],
        old_confidence=None if added else claim.confidence,
        new_confidence=claim.confidence if added else None,
        old_as_of=old.as_of,
        new_as_of=new.as_of,
        detail=(
            f"{'新增' if added else '消失'}：{claim.text}"
            f"（方向：{claim.thesis_direction}）。"
        ),
    )


def _group_claims(
    claims: list[SnapshotClaim],
    *,
    without_scope: bool = False,
) -> dict[tuple[str, ...], list[SnapshotClaim]]:
    groups: dict[tuple[str, ...], list[SnapshotClaim]] = defaultdict(list)
    for claim in claims:
        key = claim.key.without_scope() if without_scope else claim.key.tuple()
        groups[key].append(claim)
    for group in groups.values():
        group.sort(key=_claim_sort_key)
    return groups


def _merge_duplicate_claims(claims: list[SnapshotClaim]) -> list[SnapshotClaim]:
    grouped: dict[tuple[Any, ...], list[SnapshotClaim]] = defaultdict(list)
    for claim in claims:
        grouped[
            (
                claim.key.tuple(),
                claim.value,
                claim.unit,
                _normalize(claim.text),
            )
        ].append(claim)
    merged: list[SnapshotClaim] = []
    for group in grouped.values():
        first = group[0]
        evidence_ids = sorted(
            {item for claim in group for item in claim.evidence_ids}
        )
        source_urls = sorted(
            {item for claim in group for item in claim.source_urls}
        )
        merged.append(
            first.model_copy(
                update={
                    "evidence_ids": evidence_ids,
                    "source_urls": source_urls,
                    "confidence": min(claim.confidence for claim in group),
                }
            )
        )
    return sorted(merged, key=_claim_sort_key)


def _paste_summary(
    changes: list[SnapshotChange],
    old_as_of: date,
    new_as_of: date,
) -> str:
    material = [item for item in changes if item.materiality == "material"]
    selected = material[:3] or changes[:3]
    total = len(changes)
    material_count = len(material)
    opening = (
        f"本期共识别 {material_count} 项重大变更（总计 {total} 项），"
        f"比较区间为 {old_as_of.isoformat()} 至 {new_as_of.isoformat()}。"
    )
    if not selected:
        return opening + "未检出需要进一步说明的结构化变化。"
    transitions = ("最重要的是，", "其次，", "此外，")
    sentences = [
        transitions[index] + _summary_change_text(item)
        for index, item in enumerate(selected)
    ]
    return opening + "".join(sentences)


def _summary_change_text(item: SnapshotChange) -> str:
    label = _key_label(item.display_key)
    if item.change_type == "added_claim":
        text = (item.new_text or "未提供正文").rstrip("。！？!?")
        return f"新增论点“{text}”。"
    if item.change_type == "disappeared_claim":
        return f"原论点“{item.old_text or '未提供正文'}”不再出现。"
    if item.change_type == "numeric_change":
        return (
            f"{label}，数值由 {item.old_value:g}{item.old_unit or ''} 变为 "
            f"{item.new_value:g}{item.new_unit or ''}。"
        )
    if item.change_type == "scope_change":
        return f"{label}发生口径调整，相关数值不作直接同比。"
    if item.change_type == "confidence_change":
        text = (item.new_text or item.old_text or "该论点").rstrip("。！？!?")
        return (
            f"论点“{text}”的置信度由 {item.old_confidence:.2f} "
            f"变为 {item.new_confidence:.2f}。"
        )
    return f"{label}的支撑来源发生更替。"


def _relative_change(old: float, new: float) -> float:
    return abs(new - old) / max(abs(old), 1.0)


def _change_order(change_type: ChangeType) -> int:
    return {
        "added_claim": 0,
        "disappeared_claim": 1,
        "numeric_change": 2,
        "evidence_replacement": 3,
        "confidence_change": 4,
        "scope_change": 5,
    }[change_type]


def _claim_sort_key(claim: SnapshotClaim) -> tuple[Any, ...]:
    return (
        claim.key.tuple(),
        claim.value is None,
        claim.value or 0.0,
        claim.text,
        claim.claim_id,
    )


def _claim_id(key: NormalizedClaimKey, text: str) -> str:
    payload = json.dumps(
        {"key": key.model_dump(), "text": _normalize(text)},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def research_question_id(question: str) -> str:
    return hashlib.sha256(_normalize(question).encode("utf-8")).hexdigest()[:20]


def _manifest_sha256(manifest: RunManifest) -> str:
    encoded = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lower())


def _display_key(claim: SnapshotClaim) -> DisplayClaimKey:
    if claim.display_key is not None:
        return claim.display_key
    return DisplayClaimKey(
        entity=claim.key.entity or "未标注",
        metric=claim.key.metric or "未标注",
        period=claim.key.period or "未标注",
        scope=claim.key.scope or "未标注",
    )


def _key_label(key: DisplayClaimKey) -> str:
    return (
        f"实体：{key.entity or '未标注'}｜"
        f"指标：{key.metric or '未标注'}｜"
        f"期间：{key.period or '未标注'}｜"
        f"口径：{key.scope or '未标注'}"
    )
