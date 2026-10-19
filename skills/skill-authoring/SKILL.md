---
name: skill-authoring
description: Write or edit Agent Skills and reusable agent instructions. Use for new skills, self-contained policy, wording, or lesson edits. Not for library audits or lesson routing (skill-maintenance).
---
# Skill Authoring

Write only what a capable model cannot infer: library commands, failure-derived rules, user preferences, and safety/approval boundaries. Delete generic expertise, incident narration, dates, IDs, session recipes, global steering, memory repeats, over-prompting and hollow sections. (Anthropic)

Before writing a new skill, run three realistic tasks without it; keep only text that changes the results, and rerun them after edits. Delete old text the model now follows unprompted. (Anthropic; OpenAI)

Give each rule one owner; link to it elsewhere. Shared decision rules belong in principles. Put preferences as "The user prefers ..." in the subject owner, never a supervisor or router. (pstack)

A lesson must change a future decision, name a specific behavior and still hold in six months; reject unsupported generalizations. When a rule covers it, reword that rule instead of adding one. A lesson never moves reference text into SKILL.md or creates a reference. (pstack; poteto)

Cuts never touch credential/secret handling, the user's apps/accounts/windows, or destructive, irreversible or public-action boundaries; keep those verbatim.

Prefer a check or guard over prose; prove it rejects the mistake. Drop instructions the environment already enforces. (kaito)

Lead with outcome and done, then rules every run needs; compaction can drop a long skill's end. Use goals and checks, exact recipes only for fragile steps. Name tools and outside success signals; test ambitious targets against a baseline within bounded access/budgets. (OpenAI; Claude Code; Felix)

Write whole sentences with articles and verbs. Use calm imperatives, a reason clause, roles rather than model IDs, and examples only for output shape. (Matt Pocock; pstack)

Description: main use case first, then when to use it; Codex shortens descriptions when its skill list is full. Not for names only competing siblings. Keep situational detail in references one level deep, and say when to read each.

[Workflow](references/authoring-workflow.md); [sources](references/writing-rules.md).
