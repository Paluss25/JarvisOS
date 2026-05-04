---
name: email-cli
description: Use when an agent or human needs to inspect, triage, sort, draft, send, or reply to ProtonMail/GMX email through mailctl instead of email MCP tools.
metadata: {"agentSkills":{"requires":{"bins":["mailctl"]}}}
---

# Email CLI

Use `mailctl` for email work. Do not connect or request `protonmail-email`, `gmx-email`, `protonmail-mcp`, or `gmx-mcp`.

## Read-Only Workflow

- Accounts: `mailctl accounts --json`
- List unread: `mailctl list --account protonmail --unread --limit 20 --json`
- Read one email: `mailctl read --account gmx --uid 42 --json`
- Count unread: `mailctl unread-count --account protonmail --json`
- Search: `mailctl search --account gmx --from sender@example.com --subject invoice --json`

Prefer `--json` for agent use. Keep mailbox reads scoped by `--account`, `--folder`, and `--limit`.

## Triage Actions

- Mark read/unread: `mailctl mark --account protonmail --uid 42 --read --json`
- Move explicitly: `mailctl move --account gmx --uid 42 --destination Archive --json`
- Apply sorting rules: `mailctl sort --account protonmail --uid 42 --json`
- Draft only: `mailctl draft-reply --account protonmail --uid 42 --body-file reply.md --json`

`draft-reply` is allowed for agents because it does not send mail.

## Send/Reply Guardrail

Agents must not run `mailctl send` or `mailctl reply` unless both are true:

1. The user gives an explicit send/reply command for that specific message.
2. The user completes HITL confirmation for the exact recipient, subject, body, and account.

Never infer approval from a draft request, a general instruction to handle email, an automation goal, or prior consent. If approval is missing, stop at `draft-reply` and ask for confirmation. In `MAILCTL_AGENT_MODE=1` or other non-interactive contexts, `send` and `reply` require the HITL token produced for the exact approved action.

## Configuration

JarvisOS mounts `/home/paluss/docker/agents` read-only and sets `MAILCTL_CONFIG_DIR=/home/paluss/docker/agents`. Existing `.env.protonmail` and `.env.gmx` files provide credentials; provider host/port defaults are built into `mailctl`.

Sorting rules default to `MAILCTL_SORTING_RULES_PATH` or `/app/src/agents/cos/sorting_rules.yaml` in the JarvisOS container.
