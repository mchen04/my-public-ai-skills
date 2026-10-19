# Sources and design choices

The [authoring policy](../SKILL.md) owns the rules. These public sources explain their origins.

| Source | Design choice |
|---|---|
| [pstack](https://github.com/cursor/plugins/tree/main/pstack) | One owner per rule, durable lessons, and structural prevention of repeated mistakes. |
| [Agent Skills specification](https://agentskills.io/specification) | Standard folders, descriptive routing metadata, and optional resources. |
| [Anthropic skill guidance](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) | Assume model capability, test against a baseline, and load detail only when needed. |
| [Claude Code skills](https://code.claude.com/docs/en/skills) | Keep important decisions near the top and keep references separate. |
| [OpenAI Codex skills](https://developers.openai.com/codex/skills) | Use concise descriptions and separate reusable instructions from runtime settings. |

The library also draws on public writing and workflow ideas from Matt Pocock, Felix Rieseberg, poteto, and kaito.
Private captures and conversation excerpts are excluded.
See [third-party notices](../../../THIRD_PARTY_NOTICES.md) for the retained pstack license.

`fresh-eyes/assets/roles.json` holds optional routing settings. The public defaults let each installed CLI choose its model.
