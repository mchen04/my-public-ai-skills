---
name: agent-browser
description: >
  Drive a web app in headless Chromium: open a page, click, fill, screenshot, verify. Use for "test
  frontend" or "screenshot the page". Not for Safari or a project verify recipe (project-verification).
---
# Agent Browser

Exercise a web flow with the installed `agent-browser` CLI. Save evidence outside the repository. Use `agent-browser --help` for syntax. If `command -v agent-browser` finds nothing, report the missing dependency; do not install packages globally without authorization.

## Workflow

1. Read `session list`; choose a unique `--session <name>` for every command. The daemon is shared with other agents, and `--session-name` only labels saved cookies; it isolates nothing.
2. Open the URL and `snapshot` for `@ref` targets. Refresh refs after navigation or rendering. Wait for the visible revision before dependent actions.
3. Verify the result with a fresh snapshot. For visual claims, take and open a screenshot; reject blank or clipped images. Inspect `console` and `errors` on failures.
4. Close your session on every exit path, then confirm with `session list` that it is gone. Stop any dev server you started, and name anything you left running on purpose.

## The user's signed-in Chrome

Attach only when the user asks, with `--auto-connect` or `--cdp <port>`. Open your own tab with `tab new`, close only that tab, and leave the browser open. Never copy cookies or ask for a password. During a reading task, do not click vote, post, message, or account controls.

For an authorized message, confirm the account and conversation, keep any unsent draft, and recheck the target just before you send. A click proves neither a send nor a reply, so read the result back from the page. If a send times out, read the conversation before you retry, because the first send may have landed.

## Recovery and evidence

If refs fail, inspect DOM attributes read-only; use a specific selector and verify. Never submit through the DOM in place of user interaction. Scroll offscreen targets into view. Wrap repeated `eval` snippets in an IIFE to avoid persistent declarations.

Bound screenshots with an external timeout; retry once in a fresh session, then use the project's runner. For viewport claims, check scroll size, overflow and keyboard access to the last action. Chromium does not prove Safari; use the project's WebKit runner. [project-verification](../project-verification/references/recipe.md) owns runner setup.

## Composes with

As `loop` CHECK, emit exactly `VERDICT: PASS` or `VERDICT: FAIL` under its [grammar](../loop/SKILL.md#workflow). PASS requires observed state meeting the charter; an unexercised flow fails.

Close only sessions this task created.

Never run `close --all`, kill unattributed browser processes, or delete shared temporary profiles, because another agent's live session may use them.

Keep recovery codes, bearer tokens, and credentials out of screenshots and saved receipts.
