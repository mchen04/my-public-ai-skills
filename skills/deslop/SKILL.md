---
name: deslop
description: >
  Remove AI clutter from a diff: pointless comments, defensive wrappers, type casts, and nesting. Use for diff cleanup. Not for removing every comment (remove-comments) or repeated passes (loop).
---
# Deslop

Clean the branch diff against its base. Done means the diff reads like the code around it,
behavior is unchanged, and the relevant checks and the repository's required gates pass. Report in
a few lines what became simpler and how you verified it.

Remove commentary that restates code, unnecessary fallbacks on trusted paths, type casts that hide
errors, and nesting that obscures the main path. Match surrounding conventions. Keep validation at
trust boundaries and useful explanations of non-obvious decisions.

Default to unambiguous cleanup. Broader restructuring needs support from the requested scope. Code
that merely looks machine-generated is no evidence that it should change.

A fallback is unnecessary only when every runtime caller already supplies the value. A type that
marks a field as required does not prove it: tests, older saved contexts, and other packages may
still pass `undefined`. Check the call sites, or keep the fallback.

## Composes with

For repeated check/fix work use the `loop` code template.
