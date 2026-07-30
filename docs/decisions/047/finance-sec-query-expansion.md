# Finance SEC query expansion

The approved corpus contains public English SEC 20-F filings while the finance
product accepts Chinese issuer names. `FinanceDomainPack` therefore appends a
public English issuer alias to a retrieval request before either lexical or
dense retrieval. Generic RAG code receives only the expanded string through
the injected `RetrievalDomain`; it contains no finance vocabulary.

The current authoritative storage does not yet persist document-type, entity,
or fiscal-period facets. Finance consequently emits no such filter values:
the generic backends correctly fail closed for unsupported facets, and emitting
them would make every live RAG lookup empty. This is not a relaxation of
as-of, URL, document-version, character-range, extraction, or evidence-chain
guards.

The aliases are public issuer vocabulary, not writes to the frozen questions,
labels, split, or relevance values. The completed test result predates this
code change and remains the recorded negative B5-5 experiment. A new paid
quality experiment requires separate authorization and preregistration.
