# R127 — core/domain boundary closure

## Verdict

PASS. H03 is complete. General Harness code has zero concrete finance imports,
the only product DomainPack is finance, and the existing five-file/ten-hit
literal debt did not grow.

## Defect and repair

The boundary script measured `import_sites` but never failed when it was
nonzero. In addition, both the script and Ruff excluded all of `domains/**`, so
an import added to `domains/base.py`, `protocols.py`, `requirements.py`, or the
null Harness pack escaped both controls. The exclusion now covers only the
finance implementation and the explicit composition registry. Every other
production module is independently protected by the checker and Ruff.

The checker now owns one evaluation function, a six-case self-test, and a JSON
measurement mode. The complete gate invokes its self-test. The machine result
is published in `domain-boundary-proof.json`.

## Falsification

A real mutation added a concrete finance import to
`src/deepresearch_agent/domains/base.py`. The boundary checker failed with:

```text
core finance import sites must be 0, observed=1; inject DomainPack at the composition boundary
import_sites=1 literal_files=5 literal_hits=10 lexicon_terms=33 product_domains=["finance"]
```

Ruff independently rejected the same mutation with `TID251`. The mutation was
removed before verification.

## Verification

- Domain self-test: PASS, 6 cases.
- Production measurement: imports 0; product domains `["finance"]`; literal
  files 5; literal hits 10; ratchet mismatches 0.
- Domain unit suite: 11 tests, all pass.
- Repository Ruff and scoped strict mypy: pass.
- Paid or provider calls: none.

## Boundary

No second DomainPack or runtime was added, and no finance behavior changed.
