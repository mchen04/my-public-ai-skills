# Evidence scale

Use the strongest label supported by the evidence; loop's runctl.py enforces the required pointers.

| Label | Meaning | Required evidence |
|---|---|---|
| `claimed` | A report or source reading without execution. | none |
| `observed` | The check ran and its output was inspected. | observation pointer |
| `failure-proven` | Known-bad input failed, then the actual input passed. | passing observation and red-run pointer |
| `independently-verified` | A separate context reproduced/refuted the result. | observation and verifier identity, never self |

CLI dispatch grades actual independence: cross-family is stronger than same-family fresh context. Do not choose that label by hand. Renew proof when its claimed surface changes.

## Acceptance evidence

Map requirements to the paths actually exercised. A simulator, cross-build, process exit or client count proves only that surface/quantity. Report untested requirements and fallback-only runs; compare interaction costs only for goals both builds complete.

Review VERIFIED means observed or stronger; WORTH CHECKING means claimed. fixed+verified needs observed evidence. FAIL-DEMO supplies the red demonstration. A citation alone proves no execution.
