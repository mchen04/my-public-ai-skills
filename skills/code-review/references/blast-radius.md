# Blast radius

Name the one fact that the change is safe because of, for example "this call drops only cache entries that are already dead". When that fact holds, most risks clear at once. Prove it with a small script or test that runs the real code, and keep the output. If you cannot run it, mark the fact unproven. Report the fact and its proof in the coverage caveat.

Grep lists callers in a second, so look where it stops. Before dispatch, map changed exports, persisted state and trusted-value setters across packages/services. Inspect consumers of serialized output, background jobs, migrations and release paths. A narrow diff can widen reachable behavior elsewhere.

Assign each changed surface a dimension and explicit exclusions. Use [fresh-eyes' evidence scale](../../fresh-eyes/references/evidence-scale.md) for each claim; source reading is not execution. Feed the map into `reviewctl.py risk` and the [pipeline](pipeline.md).
