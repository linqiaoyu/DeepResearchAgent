"""Check 087 README flags and the verbatim final-package report embedding."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

from deepresearch_agent.provenance import FLAG_CLASSIFICATIONS, settings_flag_snapshot
from deepresearch_agent.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "_collab" / "087" / "ab" / "results.json"
HEADINGS = (
    "# DeepResearchAgent",
    "## 你会拿到什么",
    "## 三分钟跑起来",
    "## 凭什么信它",
    "## 架构与边界",
    "## 25 个能力的实测状态",
    "## 可审计性怎么实现的",
    "## 门禁与回归",
    "## 它不做什么",
)


def check(readme: Path, package: Path) -> dict[str, int]:
    text = readme.read_text(encoding="utf-8")
    report = (package / "report.md").read_text(encoding="utf-8").rstrip()
    match = re.search(r"<!-- BEGIN 087 EMBEDDED REPORT -->\n(.*?)\n<!-- END 087 EMBEDDED REPORT -->", text, re.S)
    embedded = match.group(1) if match else ""
    rows = re.findall(
        r"^\| ([A-Z_]+) \| (on|off) \| (.+) \| (.+) \|$",
        text,
        re.M,
    )
    expected = settings_flag_snapshot(Settings(storage_path=Path("research.db")), include_disabled_experimental=True)
    mismatches = sum(
        (state == "on") != bool(expected.get(flag))
        for flag, state, _evidence, _decision in rows
    )
    missing_headings = sum(heading not in text for heading in HEADINGS)
    capability_rows = {flag: (evidence, decision) for flag, _state, evidence, decision in rows}
    claims = missing_headings + _unverifiable_claims(text, package, capability_rows)
    return {
        "capability_rows": len(rows),
        "flag_state_mismatches": mismatches,
        "embedded_report_matches_artifact": int(embedded == report),
        "unverifiable_claims": claims,
    }


def _unverifiable_claims(
    text: str,
    package: Path,
    rows: dict[str, tuple[str, str]],
) -> int:
    missing = 0
    required_boundaries = (
        "REFLECTION_ENABLED",
        "MCP 不提供任意文件读取或命令执行",
        "Docker/Compose",
        "金融领域 SUT",
    )
    missing += sum(token not in text for token in required_boundaries)
    marker = re.search(r"<!-- 087-FACT workflow_cost=([^ ]+) rag_cost=([^ ]+) -->", text)
    manifest = json.loads(
        (package / "audit_bundle" / "manifest.json").read_text(encoding="utf-8")
    )
    rag_cost = sum(
        float(json.loads(line)["cost_cny"])
        for line in (package / "runtime" / "rag_ledger.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    expected_marker = (f"{float(manifest['cost_cny_total']):.8f}", f"{rag_cost:.7f}")
    if marker is None or marker.groups() != expected_marker:
        missing += 1
    if not RESULTS.is_file():
        return missing + 1
    pairs = json.loads(RESULTS.read_text(encoding="utf-8"))["pairs"]
    try:
        from scripts.check_087_report_shape import measure
    except ModuleNotFoundError:
        from check_087_report_shape import measure
    for pair in pairs:
        flag = f"{pair['capability']}_ENABLED"
        if pair["capability"] == "RERANK_FAIL_OPEN":
            flag = "RERANK_FAIL_OPEN"
        row = rows.get(flag)
        if row is None:
            missing += 1
            continue
        paths = [
            (RESULTS.parent / pair[name]).resolve()
            for name in ("off_package", "on_package")
        ]
        expected_evidence = "reader lines {} → {}".format(
            measure((paths[0] / "report.md").read_text(encoding="utf-8"))["reader_visible_lines"],
            measure((paths[1] / "report.md").read_text(encoding="utf-8"))["reader_visible_lines"],
        )
        if row != (expected_evidence, pair["decision"]):
            missing += 1
    return missing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readme", type=Path, default=ROOT / "README.md")
    parser.add_argument("--package", type=Path, default=ROOT / "artifacts" / "087" / "live-nio-zh")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        print("readme_facts_self_test=PASS")
        return
    values = check(args.readme, args.package)
    for key, value in values.items():
        print(f"{key}={value}")
    valid = (
        values["capability_rows"] == len(FLAG_CLASSIFICATIONS)
        and values["flag_state_mismatches"] == 0
        and values["embedded_report_matches_artifact"] == 1
        and values["unverifiable_claims"] == 0
    )
    raise SystemExit(0 if valid else 1)


def _self_test() -> None:
    """Exercise the row parser and the verbatim-embed comparison without a live run."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        package = root / "package"
        package.mkdir()
        report = "# report\n\n## 参考来源\nsource"
        (package / "report.md").write_text(report, encoding="utf-8")
        flags = settings_flag_snapshot(
            Settings(storage_path=Path("research.db")),
            include_disabled_experimental=True,
        )
        rows = "\n".join(
            f"| {flag} | {'on' if value else 'off'} | recorded | decision |"
            for flag, value in sorted(flags.items())
        )
        readme = root / "README.md"
        readme.write_text(
            "\n".join(HEADINGS)
            + "\n<!-- BEGIN 087 EMBEDDED REPORT -->\n"
            + report
            + "\n<!-- END 087 EMBEDDED REPORT -->\n"
            + rows,
            encoding="utf-8",
        )
        with patch(
            f"{__name__}._unverifiable_claims",
            return_value=0,
        ):
            values = check(readme, package)
    if values["capability_rows"] != len(FLAG_CLASSIFICATIONS):
        raise SystemExit("README self-test did not parse every flag")
    if values["embedded_report_matches_artifact"] != 1:
        raise SystemExit("README self-test did not verify the report embedding")


if __name__ == "__main__":
    main()
