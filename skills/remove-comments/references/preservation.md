# Preservation decisions

comments.py/notes.py own detection and behavior checks. Keep uncertain tool-readable text and report why.

## What stays

Legal notices; shebang/encoding; compiler/build directives; bundler/source-map annotations; JSDoc types used by checkJs; program-read comments/help. A docstring-required linter is a scope conflict, not permission to change config.

## Runtime docstrings

Look for __doc__, inspect.getdoc, doctest, CLI/API frameworks and pydantic readers. Move behavior into an explicit constant/help/description/table or regression test before removal. Keep/report out-of-scope interface changes. Resolve only freshly scanned path:line entries.

## Warnings and suppressions

Encode enforceable warnings as scoped checks, prove red/green and remove the note. Keep human/process/out-of-scope constraints. Avoid stale bytecode when probing same-size Python edits.

Remove dead suppressions. Correctness, safety and unscoped switches require cause fixes; keep environmental/style/formatter/coverage switches where legitimate. Intentional type-error tests may keep an exact suppression. Never weaken a config, lower a rule's level, or disable a check to make a switch go away. Use rule metadata/helper output instead of guessing its class.

## Clarity

CLARIFY is a heuristic, not proof. Read code before a local rename/extraction. A public rename that reaches outside the scope is a proposal, not an edit.

Adapted from canonical [pstack](https://github.com/cursor/plugins/tree/main/pstack), MIT, Lauren Tan. Detection/verification remain this library's implementation.
