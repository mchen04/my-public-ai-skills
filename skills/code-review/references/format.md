# Review output

Use only needed sections:

```text
<state and one-sentence reason>
Reviewed <base>..<head>: files, additions/deletions, commits, migrations.
<dimensions; candidate/refuted/survived counts from ledger>

<severity + stable finding ID: what breaks>
<mechanism; file:line; decisive reproduction; affected actors; fix>

Credited controls / refuted candidates
CI and coverage caveat
Gating / pre-merge asks / post-merge tracker
<ledger verdict output verbatim>
```

Use B1… blocking, C1… concerns, S1… smaller notes. Only gating defects justify the state. Carry post-merge trackers across rounds. Keep every finding, ranked by priority. Strip state on comment-only passes; retain surface counts.

Be direct about observed failures; label [reasoned evidence](../../fresh-eyes/references/evidence-scale.md) and exclusions. No corpus statistics, speculative harm or fixed finding quotas. The [root](../SKILL.md#output) owns posting/self-review policy.
