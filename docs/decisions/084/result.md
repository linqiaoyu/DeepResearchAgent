# 084 result

The NIO retry exported 2 structured facts, sampled 2 reader-visible numeric
values with `magnitude_mismatches=0`, and had 29/29 RAG facts with an explicit
unknown publication date reason and 0 fabricated dates. PDD exported 1
structured fact, sampled 1 numeric value, and had 32/32 corresponding RAG
facts with 0 fabricated dates. Both packages have `relative_urls_in_evidence=0`
and `audit_citation_closure=ok`.

The RAG corpus still has no publication dates: RAG `source_pub_date` remains
unknown with `corpus_lacks_publication_date`; true filing-date backfill remains
next round. Retrieval relevance was measured, not repaired: the 083 NIO
baseline off-year ratio is 0.69; 084 NIO is 0.69 and PDD is 0.75.
