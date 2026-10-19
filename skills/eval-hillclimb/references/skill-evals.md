# Skill and prompt evals

Prefer authorized production cases, then failures and realistic human-written tasks. Cover ordinary, hard, refusal and sibling cases. Put every graded requirement in the task; resolve ambiguity before freezing.

Use deterministic checks where possible; reserve blind randomized cross-model judgment for open quality. Calibrate graders, grade identical outputs twice and keep API/timeouts/state leakage separate from task failures. Record model/settings, inputs, outputs, grades, latency and uncertainty; repeated trials are not independent cases.

Split related-case families together before optimization. Hide validation answers/transcripts with actual access separation; instructions to ignore readable answers are not blindness. Keep an untouched final set when feasible; otherwise state the limit. Grader repairs require paired rebaselining, not an isolated candidate pass.

Keep quality gains only beyond noise with supporting validation and no unacceptable regression. Cost objectives may retain equal quality at measured savings. Classify stalled failures instead of endlessly rewording. More instructions or reviewer approval alone prove no gain.

[skill-maintenance](../../skill-maintenance/references/behavior-evaluation.md) owns blindeval mechanics. Description changes need trigger cases and authorized model routing comparison. Store case manifests, rubric, outputs and decisions outside durable skills.
