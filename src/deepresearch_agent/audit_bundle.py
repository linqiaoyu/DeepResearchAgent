from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from deepresearch_agent.provenance import (
    FLAG_CLASSIFICATIONS,
    RunManifest,
    settings_flag_snapshot,
)
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.security import redact
from deepresearch_agent.settings import Settings
from deepresearch_agent.structured_output import (
    render_structured_json,
    render_structured_markdown,
    write_structured_table,
)

_CITATION_RE = re.compile(r"\[\^(\d+)\]")
_BOUNDARY = (
    "本报告由自动化系统生成，不构成投资建议；前瞻性陈述已归入未验证假设；"
    "证据截至日为 {as_of}；系统已知局限见 docs/production_readiness.md。"
)
PUBLIC_EXCERPT_CHAR_LIMIT = 1_000


class AuditBundleError(ValueError):
    def __init__(self, missing_evidence_ids: list[str]) -> None:
        self.missing_evidence_ids = sorted(set(missing_evidence_ids))
        super().__init__(
            "audit bundle citation closure failed; missing evidence ids: "
            + ", ".join(self.missing_evidence_ids)
        )


def export_audit_bundle(
    *,
    state: ResearchState,
    settings: Settings,
    manifest: RunManifest,
    output_dir: Path,
) -> dict[str, Any]:
    report_claims = extract_report_claims(state)
    available_ids = {item.id for item in state.evidence_store}
    referenced_ids = {
        evidence_id
        for claim in report_claims
        for evidence_id in claim["evidence_ids"]
    }
    structured_ids = _structured_evidence_ids(state)
    missing = sorted((referenced_ids | structured_ids) - available_ids)
    if missing:
        raise AuditBundleError(missing)

    output_dir.mkdir(parents=True, exist_ok=False)
    source_credibility = {source.url: source.credibility for source in state.sources}
    evidence_payload = [
        {
            "evidence_id": item.id,
            "source_url": item.source_url,
            "source_pub_date": (
                item.source_pub_date.isoformat() if item.source_pub_date else None
            ),
            "report_period_end": (
                item.report_period_end.isoformat() if item.report_period_end else None
            ),
            "source_date_unknown_reason": item.source_date_unknown_reason,
            "retrieval_ref": (
                item.retrieval_ref.model_dump(mode="json")
                if item.retrieval_ref is not None
                else None
            ),
            "captured_at": item.extracted_at.isoformat(),
            "extract_text": item.extract_text[
                :PUBLIC_EXCERPT_CHAR_LIMIT
            ],
            "extract_sha256": hashlib.sha256(
                item.extract_text.encode("utf-8")
            ).hexdigest(),
            "extract_truncated": (
                len(item.extract_text) > PUBLIC_EXCERPT_CHAR_LIMIT
            ),
            "source_tier": item.source_tier,
            "source_content_truncated": item.content_truncated,
            "credibility": source_credibility.get(item.source_url, item.confidence),
            "structured_record": (
                item.structured_record.model_dump(mode="json")
                if item.structured_record is not None
                else None
            ),
        }
        for item in sorted(state.evidence_store, key=lambda item: item.id)
        if item.id in referenced_ids
    ]
    report_payload = {
        "research_id": state.research_id,
        "question": state.topic,
        "report_markdown": state.final_report or "",
        "claims": report_claims,
    }
    ledger_payload = _accounting_payload(state, settings)
    manifest_payload = manifest.model_dump(mode="json")
    manifest_payload["flags"] = settings_flag_snapshot(
        settings,
        include_disabled_experimental=True,
    )
    manifest_payload["flag_classifications"] = {
        flag: FLAG_CLASSIFICATIONS.get(flag, "content_affecting")
        for flag in sorted(manifest_payload["flags"])
    }
    manifest_payload["token_total_estimated"] = ledger_payload[
        "token_total_estimated"
    ]
    manifest_payload["token_total_source"] = ledger_payload["token_total_source"]
    manifest_payload["cost_cny_total"] = ledger_payload["cost_cny"]
    manifest_payload["cost_cny_total_estimated"] = ledger_payload[
        "cost_cny_estimated"
    ]
    manifest_payload["cost_cny_total_source"] = ledger_payload["cost_cny_source"]

    _write_text(output_dir / "report.md", state.final_report or "")
    _write_json(output_dir / "report.json", report_payload)
    _write_json(output_dir / "evidence.json", evidence_payload)
    _write_json(output_dir / "manifest.json", manifest_payload)
    _write_json(output_dir / "ledger.json", ledger_payload)
    _write_text(
        output_dir / "cover.md",
        _cover(
            state=state,
            report_claims=report_claims,
            cited_evidence_count=len(evidence_payload),
            accounting=ledger_payload,
        ),
    )
    if state.structured_output is not None:
        structured_output = type(state.structured_output).model_validate(
            _redact_json_values(state.structured_output.model_dump(mode="json"))
        )
        _write_text(
            output_dir / "structured.json",
            render_structured_json(structured_output),
        )
        _write_text(
            output_dir / "structured.md",
            render_structured_markdown(structured_output),
        )
        write_structured_table(structured_output, output_dir / "structured")

    files = sorted(path.name for path in output_dir.iterdir() if path.is_file())
    return {
        "citation_closure": "ok",
        "claim_count": len(report_claims),
        "referenced_evidence_count": len(referenced_ids),
        "files": files,
        "sha256": _directory_sha256(output_dir),
    }


def extract_report_claims(state: ResearchState) -> list[dict[str, Any]]:
    evidence_by_id = {item.id: item for item in state.evidence_store}
    footnotes = {
        number: evidence_by_id[evidence_id]
        for number, evidence_id in state.report_footnote_evidence.items()
        if evidence_id in evidence_by_id
    }
    claims: list[dict[str, Any]] = []
    section = ""
    for line in (state.final_report or "").splitlines():
        if line.startswith("## "):
            section = line.removeprefix("## ").strip()
            continue
        if not line.startswith("- "):
            continue
        evidence_ids: list[str] = []
        for match in _CITATION_RE.findall(line):
            number = int(match)
            evidence = footnotes.get(number)
            evidence_ids.append(evidence.id if evidence else f"footnote:{number}")
        claims.append(
            {
                "section": section,
                "text": _CITATION_RE.sub("", line.removeprefix("- ")).strip(),
                "evidence_ids": evidence_ids,
            }
        )
    return claims


def _structured_evidence_ids(state: ResearchState) -> set[str]:
    output = state.structured_output
    if output is None:
        return set()
    ids: set[str] = set()
    for row in output.comparison_table.rows:
        ids.update(row.evidence_ids)
    for row in output.event_timeline.events:
        ids.update(row.evidence_ids)
    for row in output.risk_matrix.risks:
        ids.update(row.evidence_ids)
    return ids


def _cover(
    *,
    state: ResearchState,
    report_claims: list[dict[str, Any]],
    cited_evidence_count: int,
    accounting: dict[str, Any],
) -> str:
    data_as_of = max(
        (item.source_pub_date for item in state.evidence_store if item.source_pub_date),
        default=None,
    )
    as_of = data_as_of.isoformat() if data_as_of else "未标注"
    uncited_claims = sum(1 for claim in report_claims if not claim["evidence_ids"])
    if accounting["mode"] == "deterministic":
        cost_disclosure = (
            "- 成本：本次为 deterministic fixture 运行，未产生真实 API "
            "账单；ledger 中 USD 数值为模拟估算并已显式标注。"
        )
    else:
        cost_disclosure = (
            "- 成本：ledger 数值来自 token 用量与配置价格的估算，"
            "不是供应商最终账单；具体来源与性质见 ledger.json。"
        )
    return "\n".join(
        [
            "# 审计包封面",
            "",
            f"- 研究问题：{state.topic}",
            f"- 结论摘要：{_report_summary(state.final_report or '')}",
            f"- 证据统计：引用证据 {cited_evidence_count} 条；报告 claim {len(report_claims)} 条；无引用 claim {uncited_claims} 条。",
            cost_disclosure,
            "- 已知局限：仅覆盖包内公开/fixture 证据；不含非公开数据、实时行情或人工投资判断。",
            "",
            "## 能力边界声明",
            "",
            _BOUNDARY.format(as_of=as_of),
            "",
        ]
    )


def _accounting_payload(
    state: ResearchState,
    settings: Settings,
) -> dict[str, Any]:
    usage = state.metadata.get("llm_usage", {})
    llm_usage = usage if isinstance(usage, dict) else {}
    deterministic = settings.execution_mode == "deterministic"
    cost_cny = llm_usage.get("total_cost_cny")
    price_source = llm_usage.get("price_source")
    return {
        "token_total": state.token_used,
        "token_total_estimated": deterministic,
        "token_total_source": (
            "deterministic_simulation"
            if deterministic
            else "provider_usage_via_llm_ledger"
        ),
        "cost_usd": state.cost_used,
        "cost_usd_estimated": True,
        "cost_usd_source": (
            "deterministic_simulation"
            if deterministic
            else f"llm_ledger_display_conversion:{price_source or 'unavailable'}"
        ),
        "cost_cny": cost_cny,
        "cost_cny_estimated": cost_cny is not None,
        "cost_cny_source": (
            "unavailable_no_api_billing"
            if deterministic
            else str(price_source or "unavailable")
        ),
        "provider_invoice_available": False,
        "mode": settings.execution_mode,
        "llm_stats": state.metadata.get("llm_stats", {}),
    }


def _report_summary(report: str) -> str:
    lines = report.splitlines()
    try:
        start = lines.index("## 摘要") + 1
    except ValueError:
        start = 0
    for line in lines[start:]:
        if line.strip() and not line.startswith("#"):
            return line.strip()
    return "未生成摘要"


def _write_json(path: Path, payload: Any) -> None:
    _write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _write_text(path: Path, content: str) -> None:
    path.write_text(redact(content).rstrip() + "\n", encoding="utf-8")


def _redact_json_values(value: Any) -> Any:
    """Redact string leaves without mutating JSON escape syntax."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_json_values(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_json_values(item) for key, item in value.items()}
    return value


def _directory_sha256(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.iterdir() if item.is_file()):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
