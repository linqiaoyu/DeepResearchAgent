from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

AUDIT_STATUSES = ("PASS", "DEFECT", "UNCERTAIN")
PM_UNCERTAIN_SLOTS = {("Q04", 3), ("Q13", 3), ("Q20", 1)}
PM_PROMOTED_DEFECTS = {
    ("Q26", 1): "PM 将无公告/开工日期、却回填规划产能的槽位升格为 DEFECT。",
    ("Q29", 2): "PM 将无 2024 指引调整节点、却仅说明币种的槽位升格为 DEFECT。",
}

_NUMERIC_WITH_UNIT_RE = re.compile(
    r"(?P<number>(?<!\d)-?\d+(?:,\d{3})*(?:\.\d+)?)\s*"
    r"(?P<unit>%|pct|个百分点|亿元|万元|元|亿美元|亿欧元|港元|"
    r"GWh|GW|吉瓦时|亿千瓦时|万千瓦|万台|万辆|亿单|万单|条|个|家|起|件)",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_NARROW_PERIOD_RE = re.compile(
    r"(?:第?[一二三四1-4]季度|Q[1-4]|上半年|下半年|前三季度|1\s*[-—至]\s*10月)",
    re.IGNORECASE,
)
_SEGMENT_TERMS = ("手机部件", "汽车相关业务", "分部收入", "板块收入", "产品业务")
_QUALITATIVE_FACT_TERMS = ("成因", "原因", "口径", "区分", "机制", "路径")


@dataclass(frozen=True)
class CheckResult:
    status: str
    detail: str

    def __post_init__(self) -> None:
        if self.status not in AUDIT_STATUSES:
            raise ValueError(f"unsupported audit status: {self.status}")


@dataclass(frozen=True)
class AuditRow:
    question_id: str
    slot: int
    fact: str
    entity: CheckResult
    metric: CheckResult
    period: CheckResult
    scope_unit: CheckResult
    numeric_excerpt: CheckResult
    verdict: str
    note: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class GoldRefillRejected(ValueError):
    """Raised when a proposed gold value does not pass the shared four-key gate."""


class MetricNormalizer:
    def __init__(self, aliases: dict[str, str]) -> None:
        self.aliases = dict(aliases)
        self._ordered_aliases = sorted(self.aliases, key=len, reverse=True)

    @classmethod
    def from_path(cls, path: Path) -> MetricNormalizer:
        payload = json.loads(path.read_text(encoding="utf-8"))
        aliases = payload.get("metric_aliases", {})
        if not isinstance(aliases, dict):
            raise ValueError("finance metric normalization must contain metric_aliases")
        return cls({str(key): str(value) for key, value in aliases.items()})

    def metrics_in(self, text: str) -> set[str]:
        found: set[str] = set()
        remaining = text
        for alias in self._ordered_aliases:
            if alias in remaining:
                found.add(self.aliases[alias])
                remaining = remaining.replace(alias, " ")
        return found

    def normalize_many(self, metrics: Iterable[str]) -> set[str]:
        normalized: set[str] = set()
        for metric in metrics:
            normalized.add(self.aliases.get(metric, metric))
        return normalized


def audit_questions(
    payload: dict[str, Any],
    normalizer: MetricNormalizer,
) -> list[AuditRow]:
    rows: list[AuditRow] = []
    for question in payload.get("questions", []):
        for slot_index, slot in enumerate(question.get("gold", {}).get("must_include", []), 1):
            rows.append(audit_slot(question, slot, slot_index, normalizer))
    return rows


def audit_slot(
    question: dict[str, Any],
    slot: dict[str, Any],
    slot_index: int,
    normalizer: MetricNormalizer,
) -> AuditRow:
    qid = str(question.get("id", "UNKNOWN"))
    fact = str(slot.get("fact", ""))
    combined = _combined_evidence_text(slot)
    evidence_body = _evidence_body_text(slot)
    contract = slot.get("audit_contract")
    if contract is not None and not isinstance(contract, dict):
        raise ValueError(f"{qid}s{slot_index} audit_contract must be an object")

    entity = _check_entity(question, fact, combined, contract)
    metric = _check_metric(fact, evidence_body, contract, normalizer)
    period = _check_period(question, fact, slot, evidence_body, contract)
    scope_unit = _check_scope_unit(fact, combined, contract)
    numeric_excerpt = _check_numeric_excerpt(fact, slot, contract, normalizer)

    pm_override = PM_PROMOTED_DEFECTS.get((qid, slot_index))
    note = ""
    if pm_override and not contract:
        scope_unit = CheckResult("DEFECT", pm_override)
        note = pm_override

    decision = str((contract or {}).get("decision", ""))
    decision_note = str((contract or {}).get("decision_note", "")).strip()
    if decision:
        if decision != "PM_UNCERTAIN" or (qid, slot_index) not in PM_UNCERTAIN_SLOTS:
            raise ValueError(f"{qid}s{slot_index} has unsupported audit decision: {decision}")
        if not decision_note:
            raise ValueError(f"{qid}s{slot_index} PM_UNCERTAIN requires decision_note")
        period = CheckResult("UNCERTAIN", decision_note)
        note = decision_note

    checks = (entity, metric, period, scope_unit, numeric_excerpt)
    if any(item.status == "DEFECT" for item in checks):
        verdict = "DEFECT"
    elif any(item.status == "UNCERTAIN" for item in checks):
        verdict = "UNCERTAIN"
    else:
        verdict = "PASS"
    if not note:
        note = "; ".join(item.detail for item in checks if item.status != "PASS")
    return AuditRow(
        question_id=qid,
        slot=slot_index,
        fact=fact,
        entity=entity,
        metric=metric,
        period=period,
        scope_unit=scope_unit,
        numeric_excerpt=numeric_excerpt,
        verdict=verdict,
        note=note,
    )


def enforce_refill_gate(
    question: dict[str, Any],
    candidate: dict[str, Any],
    slot_index: int,
    normalizer: MetricNormalizer,
) -> AuditRow:
    """Validate a replacement with the same gate used by the full-set auditor."""
    row = audit_slot(question, candidate, slot_index, normalizer)
    if row.verdict == "DEFECT":
        raise GoldRefillRejected(
            f"{row.question_id}s{row.slot} rejected: "
            + "; ".join(
                item.detail
                for item in (
                    row.entity,
                    row.metric,
                    row.period,
                    row.scope_unit,
                    row.numeric_excerpt,
                )
                if item.status == "DEFECT"
            )
        )
    if row.verdict == "UNCERTAIN":
        contract = candidate.get("audit_contract", {})
        if (
            (row.question_id, row.slot) not in PM_UNCERTAIN_SLOTS
            or contract.get("decision") != "PM_UNCERTAIN"
            or not str(contract.get("decision_note", "")).strip()
        ):
            raise GoldRefillRejected(
                f"{row.question_id}s{row.slot} rejected: UNCERTAIN lacks an allowed PM note"
            )
    return row


def summarize_audit(rows: list[AuditRow]) -> dict[str, Any]:
    counts = {status: sum(row.verdict == status for row in rows) for status in AUDIT_STATUSES}
    return {
        "slots": len(rows),
        "counts": counts,
        "defect_slots": [_slot_key(row) for row in rows if row.verdict == "DEFECT"],
        "uncertain_slots": [_slot_key(row) for row in rows if row.verdict == "UNCERTAIN"],
    }


def render_audit_markdown(rows: list[AuditRow], *, title: str = "Golden four-key audit") -> str:
    summary = summarize_audit(rows)
    lines = [
        f"# {title}",
        "",
        (
            f"Slots: {summary['slots']} · PASS: {summary['counts']['PASS']} · "
            f"DEFECT: {summary['counts']['DEFECT']} · "
            f"UNCERTAIN: {summary['counts']['UNCERTAIN']}"
        ),
        "",
        "| QID | Slot | Verdict | Entity | Metric | Period | Scope / unit | Numeric in excerpt | Note |",
        "| --- | ---: | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.question_id,
                    str(row.slot),
                    row.verdict,
                    _format_check(row.entity),
                    _format_check(row.metric),
                    _format_check(row.period),
                    _format_check(row.scope_unit),
                    _format_check(row.numeric_excerpt),
                    _escape_table(row.note or "—"),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _check_entity(
    question: dict[str, Any],
    fact: str,
    combined: str,
    contract: dict[str, Any] | None,
) -> CheckResult:
    companies = [str(item) for item in question.get("companies", [])]
    expected = [str(item) for item in (contract or {}).get("entities", companies)]
    if contract:
        missing = [entity for entity in expected if entity not in combined]
        if missing:
            return CheckResult("DEFECT", f"候选证据缺少实体：{', '.join(missing)}")
        return CheckResult("PASS", f"实体匹配：{', '.join(expected) or '不适用'}")

    if "两家2024营收及归母净利润" in fact:
        missing = [entity for entity in companies if entity not in combined]
        if missing:
            return CheckResult("DEFECT", f"两家公司复合槽位缺少：{', '.join(missing)}")
    if re.match(r"^2024(?:营业总收入|营业收入|营收)", fact) and any(
        term in combined for term in _SEGMENT_TERMS
    ):
        return CheckResult("DEFECT", "集团总量槽位被分部/产品业务口径替代")
    present = [entity for entity in companies if entity in combined]
    if companies and not present:
        return CheckResult("PASS", "摘录未显式写出实体；未发现与题目实体冲突")
    return CheckResult("PASS", f"实体匹配：{', '.join(present) or '不适用'}")


def _check_metric(
    fact: str,
    combined: str,
    contract: dict[str, Any] | None,
    normalizer: MetricNormalizer,
) -> CheckResult:
    expected = normalizer.metrics_in(fact)
    if contract:
        declared = normalizer.normalize_many(str(item) for item in contract.get("metrics", []))
        if expected and declared and not expected.intersection(declared):
            return CheckResult(
                "DEFECT",
                f"候选声明指标 {sorted(declared)} 与槽位指标 {sorted(expected)} 不匹配",
            )
        required = declared or expected
    else:
        required = expected
    observed = normalizer.metrics_in(combined)
    if required and observed and not required.intersection(observed):
        return CheckResult(
            "DEFECT",
            f"指标不匹配：要求 {sorted(required)}，摘录为 {sorted(observed)}",
        )
    if contract and required and not required.issubset(observed):
        missing = sorted(required - observed)
        return CheckResult("DEFECT", f"候选证据缺少声明指标：{missing}")
    if required:
        return CheckResult("PASS", f"归一指标匹配：{sorted(required.intersection(observed) or required)}")
    return CheckResult("PASS", "非归一表数值指标/定性槽位")


def _check_period(
    question: dict[str, Any],
    fact: str,
    slot: dict[str, Any],
    combined: str,
    contract: dict[str, Any] | None,
) -> CheckResult:
    value = str(slot.get("value", ""))
    anchor = str(question.get("time_anchor", ""))
    qid = str(question.get("id", ""))

    if contract:
        period = contract.get("period", {})
        if not isinstance(period, dict):
            return CheckResult("DEFECT", "audit_contract.period 必须为对象")
        kind = str(period.get("kind", ""))
        year = period.get("year")
        if year is not None and str(year) not in combined:
            return CheckResult("DEFECT", f"候选证据缺少报告期年份 {year}")
        if kind == "annual" and _NARROW_PERIOD_RE.search(value):
            return CheckResult("DEFECT", "年度槽位被单季/半年/前三季/非全年区间替代")
        if kind == "quarters":
            required = [str(item) for item in period.get("quarter_tokens", [])]
            missing = [token for token in required if token not in combined]
            if missing:
                return CheckResult("DEFECT", f"逐季槽位缺少期间：{', '.join(missing)}")
        if kind == "events":
            required = [str(item) for item in period.get("event_tokens", [])]
            missing = [token for token in required if token not in combined]
            if missing:
                return CheckResult("DEFECT", f"事件槽位缺少时点：{', '.join(missing)}")
        return CheckResult("PASS", f"报告期匹配：{period.get('label', kind or '已声明')}")

    period_text = value if _YEAR_RE.search(value) or _NARROW_PERIOD_RE.search(value) else combined
    years = [int(item) for item in _YEAR_RE.findall(period_text)]
    qualitative = any(term in fact for term in _QUALITATIVE_FACT_TERMS)
    annual_required = (
        ("财年" in anchor and "逐季" not in anchor)
        or "年度统计" in anchor
        or "2024全球装机量" in fact
    )
    if annual_required and _NARROW_PERIOD_RE.search(value):
        status = "UNCERTAIN" if qualitative else "DEFECT"
        return CheckResult(status, "年度槽位出现单季/半年/前三季/非全年区间")
    if annual_required and years and years[0] != 2024:
        status = "UNCERTAIN" if qualitative else "DEFECT"
        return CheckResult(status, f"年度槽位首个报告期为 {years[0]}，要求 2024")

    if "2024财年逐季" in anchor and years and years[0] != 2024:
        return CheckResult("DEFECT", f"2024 逐季槽位首个报告期为 {years[0]}")

    if (qid, int(slot.get("_slot_index", 0) or 0)) in PM_PROMOTED_DEFECTS:
        return CheckResult("DEFECT", PM_PROMOTED_DEFECTS[(qid, int(slot["_slot_index"]))])

    if anchor == "2024-01至2025-12":
        in_window = [year for year in years if year in {2024, 2025}]
        outside = [year for year in years if year not in {2024, 2025}]
        if outside and not in_window:
            return CheckResult("DEFECT", f"关键事实年份 {outside[0]} 超出 2024-2025 窗口")
        if outside and in_window:
            return CheckResult("UNCERTAIN", "证据混入 2024-2025 窗口外背景年份")
    if anchor == "2024自然年" and years and years[0] != 2024:
        return CheckResult("DEFECT", f"关键事实年份 {years[0]} 与 2024 自然年不匹配")
    return CheckResult("PASS", f"报告期与 time_anchor 匹配或无显式冲突：{anchor}")


def _check_scope_unit(
    fact: str,
    combined: str,
    contract: dict[str, Any] | None,
) -> CheckResult:
    if not contract:
        return CheckResult("PASS", "未发现累计/单季、范围或单位的显式冲突")
    scope_terms = [str(item) for item in contract.get("scope_terms", [])]
    missing_scope = [term for term in scope_terms if term not in combined]
    if missing_scope:
        return CheckResult("DEFECT", f"候选证据缺少口径：{', '.join(missing_scope)}")
    units = [str(item) for item in contract.get("units", [])]
    missing_units = [unit for unit in units if unit.lower() not in combined.lower()]
    if missing_units:
        return CheckResult("DEFECT", f"候选证据缺少单位：{', '.join(missing_units)}")
    dimension = str(contract.get("dimension", ""))
    if dimension == "单季" and "单季" not in combined and not re.search(r"第?[一二三四]季度", combined):
        return CheckResult("DEFECT", "候选证据未证明单季口径")
    if dimension == "累计" and not any(term in combined for term in ("累计", "全年", "年度")):
        return CheckResult("DEFECT", "候选证据未证明累计/全年口径")
    return CheckResult("PASS", f"口径/单位匹配：{dimension or '已声明'} / {units or ['语义']}")


def _check_numeric_excerpt(
    fact: str,
    slot: dict[str, Any],
    contract: dict[str, Any] | None,
    normalizer: MetricNormalizer,
) -> CheckResult:
    extracts = _source_extracts(slot)
    normalized_extract = _normalize_numeric_text(" ".join(extracts))
    if contract:
        tokens = [str(item) for item in contract.get("numeric_tokens", [])]
        missing = [token for token in tokens if _normalize_numeric_text(token) not in normalized_extract]
        if missing:
            return CheckResult("DEFECT", f"来源摘录未包含候选数字：{', '.join(missing)}")
        return CheckResult("PASS", f"候选数字均在摘录内：{', '.join(tokens) or '无数值'}")

    value = str(slot.get("value", ""))
    tokens = [match.group("number") for match in _NUMERIC_WITH_UNIT_RE.finditer(value)]
    missing = [token for token in tokens if _normalize_numeric_text(token) not in normalized_extract]
    if missing and normalizer.metrics_in(fact):
        status = "UNCERTAIN" if any(term in fact for term in _QUALITATIVE_FACT_TERMS) else "DEFECT"
        return CheckResult(status, f"来源摘录未包含值中的指标数字：{', '.join(missing)}")
    return CheckResult("PASS", f"数值在摘录内：{', '.join(tokens) or '无强制数值'}")


def _combined_evidence_text(slot: dict[str, Any]) -> str:
    refs = _source_refs(slot)
    parts = [str(slot.get("value", "")), str(slot.get("source", ""))]
    for ref in refs:
        parts.extend(
            [
                str(ref.get("source_title", "")),
                str(ref.get("extract_text", "")),
            ]
        )
    return " ".join(part for part in parts if part)


def _evidence_body_text(slot: dict[str, Any]) -> str:
    parts = [str(slot.get("value", ""))]
    parts.extend(_source_extracts(slot))
    return " ".join(part for part in parts if part)


def _source_refs(slot: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    primary = slot.get("source_ref")
    if isinstance(primary, dict):
        refs.append(primary)
    additional = slot.get("source_refs", [])
    if isinstance(additional, list):
        for ref in additional:
            if isinstance(ref, dict) and ref not in refs:
                refs.append(ref)
    return refs


def _source_extracts(slot: dict[str, Any]) -> list[str]:
    return [str(ref.get("extract_text", "")) for ref in _source_refs(slot)]


def _normalize_numeric_text(text: str) -> str:
    return text.replace(",", "").replace("，", "").replace(" ", "").lower()


def _slot_key(row: AuditRow) -> str:
    return f"{row.question_id}s{row.slot}"


def _format_check(check: CheckResult) -> str:
    return _escape_table(f"{check.status}: {check.detail}")


def _escape_table(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
