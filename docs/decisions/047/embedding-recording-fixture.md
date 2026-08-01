# Embedding 录制 fixture

`data/recordings/embeddings_v1/fixture_v1.json` 由一次授权的
`text-embedding-v4` 调用生成。它仅保存固定公开探针的 SHA-256、模型、维度与返回向量，
不保存语料正文、密钥或 endpoint。

`RecordedEmbeddingProvider` 在 CI 中按内容 hash 回放该向量；未知内容明确
`cache_miss`，不合成向量也不联网。录制账本保存在忽略的
`artifacts/047/embedding_recording_ledger.jsonl`。
