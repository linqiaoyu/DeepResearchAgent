"""Verify the restored site design and its Round 087 reader-visible facts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


EXPECTED_STYLES_SHA256 = "369121f41edf063412d635a4b8e08b64d94d095458ecccdb3306c60abedefff6"


def check(dist: Path, facts_path: Path) -> dict[str, int]:
    index = (dist / "index.html").read_text(encoding="utf-8")
    methodology = (dist / "methodology.html").read_text(encoding="utf-8")
    styles = (dist / "assets" / "styles.css").read_bytes()
    manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    if manifest.get("live_validation") != facts:
        raise ValueError("site manifest live-validation facts differ from the reviewed asset")
    if manifest.get("generated_from", {}).get("live_validation") != str(facts_path):
        raise ValueError("site manifest does not identify the reviewed live-validation asset")
    nio, pdd = facts["reports"]
    required_index = (
        "ROUND 087 · FINAL LIVE VALIDATION",
        f"NIO {nio['language']}报告",
        f"PDD {pdd['language']}报告",
        str(nio["reader_visible_lines"]),
        str(pdd["reader_visible_lines"]),
        facts["provider"],
        "金融 SUT",
    )
    if any(value not in index for value in required_index):
        raise ValueError("site home misses a required Round 087 fact")
    required_methodology = (
        "Round 087 最终 live 验证",
        facts["provider"],
        str(facts["corpus"]["documents"]),
        "finance SUT",
    )
    if any(value not in methodology for value in required_methodology):
        raise ValueError("site methodology misses a required Round 087 boundary")
    stylesheet_matches_baseline = (
        hashlib.sha256(styles).hexdigest() == EXPECTED_STYLES_SHA256
    )
    if not stylesheet_matches_baseline:
        raise ValueError("site stylesheet differs from the cfca7fb design baseline")
    return {
        "round_087_facts_visible": len(required_index),
        "methodology_boundaries_visible": len(required_methodology),
        "stylesheet_matches_cfca7fb": int(stylesheet_matches_baseline),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--facts", type=Path, required=True)
    args = parser.parse_args()
    try:
        values = check(args.dist, args.facts)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"site_check_error={exc}")
        raise SystemExit(1) from exc
    for key, value in values.items():
        print(f"{key}={value}")
    raise SystemExit(0 if values["stylesheet_matches_cfca7fb"] == 1 else 1)


if __name__ == "__main__":
    main()
