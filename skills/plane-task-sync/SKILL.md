---
name: plane-task-sync
description: Use when syncing HomeLab implementation plans or CIO remediation updates to Plane from JarvisOS agents through the Plane CLI, especially when asked to create, update, deduplicate, or verify Plane work items.
metadata: {"agentSkills":{"requires":{"files":["/app/scripts/plane_sync.py"]}}}
---

# Plane Task Sync

Use `/app/scripts/plane_sync.py` for Plane writes. Do not register or call MCP tools for Plane; this integration is CLI-only.

## Commands

Sync a HomeLab plan file as a parent work item with phase and task children:

```bash
PYTHONPATH=/app/src /app/scripts/plane_sync.py plan /path/to/plan.md
```

Sync a CIO-style incident remediation update:

```bash
PYTHONPATH=/app/src /app/scripts/plane_sync.py incident \
  --domain homelab-operations \
  --service service-name \
  --title "Incident title" \
  --severity medium \
  --status triaged \
  --problem "What failed" \
  --root-cause "Known cause or empty" \
  --resolution-plan "First remediation step"
```

Create or update a single planning work item:

```bash
PYTHONPATH=/app/src /app/scripts/plane_sync.py project \
  --domain jarvios-platform \
  --title "Work item title" \
  --description "Short operational description" \
  --external-id "stable-source-id"
```

## Rules

- Keep `external_id` stable; the CLI is idempotent and updates matching Plane work items.
- Use `homelab-operations` for incidents unless the payload already has a more specific domain.
- Use `jarvios-platform` for JarvisOS implementation plans.
- Do not print Plane API keys or raw environment values.
- Treat HTTP 409 external-id conflicts as an update path; the CLI already handles this.
- Treat HTTP 429 as rate limiting; the CLI retries using `Retry-After`.

## Configuration

JarvisOS loads Plane configuration from `/home/paluss/docker/.env` through Docker `env_file`.
Required variables are `PLANE_API_KEY`, `PLANE_WORKSPACE_SLUG`, and `PLANE_DEFAULT_PROJECT_ID`.
`PLANE_PROJECT_MAP_JSON` maps JarvisOS domains to Plane project ids when needed.
