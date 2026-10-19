# Performance

Measure a real user path with primary/secondary metrics. For size, inventory the complete deployable runtime; separate evaluator-only assets and stored/inference dtype. Never manufacture an uncompressed baseline.

## Whole-app climbs

Inventory startup, main endpoints/screens, jobs and model calls. Rank measured cost×frequency/impact; climb the top path, then rotate on plateau. Freeze representative workloads; the cap covers the whole app. Account for every entry as gain, supported no-gain or gap.

## Measurements

Keep build, cache, power, background load, dataset and timed boundary comparable. Drift makes the comparison incomplete. Preserve failed evidence. Report correct outputs/errors, physical limiter and omitted end-to-end latency; controlled laptop results are not production proof. The root owns repetition/noise/selection.

Run each side as production runs it: release build, production flags, pools, caches and data. A side left on defaults compares configurations, not implementations. Do the limit arithmetic before you accept a gain. Removing a part that takes 10% of the run makes the run at most about 11% faster, and a result past a limit measured something other than the work, such as a cache, a no-op or a bug. Confirm that the timed work actually ran: count the requests, rows or bytes inside the timed region. Lazy generators, unawaited promises and timeouts produce numbers for work that never happened.

For model experiments, check compute, memory, and hardware requirements before choosing a test environment.
Measure model quality and serving latency separately. Cloud access alone does not prove that the required hardware is available.

## Saved artifact acceptance

Validate downloads, archive paths, complete manifests, hashes, and restored behavior before accepting a saved artifact.
Bind results to the source, model, and inputs that produced them.
Restore the complete artifact before deleting source copies. Verified chunks do not prove complete restoration.

Do not load-test production or shared services without approval. Test concurrency changes, keep correctness under concurrency, and preserve operational logging/error paths. [Skill evals](skill-evals.md) owns model quality measurement.
