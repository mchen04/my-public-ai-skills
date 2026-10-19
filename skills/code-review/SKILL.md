---
name: code-review
description: >
  Multi-dimension PR review with adversarial verification and a reported refute count. Use for
  "judge this PR", "review this change deeply", "what could this break", or "self-review". Not for one-pass review.
---
# Code Review

Find consequential defects and ground them at the reviewed head. Finish when candidates are terminal, judge/CI evidence is recorded, and the review ends with `ledger verdict` verbatim.

Read [pipeline](references/pipeline.md) for stages, seeds, severity and budgets; [traps](references/traps.md) for missed-failure classes; [blast radius](references/blast-radius.md) for cross-diff tracing; [local stack](references/local-stack.md) for reproduction; [format](references/format.md) for output; [provider](references/provider.md) for model-dependent code.

## Rules

Each candidate gets a fresh independent refuter seeing candidate/source, never hunter reasoning. Nobody refutes their own finding. Require file:line to refute material/blocker claims. Ground survivors in a separate pass at the exact source location.

A spec is a claim: check what actually goes live. Rate a race by how often its trigger happens, not by how short its window is. Trace trusted values through their setters beyond the diff. Probe scratch copies/local fakes; never a real service. Reproduce gating findings; label unexecuted reasoning. Pre-existing/safe-direction defects do not gate; prove provenance. Every finding gets a disposition.

## Process

1. Run EXECUTED `scripts/reviewctl.py scope` and `risk`. Pick one dimension for a small no-risk diff; otherwise 3–5 orthogonal dimensions. Choose the crown jewel and concrete hunt lists.
2. `reviewctl.py ledger init --log <outside-repo>` starts round one. Later rounds keep that ledger via `ledger round`. Default cap: three rounds. Honor an explicit operator cap with `--round-cap N`; use `--zero-open` for a zero-issues gate. Both persist in later rounds.
3. Dispatch hunters, two strongest findings per call; repeat while they find more. Record credited controls with citations. Later hunters receive open/refuted lists, never fix rationale, under [fresh-eyes' exception](../fresh-eyes/SKILL.md#rules).
4. Refute each candidate; `ledger record` its mechanism, severity, state, identities and evidence. Refuted candidates return only with new evidence; fixed rows cite the fix. Ground survivors at the reviewed commit. Reproduce migrations on a scratch real database; use the draft role for model-dependent code.
5. Dispatch a fresh judge that neither hunted nor refuted. Record missed defects through the same refute/ground path, then `ledger judge` and exact-head `ledger ci`.
6. Write the format reference's review and append `ledger verdict`.

## Output

Post a PR review or comment only when the user asks to publish it; opening or updating a PR does not authorize that.

When publication is requested, a self-review posts comment-only, keeps the token, says it was a self-review, and sends subjective or design findings through `fresh-eyes`.

Under [loop's grammar](../loop/SKILL.md#workflow), APPROVE requires no gating survivor/unverified candidate, independent refuters, judge pass and green exact-head CI; emit `VERDICT: APPROVE` or `VERDICT: BLOCK`.

## Composes with

Use `fresh-eyes` for blind dispatch, `agent-browser` for UI evidence, and `address-review` for requested fixes.
