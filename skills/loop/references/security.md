# Security

Use only on user-authorized assets and environments. Production mutation, real user data, and third-party targets need separate authorization.

Freeze threat model, trust boundaries and identities. CHECK combines triaged scanners with executed abuse probes. BAR is zero confirmed in-scope findings. FAIL-DEMO demonstrates a denial failing on vulnerable state; HOLDOUT adds an unseen abuse case. Unreached production configuration/novel attacks stay residual.

Cover applicable anonymous/tenant/admin access, webhooks/OAuth/replay, SSRF, prompt/tool injection, files/signed URLs, realtime, retention/exports and client/log secret exposure. Confirm candidates through failing tests or exploits; model-only ambiguity needs refutation. Fix survivors, prove the boundary, retain regressions and reattack changed paths/holdout.

Emit `VERDICT: PASS` only with zero confirmed findings, triaged scans, evidence/residual for every boundary and no private data in shipped artifacts; otherwise `VERDICT: FAIL`. Claim no broader safety than tested.
