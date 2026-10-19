# Performance

Measure a real user path with primary/secondary metrics. For size, inventory the complete deployable runtime; separate evaluator-only assets and stored/inference dtype. Never manufacture an uncompressed baseline.

## Whole-app climbs

Inventory startup, main endpoints/screens, jobs and model calls. Rank measured cost×frequency/impact; climb the top path, then rotate on plateau. Freeze representative workloads; the cap covers the whole app. Account for every entry as gain, supported no-gain or gap.

## Measurements

Keep build, cache, power, background load, dataset and timed boundary comparable. Drift makes the comparison incomplete. Preserve failed evidence. Report correct outputs/errors, physical limiter and omitted end-to-end latency; controlled laptop results are not production proof. The root owns repetition/noise/selection.

Run each side as production runs it: release build, production flags, pools, caches and data. A side left on defaults compares configurations, not implementations. Do the limit arithmetic before you accept a gain. Removing a part that takes 10% of the run makes the run at most about 11% faster, and a result past a limit measured something other than the work, such as a cache, a no-op or a bug. Confirm that the timed work actually ran: count the requests, rows or bytes inside the timed region. Lazy generators, unawaited promises and timeouts produce numbers for work that never happened.

Model experiments distinguish research, training and inference capacity; cloud access does not prove memory/accelerators or Apple Silicon performance. For compression, prefer meaningful student/layer changes with recovery training over repeated tiny trims within the frozen gates.

## Checkpoint acceptance

Validate downloads, archive paths, complete manifests, hashes and replay/scoring before keeping a checkpoint. Bind numbers to replay-verified source/model/input receipts. Reconstruct the whole target manifest before reclaiming evidence; verified chunks do not prove recovery.

Do not load-test production or shared services without approval. Test concurrency changes, keep correctness under concurrency, and preserve operational logging/error paths. [Skill evals](skill-evals.md) owns model quality measurement.
