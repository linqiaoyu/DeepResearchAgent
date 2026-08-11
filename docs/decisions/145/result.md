# R145: Storage and service backends H2

All StorageProtocol methods are exercised through the same contract entrypoint
for SQLite and Postgres, and the generated SQLite schema has zero undeclared
differences from Postgres migrations. The declared Postgres and Qdrant CI jobs
each select nonzero service tests. A configured skip or a green result with
zero executed tests now fails explicitly.
