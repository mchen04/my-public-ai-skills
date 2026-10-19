---
name: believe
description: >
  Challenge "blocked" or "impossible" stops with new safe routes. Use for "keep trying", "find
  another way", "don't give up", "same failed command". Not for loops, "keep working", or other
  agents' runs.
---
# Believe

Test a blocked claim until the requested outcome succeeds or evidence justifies stopping. Treat safety, permission, and authority limits as boundaries. Never try to evade them.

## Freeze the claim

Record `OUTCOME`, an observable `SUCCESS` check, a falsifiable `BLOCKER`, authorized `BOUNDARIES`, and `CAP` (the user's limit or six material attempts). Do not weaken success or widen boundaries. Reproduce a safe blocker once.

## Build distinct routes

List two or three safe routes. Change the causal hypothesis, interface, environment, reproduction size, evidence source or checkpoint. Rewording the same action is not a new route.

## Run the bounded audit

Record each attempt's hypothesis, route, observation and `DELTA=PROGRESS` or `DELTA=NONE`. Progress must move the success check, narrow the blocker with a new fact, or open a safe route.

Do not run an identical action more than twice. Retry once only when evidence shows a transient fault, then change routes. Three consecutive `DELTA=NONE` results mean `STUCK`. Six material attempts mean `CAP` unless the user set another limit. Sunk effort never extends the cap.

## Stop honestly

- `SOLVED`: the frozen success check passes with observed evidence.
- `BOUNDARY`: a safety, permission, authority, or destructive-action limit prevents a safe attempt.
- `STUCK`: three consecutive material attempts produce no progress.
- `CAP`: the attempt limit ends without success.

Keep labels in working notes. At a boundary, stop, and ask for new authority only when the user can safely provide it. At `STUCK` or `CAP`, preserve useful work. End with `Next, <smallest change that opens a route>.` Say "blocked under current constraints," not "impossible."

## Composes with

Use `loop` for scored check/fix cycles, `fix-bug` for a reproduced defect. Under a loop, record abandoned routes in its run record.

Use the [evidence scale](../fresh-eyes/references/evidence-scale.md) when labeling worklog claims.
