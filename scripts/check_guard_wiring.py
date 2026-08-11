"""Refuse a guard that never runs.

R125: §8 says every round's reader-visible outcome must become a permanent
offline guard wired into ``scripts/gate.py``, because "只写在当轮任务卡、不进门禁的
成果视为未交付".  Twenty guards were written under that rule and named after the
round that produced them.  Fifteen of them were referenced by nothing -- not the
gate, not a CI workflow, not a test.  The rule's own output escaped the rule.

An unwired guard is worse than a missing one.  It reads as coverage in a
directory listing while asserting nothing, and it rots: ``check_081_rendering``
exited 1 with ``render_mismatches=64`` for every value/unit pair, because the
renderer deliberately gained a space between number and unit some rounds later
and no gate ever replayed the expectation.  By the time anyone runs it, a real
regression and a stale expectation look identical.

So: every ``scripts/**/check_*.py`` must be reachable from something that
executes.  Three surfaces count, because all three actually run the file:

* ``scripts/gate.py`` -- the full local gate,
* ``.github/workflows/*.yml`` -- a CI job,
* ``tests/`` -- a module imported by the suite the gate runs.

Reachability is transitive: a guard imported by a wired script runs whenever
that script does, which is how ``check_082_report_fidelity`` earns its place as
a measurement library behind ``check_087_capability_ab``.

The check is bidirectional.  A guard nothing reaches fails, and so does a gate
or workflow line naming a script that is not on disk.  There is no allowlist:
an invariant worth guarding is worth running, and one that is not should be
deleted rather than parked.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"

#: Guards live anywhere under scripts/, including the round/ package.
GUARD_GLOB = "**/check_*.py"

#: ``scripts/a/b.py``, ``scripts/a/b`` and ``scripts.a.b`` all name the same file.
_SCRIPT_REFERENCE = re.compile(r"scripts[/.]([A-Za-z0-9_]+(?:[/.][A-Za-z0-9_]+)*)")


def _resolve(reference: str, known: set[str]) -> str:
    """Collapse a path or dotted-import spelling to a scripts-relative stem.

    ``scripts.check_x._helper`` names a symbol inside ``scripts/check_x.py``, so
    the longest prefix that exists on disk wins.  When no prefix exists the
    whole reference is returned, which is what makes a deleted script show up
    as dangling instead of silently resolving to its parent package.
    """

    parts = reference.replace(".py", "").replace(".", "/").split("/")
    for end in range(len(parts), 0, -1):
        candidate = "/".join(parts[:end])
        if candidate in known:
            return candidate
    return "/".join(parts)


def _referenced_scripts(text: str, known: set[str]) -> set[str]:
    """Script stems named by a runner, covering both path and import spellings."""

    return {_resolve(match.group(1), known) for match in _SCRIPT_REFERENCE.finditer(text)}


def _read_all(paths: Iterable[Path]) -> str:
    chunks = []
    for path in paths:
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    return "\n".join(chunks)


def _stem(path: Path, root: Path) -> str:
    return path.relative_to(root / "scripts").with_suffix("").as_posix()


def collect(root: Path = ROOT) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
    """Guards on disk, what each runner surface references, and script imports."""

    scripts_dir = root / "scripts"
    known = {_stem(path, root) for path in scripts_dir.rglob("*.py")}
    guards = {_stem(path, root) for path in scripts_dir.glob(GUARD_GLOB)}
    surfaces = {
        "gate": _referenced_scripts(_read_all([scripts_dir / "gate.py"]), known),
        "ci": _referenced_scripts(
            _read_all(sorted((root / ".github/workflows").glob("*.yml"))), known
        ),
        "tests": _referenced_scripts(_read_all(sorted((root / "tests").rglob("*.py"))), known),
    }
    imports = {
        _stem(path, root): _referenced_scripts(path.read_text(encoding="utf-8"), known)
        for path in sorted(scripts_dir.rglob("*.py"))
    }
    return guards, surfaces, imports


def _reachable(surfaces: dict[str, set[str]], imports: dict[str, set[str]]) -> set[str]:
    """Everything a runner names, plus everything those scripts import."""

    frontier = set().union(*surfaces.values()) if surfaces else set()
    seen: set[str] = set()
    while frontier:
        name = frontier.pop()
        if name in seen:
            continue
        seen.add(name)
        frontier |= imports.get(name, set()) - seen
    return seen


def evaluate(
    guards: set[str],
    surfaces: dict[str, set[str]],
    imports: dict[str, set[str]],
    *,
    on_disk: set[str] | None = None,
) -> list[str]:
    """Failures in both directions: unreachable guards, and wiring to nothing."""

    failures: list[str] = []
    reachable = _reachable(surfaces, imports)
    for guard in sorted(guards - reachable):
        failures.append(
            f"unwired guard: scripts/{guard}.py is reached by no runner. "
            "Wire it into scripts/gate.py (add a --self-test if it needs a run "
            "artifact), give it a CI job, or delete it -- a guard outside the "
            "gate asserts nothing and rots into a false alarm."
        )
    known = set(imports) if on_disk is None else on_disk
    for surface, referenced in sorted(surfaces.items()):
        for name in sorted(referenced - known):
            failures.append(
                f"dangling reference: {surface} runs scripts/{name}.py, which is not on disk"
            )
    return failures


def _self_test() -> None:
    """Both directions must fail, or the check is decorative."""

    guards, surfaces, imports = collect()
    if evaluate(guards, surfaces, imports):
        print("guard_wiring_self_test=FAIL repository is not currently clean", file=sys.stderr)
        raise SystemExit(1)

    unwired = evaluate(guards | {"check_invented_guard"}, surfaces, imports)
    if not any("unwired guard" in line for line in unwired):
        print("guard_wiring_self_test=FAIL unwired guard was accepted", file=sys.stderr)
        raise SystemExit(1)

    dangling = evaluate(
        guards, {**surfaces, "gate": surfaces["gate"] | {"check_deleted_guard"}}, imports
    )
    if not any("dangling reference" in line for line in dangling):
        print("guard_wiring_self_test=FAIL dangling reference was accepted", file=sys.stderr)
        raise SystemExit(1)

    # Transitivity is load bearing: a library guard reached only through another
    # script must stay green, or the check would push authors to inline it.
    indirect = evaluate({"check_library"}, {"gate": {"check_front"}}, {"check_front": {"check_library"}})
    if indirect:
        print("guard_wiring_self_test=FAIL transitive reach was rejected", file=sys.stderr)
        raise SystemExit(1)

    print(f"guard_wiring_self_test=PASS guards={len(guards)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()

    guards, surfaces, imports = collect()
    failures = evaluate(guards, surfaces, imports)
    reachable = _reachable(surfaces, imports)
    print(
        f"guards={len(guards)} wired={len(guards & reachable)} "
        f"unwired={len(guards - reachable)}"
    )
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
