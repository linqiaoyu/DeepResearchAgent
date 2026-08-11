"""Enforce the finance-domain literal ratchet outside domain implementations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LEXICON_PATH = ROOT / "data/domain_boundary/finance_lexicon.json"
ALLOWLIST_PATH = ROOT / "data/domain_boundary/allowlist.json"
SOURCE_ROOT = ROOT / "src/deepresearch_agent"
PROMPT_ROOT = ROOT / "prompts"
DOMAIN_IMPORT = "deepresearch_agent.domains.finance"

#: R113 turned "there is only one domain" from an open gap into a stated scope:
#: finance is the domain being finished, the `DomainPack` seam stays and keeps
#: carrying dependency inversion, and no second product domain is started. The
#: check runs in both directions -- a second product domain fails, and so does
#: losing this one -- so the scope cannot drift without somebody deciding to
#: change it.
DECLARED_PRODUCT_DOMAINS = {"finance"}


def _product_domain_packs() -> tuple[str, ...]:
    sys.path.insert(0, str(ROOT / "src"))
    from deepresearch_agent.domains.registry import product_domain_packs

    return product_domain_packs()


def _load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _scanned_files() -> list[Path]:
    """Every core surface the ratchet covers.

    R112: this used to scan Python under ``src`` only, so ``prompts/`` was a
    blind spot -- core prompts could name any amount of finance vocabulary while
    ``import_sites=0`` still read clean. A prompt is core behaviour, not a
    comment, so it is measured the same way.
    """

    files = [
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if "domains" not in path.relative_to(SOURCE_ROOT).parts
    ]
    files.extend(path for path in PROMPT_ROOT.rglob("*") if path.is_file())
    return files


def _literal_lines(lexicon: tuple[str, ...]) -> dict[str, int]:
    hits: dict[str, int] = {}
    for path in _scanned_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        count = sum(1 for line in lines if any(word in line for word in lexicon))
        if count:
            hits[path.relative_to(ROOT).as_posix()] = count
    return dict(sorted(hits.items()))


def _concrete_domain_import_sites(source_root: Path = SOURCE_ROOT) -> int:
    """Count concrete finance imports outside the finance implementation.

    The finance implementation may import its own package and the registry is
    the explicit composition root. Every other module, including domain base,
    protocols, requirements, and the null harness pack, must depend only on the
    abstract contract. Keeping the measurement here makes that forbidden class
    visible independently of Ruff.
    """
    return sum(
        1
        for path in source_root.rglob("*.py")
        if not path.relative_to(source_root).is_relative_to("domains/finance")
        and path.relative_to(source_root).as_posix() != "domains/registry.py"
        for line in path.read_text(encoding="utf-8").splitlines()
        if DOMAIN_IMPORT in line
    )


def _evaluate_boundary(
    *,
    hits: dict[str, int],
    allowlist: dict[str, int],
    import_sites: int,
    product_domains: tuple[str, ...],
) -> list[str]:
    failures: list[str] = []
    if import_sites != 0:
        failures.append(
            f"core finance import sites must be 0, observed={import_sites}; "
            "inject DomainPack at the composition boundary"
        )
    for path in sorted(set(hits) | set(allowlist)):
        observed = hits.get(path, 0)
        allowed = allowlist.get(path)
        if allowed is None:
            failures.append(f"unallowlisted literal: {path} observed={observed}")
        elif observed != allowed:
            direction = "lower allowlist to" if observed < allowed else "remove literals or raise no allowlist"
            failures.append(
                f"ratchet mismatch: {path} observed={observed} allowed={allowed}; "
                f"{direction} {observed}"
            )
    if set(product_domains) != DECLARED_PRODUCT_DOMAINS:
        failures.append(
            f"product domains are {sorted(product_domains)}, declared "
            f"{sorted(DECLARED_PRODUCT_DOMAINS)}. AGENTS.md section 1 says finance is "
            "the one domain being finished and no second product domain is started. "
            "Changing that is a product decision: record it there first."
        )
    return failures


def _self_test() -> None:
    clean = {
        "hits": {"core.py": 1},
        "allowlist": {"core.py": 1},
        "import_sites": 0,
        "product_domains": ("finance",),
    }
    if _evaluate_boundary(**clean):
        raise SystemExit("domain_boundary_self_test=FAIL rejected clean fixture")
    cases: dict[str, dict[str, Any]] = {
        "core_import": {**clean, "import_sites": 1},
        "new_product_domain": {
            **clean,
            "product_domains": ("finance", "healthcare"),
        },
        "missing_finance": {**clean, "product_domains": ()},
        "literal_growth": {**clean, "hits": {"core.py": 2}},
        "unregistered_literal_file": {
            **clean,
            "hits": {"core.py": 1, "new.py": 1},
        },
    }
    for label, broken in cases.items():
        if not _evaluate_boundary(**broken):
            raise SystemExit(f"domain_boundary_self_test=FAIL accepted {label}")
    print(f"domain_boundary_self_test=PASS cases={len(cases) + 1}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true", help="emit the measured boundary as JSON")
    args = parser.parse_args()
    raw_lexicon = _load_json(LEXICON_PATH)
    raw_allowlist = _load_json(ALLOWLIST_PATH)
    lexicon = raw_lexicon
    allowlist = raw_allowlist
    if not isinstance(lexicon, list) or not all(isinstance(word, str) and word for word in lexicon):
        raise SystemExit(f"invalid lexicon: {LEXICON_PATH}")
    if not isinstance(allowlist, dict) or not all(
        isinstance(path, str) and isinstance(limit, int) and limit >= 0
        for path, limit in allowlist.items()
    ):
        raise SystemExit(f"invalid allowlist: {ALLOWLIST_PATH}")

    typed_allowlist = {str(path): int(limit) for path, limit in allowlist.items()}
    hits = _literal_lines(tuple(lexicon))
    import_sites = _concrete_domain_import_sites()
    product_domains = _product_domain_packs()
    failures = _evaluate_boundary(
        hits=hits,
        allowlist=typed_allowlist,
        import_sites=import_sites,
        product_domains=product_domains,
    )
    if args.self_test:
        _self_test()
    metrics = {
        "import_sites": import_sites,
        "literal_files": len(hits),
        "literal_hits": sum(hits.values()),
        "lexicon_terms": len(lexicon),
        "product_domains": list(product_domains),
        "ratchet_mismatches": sum("ratchet" in failure or "literal" in failure for failure in failures),
    }
    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"import_sites={import_sites} literal_files={len(hits)} "
            f"literal_hits={sum(hits.values())} lexicon_terms={len(lexicon)} "
            f"product_domains={json.dumps(list(product_domains))}"
        )
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
