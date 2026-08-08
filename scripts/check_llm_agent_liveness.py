"""Prove the LLM extractor and reporter actually ran instead of falling back.

Two independent guards live here because the R073-R089 failure needed both to
be absent to stay hidden for fifteen rounds:

``--self-test``
    Offline. Drives the real :class:`LLMClient` with a provider stub that
    truncates at ``max_tokens`` exactly like a real one, using the real role
    configs and the real ``ExtractedClaims``/``ReportDraft`` schemas. A
    completion cap too small for a role's schema fails here, with no API key
    and no spend.

``<package>``
    Measures a delivered research package: whether either LLM agent degraded to
    its deterministic fallback, whether any structured call was truncated, and
    how many reader-visible claims the reporter actually authored rather than
    assembled mechanically from structured records.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deepresearch_agent.llm.client import (  # noqa: E402
    LLMClient,
    StructuredOutputTruncatedError,
)
from deepresearch_agent.llm_config import DEFAULT_LLM_CONFIG  # noqa: E402
from deepresearch_agent.schemas import ExtractedClaims, ReportDraft  # noqa: E402

#: Mechanically assembled findings are the fallback's signature, not the
#: reporter LLM's output.
MECHANICAL_PROVENANCE = "mechanical_grounded_fact"
DEFAULT_MIN_AUTHORED_CLAIMS = 3
#: Measured, not estimated. The first live run that reached a provider (R091,
#: `_collab/091/evidence/liveness_attempt1.log`) recorded both the extractor and
#: the reporter emitting exactly 4096 completion tokens with
#: `finish_reason=length` -- they wanted more. R090's hand-built reference
#: payloads came to 1487 and 1230 tokens, so the guard went green while
#: production truncated on every call. A role's cap must clear what production
#: was measured to need, with headroom.
MEASURED_TRUNCATION_TOKENS = 4096
REQUIRED_CAP_HEADROOM = 2
#: `ReporterAgent._render_llm_report` renders at most three analysis claims per
#: sub-question and drops those unrelated to the key findings, so a depth-1
#: single-sub-question topic has a ceiling of three. The floor is what proves
#: the reader receives authored analysis at all; the R086/R087 baseline is zero.
DEFAULT_MIN_READER_ANALYSIS_LINES = 2


def _estimate_tokens(text: str) -> int:
    """Deterministic offline proxy for provider tokenization.

    CJK codepoints bill at roughly one token each and Latin text at roughly one
    token per four characters. The proxy only has to be stable and not
    optimistic; it stands in for a tokenizer the offline gate cannot call.
    """

    cjk = sum(1 for char in text if "㐀" <= char <= "鿿" or "＀" <= char <= "￯")
    return cjk + (len(text) - cjk + 3) // 4


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    if _estimate_tokens(text) <= max_tokens:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if _estimate_tokens(text[:mid]) <= max_tokens:
            low = mid
        else:
            high = mid - 1
    return text[:low]


class TruncatingProvider:
    """Provider stub that enforces ``max_tokens`` the way a real one does."""

    def __init__(self, payload: str) -> None:
        self.payload = payload

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        max_tokens = int(kwargs.get("max_tokens") or 0)
        content = _truncate_to_tokens(self.payload, max_tokens) if max_tokens else self.payload
        completion_tokens = _estimate_tokens(content)
        truncated = completion_tokens >= max_tokens > 0 and content != self.payload
        return {
            "choices": [
                {
                    "message": {"content": content},
                    "finish_reason": "length" if truncated else "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": completion_tokens,
                "total_tokens": 100 + completion_tokens,
            },
        }


def _evidence_id(index: int) -> str:
    return f"3f2a{index:04d}-0000-5000-8000-00000000{index:04d}"


def reference_extractor_payload() -> str:
    """One verbatim claim per admitted source, at the observed source count.

    ``prompts/extractor.md`` asks for a claim per relevant source with a
    verbatim ``extract_text`` and filled ``numeric_fields``; the R087 live run
    admitted eight RAG sources (``rag_sources_admitted=8``). Eight claims is
    therefore the contract's own floor, not a target chosen to fail a cap.
    """

    claims = [
        {
            "claim": f"公司在报告期内披露了第{index + 1}项与该子问题直接相关的经营数据。",
            "claim_type": "data",
            "source_url": (
                "https://www.sec.gov/Archives/edgar/data/1736541/000141057825000661/"
                f"nio-20241231x20f.htm#chunk={_evidence_id(index)}"
            ),
            "extract_text": (
                "Total revenues were RMB65,731.6 million (US$9,004.8 million) in 2024, "
                "representing an increase of 18.2% from 2023, primarily attributable to "
                "the increase in vehicle delivery volume and the expansion of "
                f"other sales, as further described in note {index + 1}."
            ),
            "confidence": 0.82,
            "numeric_fields": {
                "entity": "NIO Inc.",
                "metric_name": "营业收入",
                "period": "2024-12-31",
                "dimension": "年度",
                "value": "65731559000",
                "unit": "CNY",
            },
        }
        for index in range(8)
    ]
    return json.dumps({"claims": claims}, ensure_ascii=False)


def reference_reporter_payload() -> str:
    """A report at the upper bound of the reporter's own output contract.

    ``prompts/reporter.md`` asks for 3-6 key findings plus a ``detailed_analysis``
    that explains support, implications, contradictions and limits without
    repeating the findings, plus risks and unverified assumptions, over up to 18
    evidence entries. Six findings, three sections and cited risks is that
    contract's upper bound -- and still smaller than what the R087 reporter was
    already emitting when the 1024-token cap cut it off mid-object.
    """

    def claim(text: str, index: int) -> dict[str, Any]:
        return {"text": text, "evidence_ids": [_evidence_id(index)]}

    findings = [
        "2024 财年营业收入为 657.32 亿元，较上一财年增长约 18%，增量主要来自整车交付量提升。",
        "2024 财年毛利为 64.93 亿元，对应毛利率约 9.9%，较上一财年回升但仍低于行业整体水平。",
        "毛利率回升同时受到单车成本下降与其他销售业务占比上升两个方向的影响。",
        "整车销售毛利率与公司整体毛利率之间存在差值，两者不可互相替代使用。",
        "其他销售收入的同比增速高于整车销售，收入结构较上一财年发生可观察的变化。",
        "研发与销售费用的绝对额继续上升，因此毛利改善并未同比例传导到经营利润。",
    ]
    sections = [
        (
            "营收结构与增长来源",
            [
                "整车销售仍是收入主体，其他销售的增速高于整车销售，改变了收入结构的构成比例。",
                "年报披露的交付量与平均售价变化共同解释了收入增量，两者方向并不一致。",
                "分季度看，下半年交付量占全年比重更高，全年同比增速掩盖了期内波动。",
            ],
        ),
        (
            "毛利驱动因素",
            [
                "毛利改善主要来自材料成本与制造费用摊薄，而非售价提升。",
                "电池采购成本的下行是单车成本下降中可从披露文本直接归因的部分。",
                "产能利用率提升对单位固定成本的摊薄作用在披露文本中有定性但无定量说明。",
            ],
        ),
        (
            "口径限制与可比性",
            [
                "结构化接口的毛利口径与年报分部口径存在差异，跨期比较需要保持同一口径。",
                "以人民币列报的金额与美元折算金额使用不同汇率基准，不应混用。",
                "上一财年数据在本次年报中经过重述，与上一版年报披露值并不完全一致。",
            ],
        ),
    ]
    index = 0
    key_findings = []
    for text in findings:
        key_findings.append(claim(text, index))
        index += 1
    detailed_analysis = []
    for heading, texts in sections:
        section_claims = []
        for text in texts:
            section_claims.append(claim(text, index))
            index += 1
        detailed_analysis.append(
            {"sub_question_id": "rev", "heading": heading, "claims": section_claims}
        )
    draft = {
        "summary": (
            "本报告围绕蔚来 2024 财年的营收与毛利表现展开，结合公司 20-F 年报披露的"
            "分部数据与结构化财务接口的口径核对，说明收入增长的主要来源、毛利率变化的"
            "驱动因素，以及与上一财年相比的可比性限制；结论仅覆盖公开披露口径。"
        ),
        "key_findings": key_findings,
        "detailed_analysis": detailed_analysis,
        "risks": [
            "口径差异：结构化接口与年报文本对毛利的定义不完全一致，直接比较可能失真。",
            "覆盖限制：本报告仅使用公开披露文件，不包含未公开的分部成本明细。",
            "时点限制：披露文件发布后的经营变化不在本报告的观察窗口内。",
            "汇率影响：以美元折算的金额随汇率变动，与人民币口径的同比结论可能不一致。",
        ],
        "unverified_assumptions": [
            claim("其他销售业务的毛利率高于整车销售的假设未在披露文件中直接给出。", index),
            claim("产能利用率提升对毛利率的贡献幅度在披露文本中没有定量支持。", index + 1),
            claim("电池采购价格的后续走势属于前瞻判断，不由本期披露文件支持。", index + 2),
        ],
    }
    return json.dumps(draft, ensure_ascii=False)


@dataclass(frozen=True)
class RoleProbe:
    role: str
    schema: type
    payload: str


def _role_probes() -> tuple[RoleProbe, ...]:
    return (
        RoleProbe("extractor", ExtractedClaims, reference_extractor_payload()),
        RoleProbe("reporter", ReportDraft, reference_reporter_payload()),
    )


def _measured_floor() -> int:
    """The cap a role must clear, taken from measured production output."""

    return MEASURED_TRUNCATION_TOKENS * REQUIRED_CAP_HEADROOM


def self_test(tmp_root: Path) -> int:
    failures: list[str] = []
    # The stub provider never leaves the process; a placeholder satisfies the
    # client's credential precondition without touching the real .env.
    env_path = tmp_root / ".env"
    env_path.write_text(
        "DEEPSEEK_API_KEY=placeholder-self-test\nDASHSCOPE_API_KEY=placeholder-self-test\n",
        encoding="utf-8",
    )
    for probe in _role_probes():
        role_config = DEFAULT_LLM_CONFIG.roles[probe.role]
        cap = role_config.max_completion_tokens
        needed = _estimate_tokens(probe.payload)
        client = LLMClient(
            ledger_path=tmp_root / f"{probe.role}.jsonl",
            global_ledger_path=tmp_root / "global.jsonl",
            budget_cny=10.0,
            completion_func=TruncatingProvider(probe.payload),
            env_path=tmp_root / ".env",
        )
        status = "ok"
        try:
            result = client.complete(
                role=probe.role,
                run_id=f"self-test-{probe.role}",
                messages=[{"role": "user", "content": "reference"}],
                schema=probe.schema,
            )
            if not isinstance(result.parsed, probe.schema):
                status = "unparsed"
        except StructuredOutputTruncatedError:
            status = "truncated"
        floor = _measured_floor()
        print(
            f"role={probe.role} max_completion_tokens={cap} "
            f"reference_tokens={needed} measured_floor={floor} status={status}"
        )
        if status != "ok":
            failures.append(
                f"{probe.role}: max_completion_tokens={cap} cannot carry its own schema "
                f"(reference response needs ~{needed} tokens, status={status})"
            )
        if cap < floor:
            failures.append(
                f"{probe.role}: max_completion_tokens={cap} is below the measured floor "
                f"{floor} (production emitted {MEASURED_TRUNCATION_TOKENS} and was cut off)"
            )

    # A truncating provider must still be *detected* as truncating; a classifier
    # that never fires would make the check above vacuous.
    probe = _role_probes()[1]
    detector = LLMClient(
        ledger_path=tmp_root / "detector.jsonl",
        global_ledger_path=tmp_root / "detector-global.jsonl",
        budget_cny=10.0,
        completion_func=TruncatingProvider(probe.payload),
        env_path=tmp_root / ".env",
        config=_config_with_cap("reporter", 64),
    )
    detected = False
    try:
        detector.complete(
            role="reporter",
            run_id="self-test-detector",
            messages=[{"role": "user", "content": "reference"}],
            schema=probe.schema,
        )
    except StructuredOutputTruncatedError:
        detected = True
    print(f"truncation_detected_at_cap_64={str(detected).lower()}")
    if not detected:
        failures.append("truncation classifier did not fire at a 64-token cap")

    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    print(f"self_test_failures={len(failures)}")
    return 1 if failures else 0


def _config_with_cap(role: str, cap: int) -> Any:
    from dataclasses import replace

    roles = dict(DEFAULT_LLM_CONFIG.roles)
    roles[role] = replace(roles[role], max_completion_tokens=cap)
    return replace(DEFAULT_LLM_CONFIG, roles=roles)


@dataclass(frozen=True)
class PackageMeasurement:
    extractor_fallback: int
    reporter_fallback: int
    structured_parse_errors: int | None
    truncated_calls: int | None
    llm_authored_claims: int
    reader_analysis_lines: int
    orphan_footnotes: int

    def as_line(self) -> str:
        def show(value: int | None) -> str:
            return "unavailable" if value is None else str(value)

        return (
            f"extractor_fallback={self.extractor_fallback} "
            f"reporter_fallback={self.reporter_fallback} "
            f"structured_parse_errors={show(self.structured_parse_errors)} "
            f"truncated_calls={show(self.truncated_calls)} "
            f"llm_authored_claims={self.llm_authored_claims} "
            f"reader_analysis_lines={self.reader_analysis_lines} "
            f"orphan_footnotes={self.orphan_footnotes}"
        )


def measure_report(report: str) -> tuple[int, int]:
    """Count what the reader receives, not what the pipeline produced.

    ``llm_authored_claims`` is a pipeline property: R087 showed a package can
    record authored claims that the finance compaction step then deletes before
    rendering. ``reader_analysis_lines`` counts cited bullets that survive into
    ``## 详细分析`` in the delivered report.

    ``orphan_footnotes`` counts references listed under ``## 参考来源`` that no
    line of the report body ever cites. It is reported, not enforced, this
    round.
    """

    body, _, references = report.partition("## 参考来源")
    analysis = re.search(r"(?ms)^## 详细分析\s*$\n?(.*?)(?=^## |\Z)", body)
    reader_analysis_lines = 0
    if analysis:
        reader_analysis_lines = sum(
            1
            for line in analysis.group(1).splitlines()
            if line.strip().startswith("- ") and re.search(r"\[\^\d+\]", line)
        )
    cited = set(re.findall(r"\[\^(\d+)\]", body))
    listed = set(re.findall(r"(?m)^\[\^(\d+)\]:", references))
    return reader_analysis_lines, len(listed - cited)


def measure_package(
    package: Path,
    *,
    llm_ledger: Path | None = None,
) -> PackageMeasurement:
    ledger = json.loads((package / "audit_bundle" / "ledger.json").read_text(encoding="utf-8"))
    stats = ledger.get("llm_stats") or {}

    extractor_entries = stats.get("extractor") or []
    if isinstance(extractor_entries, dict):
        extractor_entries = [extractor_entries]
    extractor_fallback = sum(1 for entry in extractor_entries if entry.get("fallback"))

    reporter = stats.get("reporter") or {}
    reporter_fallback = 1 if reporter.get("fallback") else 0

    authored = 0
    for entry in reporter.get("claim_provenance") or []:
        if entry.get("provenance") == MECHANICAL_PROVENANCE:
            continue
        if not entry.get("has_citation"):
            continue
        if int(entry.get("invalid_reference_count") or 0):
            continue
        authored += 1

    structured = ledger.get("structured_output")
    parse_errors: int | None = None
    truncated: int | None = None
    if isinstance(structured, dict) and structured:
        parse_errors = int(structured.get("structured_parse_errors") or 0)
        truncated = int(structured.get("truncated_calls") or 0)
    elif llm_ledger is not None:
        parse_errors, truncated = _from_global_ledger(package, llm_ledger)

    report_path = package / "report.md"
    reader_analysis_lines, orphan_footnotes = (
        measure_report(report_path.read_text(encoding="utf-8"))
        if report_path.exists()
        else (0, 0)
    )

    return PackageMeasurement(
        extractor_fallback=extractor_fallback,
        reporter_fallback=reporter_fallback,
        structured_parse_errors=parse_errors,
        truncated_calls=truncated,
        llm_authored_claims=authored,
        reader_analysis_lines=reader_analysis_lines,
        orphan_footnotes=orphan_footnotes,
    )


def _is_live(package: Path) -> bool:
    ledger = json.loads((package / "audit_bundle" / "ledger.json").read_text(encoding="utf-8"))
    return ledger.get("mode") == "llm"


def _from_global_ledger(package: Path, llm_ledger: Path) -> tuple[int, int]:
    """Reconstruct structured-call health for packages written before R090.

    Historical packages are immutable, so their embedded ledger cannot gain the
    new counters; the run id links them to the append-only global ledger.
    """

    run_ids = {
        json.loads(manifest.read_text(encoding="utf-8")).get("run_id")
        for manifest in package.glob("runs/*/manifest.json")
    }
    parse_errors = 0
    truncated = 0
    with llm_ledger.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("run_id") not in run_ids or not row.get("structured"):
                continue
            if row.get("parse_error"):
                parse_errors += 1
            if row.get("truncated") or (
                row.get("parse_error") and row.get("truncated") is None
            ):
                truncated += 1
    return parse_errors, truncated


def check_package(
    package: Path,
    *,
    min_authored_claims: int,
    llm_ledger: Path | None,
    min_reader_analysis_lines: int = DEFAULT_MIN_READER_ANALYSIS_LINES,
) -> int:
    measurement = measure_package(package, llm_ledger=llm_ledger)
    print(measurement.as_line())
    failures: list[str] = []
    if measurement.extractor_fallback:
        failures.append("extractor degraded to its deterministic fallback")
    if measurement.reporter_fallback:
        failures.append("reporter degraded to its mechanical fallback")
    if measurement.structured_parse_errors:
        failures.append(
            f"{measurement.structured_parse_errors} structured call(s) failed to parse"
        )
    if measurement.truncated_calls:
        failures.append(f"{measurement.truncated_calls} structured call(s) were truncated")
    if measurement.structured_parse_errors is None and _is_live(package):
        # A package produced after R090 carries its own structured-output
        # health. Missing counters on a live package means the evidence for
        # "no call was truncated" does not exist, which must not read as zero.
        failures.append("structured-output health is unavailable for a live package")
    if measurement.llm_authored_claims < min_authored_claims:
        failures.append(
            f"only {measurement.llm_authored_claims} LLM-authored cited claim(s), "
            f"need >= {min_authored_claims}"
        )
    if measurement.reader_analysis_lines < min_reader_analysis_lines:
        failures.append(
            f"only {measurement.reader_analysis_lines} cited analysis line(s) reach the "
            f"reader, need >= {min_reader_analysis_lines}"
        )
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--min-authored-claims",
        type=int,
        default=DEFAULT_MIN_AUTHORED_CLAIMS,
    )
    parser.add_argument(
        "--min-reader-analysis-lines",
        type=int,
        default=DEFAULT_MIN_READER_ANALYSIS_LINES,
    )
    parser.add_argument(
        "--llm-ledger",
        type=Path,
        default=None,
        help="Reconstruct structured-call health for pre-R090 packages.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            return self_test(Path(tmp))

    if args.package is None:
        parser.error("a package path or --self-test is required")
    return check_package(
        args.package,
        min_authored_claims=args.min_authored_claims,
        llm_ledger=args.llm_ledger,
        min_reader_analysis_lines=args.min_reader_analysis_lines,
    )


if __name__ == "__main__":
    raise SystemExit(main())
