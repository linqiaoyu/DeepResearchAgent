from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "check_082_report_fidelity.py"
SPEC = importlib.util.spec_from_file_location("check_082_report_fidelity", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def package(*, footnote: bool = False, rendered: str = "71332000000CNY") -> Path:
    root = Path(tempfile.mkdtemp())
    audit = root / "audit_bundle"
    audit.mkdir()
    (root / "report.md").write_text(f"Revenue was {rendered}.", encoding="utf-8")
    (audit / "evidence.json").write_text(json.dumps([{
        "evidence_id": "evidence-1", "source_pub_date": "2025-03-01",
        "structured_record": {"value": "71332000000", "unit": "CNY"},
    }]), encoding="utf-8")
    evidence_ids = ["footnote:9"] if footnote else ["evidence-1"]
    (audit / "report.json").write_text(json.dumps({"claims": [{"evidence_ids": evidence_ids}]}), encoding="utf-8")
    return root


class Check082ReportFidelityTests(unittest.TestCase):
    def test_footnote_misreference_fails(self) -> None:
        metrics = MODULE.measure(package(footnote=True))
        self.assertEqual(metrics.footnote_misrefs, 1)

    def test_truncated_number_is_a_magnitude_mismatch(self) -> None:
        metrics = MODULE.measure(package(rendered="71332CNY"))
        self.assertEqual(metrics.sampled_numbers, 1)
        self.assertEqual(metrics.magnitude_mismatches, 1)

    def test_complete_package_passes(self) -> None:
        metrics = MODULE.measure(package())
        self.assertEqual(metrics.footnote_misrefs, 0)
        self.assertEqual(metrics.magnitude_mismatches, 0)
