"""Refuse documentation that states a capability default the code contradicts.

`sync_agents_settings.py` rewrites every `FLAG_NAME=true|false` token to match
`Settings`, so those are already safe. What it cannot see is prose: R110 found
`NUMERIC_CHECK_ENABLED 默认关闭` in two documents and
`DECISION_WEAVING_ENABLED ... 默认关闭` in a third, while both have been `True`
in `Settings`; and `README.md` describing trajectory recording and progressive
delivery as switched off after `e131c31` turned both on. Every one of those
passed the full gate.

Two rules, both anchored so a claim binds only to the capability it is about:

* **flag rule** -- a state assertion binds to any `FLAG_NAME` token appearing in
  the window immediately before it. That window is what stops
  ``CONTEXT_PACKER_ENABLED=true ... 其它能力保持关闭`` from being read as a claim
  about the context packer.
* **alias rule** -- prose names a capability without its flag token
  (``trajectory record``), so a small alias table binds those too. Extend
  ``PROSE_ALIASES`` whenever a capability acquires a prose name in the docs; an
  alias that names no real flag fails this checker.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deepresearch_agent.settings import boolean_setting_defaults  # noqa: E402

#: How far back from an assertion a capability may be named and still be its
#: subject. Wide enough for a four-capability enumeration; the clause rule
#: below, not this width, is what stops a claim binding to the wrong subject.
BIND_WINDOW = 160
#: A claim does not reach across a clause boundary. Without this,
#: ``A_ENABLED=true；其余能力保持关闭`` reads as a claim about `A_ENABLED`.
CLAUSE_BREAKS = "；;。：:！!？?|"

OFF_CLAIMS = ("默认关闭", "保持关闭", "仍关闭", "默认为 false", "默认 false", "defaults to false")
ON_CLAIMS = ("默认开启", "保持开启", "已默认开启", "默认为 true", "默认 true", "defaults to true")

#: Prose names that mean a flag. Keys must be real flag names.
PROSE_ALIASES = {
    "TRAJECTORY_RECORD_ENABLED": ("trajectory record", "轨迹记录"),
    "PROGRESSIVE_DELIVERY_ENABLED": ("progressive delivery", "渐进交付"),
    "RESEARCH_LOOP_ENABLED": ("research loop", "多轮研究"),
    "SKILL_PACKS_ENABLED": ("skill packs", "技能包"),
    "CONTEXT_PACKER_ENABLED": ("context packer",),
    "NUMERIC_CHECK_ENABLED": ("numeric check",),
    "SEMANTIC_JUDGE_ENABLED": ("semantic judge",),
    "DECISION_WEAVING_ENABLED": ("decision weaving",),
    "RAG_ENABLED": ("rag search",),
    "REFLECTION_ENABLED": ("reflection",),
}


class DocFlagClaimError(AssertionError):
    pass


def tracked_markdown() -> list[Path]:
    """Documentation under version control, excluding archived round records.

    `docs/decisions/<round>/` is a historical record: it states what was true in
    that round and must not be rewritten when a default later changes.
    """

    out = subprocess.run(
        ["git", "ls-files", "*.md"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [Path(p) for p in out if not p.startswith("docs/decisions/")]


def _subjects(line: str, position: int, defaults: dict[str, bool]) -> set[str]:
    window = line[max(0, position - BIND_WINDOW) : position]
    cut = max((window.rfind(mark) for mark in CLAUSE_BREAKS), default=-1)
    if cut >= 0:
        window = window[cut + 1 :]
    found = {name for name in defaults if name in window}
    for flag, aliases in PROSE_ALIASES.items():
        if flag in defaults and any(alias in window.lower() for alias in aliases):
            found.add(flag)
    return found


def validate_alias_table(defaults: dict[str, bool]) -> None:
    """An alias that names no real flag would silently check nothing."""

    unknown = sorted(set(PROSE_ALIASES) - set(defaults))
    if unknown:
        raise DocFlagClaimError(f"alias table names no such flag: {unknown}")


def contradictions(paths: list[Path], defaults: dict[str, bool]) -> list[str]:
    found: list[str] = []
    for path in paths:
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for claims, claimed in ((OFF_CLAIMS, False), (ON_CLAIMS, True)):
                for phrase in claims:
                    for match in re.finditer(re.escape(phrase), line):
                        for flag in _subjects(line, match.start(), defaults):
                            if defaults[flag] != claimed:
                                found.append(
                                    f"{path}:{number} {flag} is "
                                    f"{str(defaults[flag]).lower()}, "
                                    f"text claims {str(claimed).lower()} "
                                    f"via '{phrase}'"
                                )
    return sorted(set(found))


def _self_test() -> None:
    """Both rules must fire, and neither may fire on a correct sentence."""

    defaults = {"A_ENABLED": True, "B_ENABLED": False}
    aliases = dict(PROSE_ALIASES)
    try:
        PROSE_ALIASES.clear()
        PROSE_ALIASES["A_ENABLED"] = ("alpha packer",)
        cases = {
            "`A_ENABLED` 默认关闭。": 1,
            "`A_ENABLED` 与 `B_ENABLED` 默认关闭。": 1,
            "alpha packer 默认关闭": 1,
            "`A_ENABLED` 默认开启。": 0,
            "`B_ENABLED` 默认关闭。": 0,
            # The false positive the window exists to prevent: a correct claim
            # about one capability followed by a claim about another.
            "`A_ENABLED=true`；此外其余尚未验证的能力全部保持关闭。": 0,
        }
        for line, expected in cases.items():
            path = Path("<self-test>")
            observed = len(
                [
                    item
                    for claims, claimed in ((OFF_CLAIMS, False), (ON_CLAIMS, True))
                    for phrase in claims
                    for match in re.finditer(re.escape(phrase), line)
                    for flag in _subjects(line, match.start(), defaults)
                    if defaults[flag] != claimed
                    for item in [flag]
                ]
            )
            if observed != expected:
                raise DocFlagClaimError(
                    f"self-test: {line!r} expected {expected} got {observed}"
                )
            del path
    finally:
        PROSE_ALIASES.clear()
        PROSE_ALIASES.update(aliases)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        defaults = boolean_setting_defaults()
        validate_alias_table(defaults)
        _self_test()
        if args.self_test:
            print("doc_flag_claims=PASS self-test")
            return 0
        found = contradictions(tracked_markdown(), defaults)
    except DocFlagClaimError as exc:
        print(f"doc_flag_claims=FAIL {exc}", file=sys.stderr)
        return 1
    if found:
        print(f"doc_flag_claims=FAIL contradictions={len(found)}", file=sys.stderr)
        for item in found:
            print(f"  {item}", file=sys.stderr)
        return 1
    print("doc_flag_claims=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
