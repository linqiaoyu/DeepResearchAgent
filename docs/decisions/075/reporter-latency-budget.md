# Reporter latency-budget decision

R074 completed live extraction (56 evidence) but the reporter serialized all
56 entries including raw extract text and retained an 8,192-token completion
allowance. Its three 60-second calls exhausted. The reporter now passes at most
18 evidence entries, truncates each provider claim to 800 characters, omits
redundant raw extract text, and caps output at 1,024 tokens. Canonical evidence
and final footnotes remain unchanged. Mutation to 20 entries fails the guard;
the complete gate passed. A new paid T8 run requires fresh authorization.
