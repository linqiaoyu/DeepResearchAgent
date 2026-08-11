# R147: Real Harness interoperability

H23 passed without making any remote data write. Three DeepSeek calls, three
DashScope/Qdrant/SQLite RAG probes, and three independent MCP subprocesses
completed with cost, latency, trajectory, termination, and offline commitment
evidence. Each boundary also rejected or degraded one injected failure.

The configured remote Qdrant collection was read-only diagnosed as stale: its
points lack `published_at`, so the H09 disclosure guard correctly withholds
them. RAG success validation therefore used a temporary local
`qdrant/qdrant:v1.18.3-unprivileged` container populated with three real corpus
chunks and deleted after the probes. This is a mechanism proof, not a finance
quality claim.

All interrupted and successful paid attempts are included in the ledger total:
CNY 0.0191385 against the CNY 40 round fuse.
