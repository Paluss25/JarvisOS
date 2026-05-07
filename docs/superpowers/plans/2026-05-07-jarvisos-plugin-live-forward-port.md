# JarvisOS Plugin Live Forward-Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Forward-port the useful plugin runtime and tool-plugin upgrades from the old plugin branches onto the current live `main` image without regressing WHOOP, Plane, email, CHRO/COH schema, or finance fixes.

**Architecture:** Treat `feature/plugin-directory-migration` as reference material, not as a merge source. Rebuild the plugin runtime incrementally on top of current `main`, preserving current live agent modules and only adding plugin contracts, plugin packages, client adapters, default allowlists, and tests. `feature/plugin-kernel-tool-migration` is a subset and should not be merged separately.

**Tech Stack:** Python 3.12, existing JarvisOS MCP tool assembly, local trusted plugin packages under `plugins/`, `pytest`, Docker image `10.10.200.61:5000/jarvios-platform:latest`.

---

## Live Baseline

Current live image digest checked during plan creation:

- `jarvios-platform`: `sha256:3d011734320c715420bde1f69fcd09df6a3b323f052c8f98f42f5d31994c2b27`
- Live has WHOOP sync, Garmin observation bridge, YNAB CLI, email dedupe, CHRO `human_res`, COH health/public lab schema, and Plane CLI/runtime.
- Live does **not** have `/app/src/plugin_runtime` or `/app/plugins`.

Old branch assessment:

- `feature/plugin-kernel-tool-migration`: useful subset only. Do not merge; copy ideas from commit `3bbbc53`.
- `feature/plugin-directory-migration`: useful architecture and tests, but stale relative to live `main`. Do not merge directly.
- `feature/plane-task-sync`: stale/downgrade and intentionally deleted after this plan.

## File Map

Create:

- `src/plugin_runtime/__init__.py` - exported plugin runtime API.
- `src/plugin_runtime/context.py` - narrow `PluginContext` object passed to plugins.
- `src/plugin_runtime/errors.py` - plugin load and validation exceptions.
- `src/plugin_runtime/hooks.py` - plugin hook protocol and discovery helpers.
- `src/plugin_runtime/loader.py` - manifest/module loader for trusted local plugins.
- `src/plugin_runtime/manifest.py` - YAML manifest parser and validation.
- `src/plugin_runtime/registry.py` - per-agent plugin registration and allowlist filtering.
- `src/plugin_runtime/tools.py` - `ToolSpec` and adapter helpers for SDK tools.
- `src/agent_runner/plugin_defaults.py` - default plugin package allowlists per agent.
- `plugins/README.md` - runtime contract documentation.
- `plugins/*/plugin.yaml` and `plugins/*/plugin.py` - first plugin packages.
- `src/agent_runner/tools/*_client.py` - reusable clients extracted from direct wrappers.

Modify:

- `Dockerfile` - copy `plugins/` into image.
- `src/agent_runner/client.py` - assemble plugin tools after built-ins.
- `src/agent_runner/config.py` - add optional plugin configuration.
- Agent config files under `src/agents/*/config.py` - enable plugin package lists only where needed.
- Existing tool wrappers under `src/agent_runner/tools/*.py` and `src/agents/*/tools.py` - keep compatibility wrappers; do not delete live direct tools in the first pass.
- `tests/conftest.py` - register new plugin tests in the explicit test classification map.

Do not remove:

- `src/agents/dos/whoop_sync.py`
- `migrations/010_whoop_sync.sql`
- `migrations/011_garmin_recovery_observation_bridge.sql`
- `src/tools/ynab_cli.py`
- `src/agents/cfo/YNAB_CLI.md`
- `vendor/mailctl/`
- `html-text-cli/`
- Plane files under `src/integrations/plane/`, `src/agents/mt/plane_tools.py`, `src/agents/cio/plane_payload.py`, `scripts/plane_sync.py`
- Current CHRO/COH schema compatibility code and tests.

## Task 1: Runtime Contract Skeleton

**Files:**

- Create: `src/plugin_runtime/manifest.py`
- Create: `src/plugin_runtime/context.py`
- Create: `src/plugin_runtime/errors.py`
- Create: `src/plugin_runtime/tools.py`
- Create: `src/plugin_runtime/__init__.py`
- Test: `tests/test_plugin_manifest.py`
- Test: `tests/test_plugin_tool_spec.py`

- [ ] **Step 1: Write manifest validation tests**

Add `tests/test_plugin_manifest.py`:

```python
import pytest

from plugin_runtime.manifest import PluginManifest, load_manifest_text
from plugin_runtime.errors import PluginManifestError


def test_load_manifest_text_accepts_minimal_plugin_manifest():
    manifest = load_manifest_text(
        '''
name: memory-box-tools
version: 1
entrypoint: plugin.py
tools:
  - memory_box_query
  - memory_box_write
allowed_agents:
  - ceo
  - cio
'''
    )

    assert manifest == PluginManifest(
        name="memory-box-tools",
        version=1,
        entrypoint="plugin.py",
        tools=("memory_box_query", "memory_box_write"),
        allowed_agents=("ceo", "cio"),
    )


def test_load_manifest_text_rejects_empty_tool_list():
    with pytest.raises(PluginManifestError, match="tools"):
        load_manifest_text(
            '''
name: empty
version: 1
entrypoint: plugin.py
tools: []
allowed_agents: [ceo]
'''
        )
```

- [ ] **Step 2: Implement manifest parser**

Create `src/plugin_runtime/errors.py`:

```python
class PluginError(RuntimeError):
    """Base class for trusted local plugin runtime failures."""


class PluginManifestError(PluginError):
    """Raised when a plugin manifest is missing required fields or is invalid."""
```

Create `src/plugin_runtime/manifest.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from plugin_runtime.errors import PluginManifestError


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: int
    entrypoint: str
    tools: tuple[str, ...]
    allowed_agents: tuple[str, ...]


def load_manifest_text(text: str) -> PluginManifest:
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise PluginManifestError("manifest must be a mapping")

    name = _required_str(raw, "name")
    version = int(raw.get("version", 1))
    entrypoint = _required_str(raw, "entrypoint")
    tools = _required_str_list(raw, "tools")
    allowed_agents = _required_str_list(raw, "allowed_agents")

    return PluginManifest(
        name=name,
        version=version,
        entrypoint=entrypoint,
        tools=tuple(tools),
        allowed_agents=tuple(allowed_agents),
    )


def _required_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PluginManifestError(f"{key} is required")
    return value.strip()


def _required_str_list(raw: dict[str, Any], key: str) -> list[str]:
    value = raw.get(key)
    if not isinstance(value, list) or not value:
        raise PluginManifestError(f"{key} must be a non-empty list")
    out = [str(item).strip() for item in value if str(item).strip()]
    if not out:
        raise PluginManifestError(f"{key} must be a non-empty list")
    return out
```

- [ ] **Step 3: Write ToolSpec tests**

Add `tests/test_plugin_tool_spec.py`:

```python
from plugin_runtime.tools import ToolSpec


def test_tool_spec_keeps_name_description_schema_and_handler():
    def handler(args):
        return {"ok": args["value"]}

    spec = ToolSpec(
        name="echo",
        description="Echo a value.",
        schema={"type": "object", "properties": {"value": {"type": "string"}}},
        handler=handler,
    )

    assert spec.name == "echo"
    assert spec.handler({"value": "x"}) == {"ok": "x"}
```

- [ ] **Step 4: Implement runtime skeleton**

Create `src/plugin_runtime/tools.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]
    handler: ToolHandler
```

Create `src/plugin_runtime/context.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PluginContext:
    agent_id: str
    workspace_path: Path
    config: dict[str, Any]
```

Create `src/plugin_runtime/__init__.py`:

```python
from plugin_runtime.context import PluginContext
from plugin_runtime.manifest import PluginManifest
from plugin_runtime.tools import ToolSpec

__all__ = ["PluginContext", "PluginManifest", "ToolSpec"]
```

- [ ] **Step 5: Verify**

Run:

```bash
PYTHONPATH=. pytest tests/test_plugin_manifest.py tests/test_plugin_tool_spec.py
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/plugin_runtime tests/test_plugin_manifest.py tests/test_plugin_tool_spec.py
git commit -m "feat(plugin): add runtime contract skeleton"
```

## Task 2: Loader and Registry

**Files:**

- Create: `src/plugin_runtime/loader.py`
- Create: `src/plugin_runtime/registry.py`
- Test: `tests/test_plugin_loader.py`
- Test: `tests/test_plugin_registry.py`

- [ ] **Step 1: Write loader tests**

Add tests that create a temporary plugin directory with `plugin.yaml` and `plugin.py`; assert the loader returns one `ToolSpec` named `echo`.

Expected plugin module API:

```python
def register(context):
    return [ToolSpec(...)]
```

- [ ] **Step 2: Implement loader**

Load only from explicit directories under the configured plugin root. Use `importlib.util.spec_from_file_location`; reject entrypoints that escape the plugin directory.

- [ ] **Step 3: Write registry tests**

Assert that a plugin with `allowed_agents: [mt]` is visible for `mt` and hidden for `cfo`.

- [ ] **Step 4: Implement registry**

Expose:

```python
def discover_plugins(root: Path) -> list[LoadedPlugin]
def tools_for_agent(root: Path, agent_id: str, context: PluginContext) -> list[ToolSpec]
```

- [ ] **Step 5: Verify**

Run:

```bash
PYTHONPATH=. pytest tests/test_plugin_loader.py tests/test_plugin_registry.py
```

- [ ] **Step 6: Commit**

```bash
git add src/plugin_runtime tests/test_plugin_loader.py tests/test_plugin_registry.py
git commit -m "feat(plugin): load trusted local plugins"
```

## Task 3: Agent Runner Integration in Shadow Mode

**Files:**

- Modify: `src/agent_runner/config.py`
- Modify: `src/agent_runner/client.py`
- Create: `src/agent_runner/plugin_defaults.py`
- Test: `tests/test_agent_plugin_settings.py`
- Test: `tests/test_plugin_client_integration.py`

- [ ] **Step 1: Add config tests**

Assert plugin root defaults to `/app/plugins`, plugin loading can be disabled, and agent-specific plugin names can be configured.

- [ ] **Step 2: Add plugin defaults**

Create a mapping like:

```python
DEFAULT_AGENT_PLUGINS = {
    "ceo": ("memory-box-tools", "report-issue-tools", "task-tools"),
    "cio": ("memory-box-tools", "report-issue-tools", "cron-tools"),
    "mt": ("calendar-tools", "contacts-tools", "email-digest-tools", "task-tools"),
}
```

Keep the list conservative. Do not enable plugins for all agents in the first pass.

- [ ] **Step 3: Integrate after built-ins**

Append plugin `ToolSpec`s after existing direct tool registrations. If a plugin tool name duplicates a built-in, keep the built-in and log a warning; do not replace direct tools in this task.

- [ ] **Step 4: Verify**

Run:

```bash
PYTHONPATH=. pytest tests/test_agent_plugin_settings.py tests/test_plugin_client_integration.py tests/test_agent_runner_config.py
```

- [ ] **Step 5: Commit**

```bash
git add src/agent_runner tests/test_agent_plugin_settings.py tests/test_plugin_client_integration.py
git commit -m "feat(plugin): register plugin tools in shadow-safe mode"
```

## Task 4: First Plugin Packages

**Files:**

- Create: `plugins/memory-box-tools/plugin.yaml`
- Create: `plugins/memory-box-tools/plugin.py`
- Create: `plugins/task-tools/plugin.yaml`
- Create: `plugins/task-tools/plugin.py`
- Create: `plugins/report-issue-tools/plugin.yaml`
- Create: `plugins/report-issue-tools/plugin.py`
- Create: `plugins/cron-tools/plugin.yaml`
- Create: `plugins/cron-tools/plugin.py`
- Create: `src/agent_runner/tools/memory_box_client.py`
- Create: `src/agent_runner/tools/report_issue_client.py`
- Create: `src/agent_runner/tools/cron_client.py`
- Test: `tests/test_memory_box_tools_plugin.py`
- Test: `tests/test_task_tools_plugin.py`
- Test: `tests/test_report_issue_tools_plugin.py`
- Test: `tests/test_cron_tools_plugin.py`

- [ ] **Step 1: Extract clients without changing direct wrappers**

Move reusable HTTP/file operations into client modules, but keep existing direct tool behavior unchanged.

- [ ] **Step 2: Implement plugin wrappers**

Each plugin must expose `register(context)` and return `ToolSpec` objects using the new clients.

- [ ] **Step 3: Test plugin allowlists**

Use `PluginContext(agent_id="cio", ...)` and assert only allowed agents receive tools.

- [ ] **Step 4: Verify**

Run:

```bash
PYTHONPATH=. pytest \
  tests/test_memory_box_tools_plugin.py \
  tests/test_task_tools_plugin.py \
  tests/test_report_issue_tools_plugin.py \
  tests/test_cron_tools_plugin.py
```

- [ ] **Step 5: Commit**

```bash
git add plugins src/agent_runner/tools tests/test_*_tools_plugin.py
git commit -m "feat(plugin): add core operational tool plugins"
```

## Task 5: MT Productivity Plugins

**Files:**

- Create: `plugins/calendar-tools/plugin.py`
- Create: `plugins/calendar-tools/plugin.yaml`
- Create: `plugins/contacts-tools/plugin.py`
- Create: `plugins/contacts-tools/plugin.yaml`
- Create: `plugins/email-digest-tools/plugin.py`
- Create: `plugins/email-digest-tools/plugin.yaml`
- Create: `src/agent_runner/tools/calendar_client.py`
- Create: `src/agent_runner/tools/contacts_client.py`
- Create: `src/agent_runner/tools/email_digest_client.py`
- Test: `tests/test_calendar_tools_plugin.py`
- Test: `tests/test_contacts_tools_plugin.py`
- Test: `tests/test_email_digest_tools_plugin.py`

- [ ] **Step 1: Extract clients from existing MT wrappers**

Preserve existing MT behavior and imports. Plugin clients should call the same underlying CalDAV, contacts, and email digest code paths.

- [ ] **Step 2: Add MT-only plugin manifests**

Use `allowed_agents: [mt]`.

- [ ] **Step 3: Verify**

Run:

```bash
PYTHONPATH=. pytest \
  tests/test_calendar_tools_plugin.py \
  tests/test_contacts_tools_plugin.py \
  tests/test_email_digest_tools_plugin.py \
  tests/test_mt_calendar_tools.py \
  tests/test_mt_contacts_tools.py \
  tests/test_mt_tools.py
```

- [ ] **Step 4: Commit**

```bash
git add plugins src/agent_runner/tools tests/test_calendar_tools_plugin.py tests/test_contacts_tools_plugin.py tests/test_email_digest_tools_plugin.py
git commit -m "feat(plugin): add MT productivity plugins"
```

## Task 6: Perplexity Plugin

**Files:**

- Create: `plugins/perplexity-tools/plugin.py`
- Create: `plugins/perplexity-tools/plugin.yaml`
- Create: `src/agent_runner/tools/perplexity_client.py`
- Modify: `src/agent_runner/tools/perplexity_search.py`
- Test: `tests/test_perplexity_tools_plugin.py`

- [ ] **Step 1: Extract Perplexity client**

Keep the existing direct search tool working. The plugin should call the same client module.

- [ ] **Step 2: Add plugin tests**

Mock the HTTP call and assert the plugin returns a `ToolSpec` named consistently with the existing direct tool.

- [ ] **Step 3: Verify**

Run:

```bash
PYTHONPATH=. pytest tests/test_perplexity_tools_plugin.py
```

- [ ] **Step 4: Commit**

```bash
git add plugins/perplexity-tools src/agent_runner/tools/perplexity_client.py src/agent_runner/tools/perplexity_search.py tests/test_perplexity_tools_plugin.py
git commit -m "feat(plugin): add Perplexity search plugin"
```

## Task 7: Packaging and Inventory

**Files:**

- Modify: `Dockerfile`
- Create: `plugins/README.md`
- Create: `docs/jarvisos-plugin-layout.md`
- Test: `tests/test_docker_plugin_packaging.py`
- Test: `tests/test_plugin_directory_contract.py`
- Test: `tests/test_plugin_tool_inventory.py`

- [ ] **Step 1: Package plugins**

Add to `Dockerfile`:

```dockerfile
COPY plugins/ ./plugins/
```

Do not remove any existing `COPY` for current source, vendor, mailctl, html-text, migrations, or skills.

- [ ] **Step 2: Add inventory tests**

Assert plugin manifests are valid and no plugin attempts to shadow a direct tool unless explicitly allowlisted.

- [ ] **Step 3: Verify**

Run:

```bash
PYTHONPATH=. pytest \
  tests/test_docker_plugin_packaging.py \
  tests/test_plugin_directory_contract.py \
  tests/test_plugin_tool_inventory.py
```

- [ ] **Step 4: Commit**

```bash
git add Dockerfile plugins/README.md docs/jarvisos-plugin-layout.md tests/test_docker_plugin_packaging.py tests/test_plugin_directory_contract.py tests/test_plugin_tool_inventory.py
git commit -m "chore(plugin): package plugins and document inventory"
```

## Task 8: Full Verification and Live Readiness

**Files:**

- No production source changes unless tests expose a specific bug.

- [ ] **Step 1: Run focused plugin suite**

```bash
PYTHONPATH=. pytest \
  tests/test_plugin_manifest.py \
  tests/test_plugin_tool_spec.py \
  tests/test_plugin_loader.py \
  tests/test_plugin_registry.py \
  tests/test_plugin_client_integration.py \
  tests/test_memory_box_tools_plugin.py \
  tests/test_task_tools_plugin.py \
  tests/test_report_issue_tools_plugin.py \
  tests/test_cron_tools_plugin.py \
  tests/test_calendar_tools_plugin.py \
  tests/test_contacts_tools_plugin.py \
  tests/test_email_digest_tools_plugin.py \
  tests/test_perplexity_tools_plugin.py \
  tests/test_plugin_tool_inventory.py
```

Expected: all pass.

- [ ] **Step 2: Run live-regression guard suite**

```bash
PYTHONPATH=. pytest \
  tests/test_dos_whoop_sync.py \
  tests/test_daily_fitness_migration.py \
  tests/test_dos_daily_fitness_import.py \
  tests/test_cfo_opportunity_watchlist.py \
  tests/test_cfo_worker_dispatch.py \
  tests/test_chro_db_schema.py \
  tests/test_coh_db_schema.py \
  tests/test_email_extraction_writes.py \
  tests/test_plane_cli.py \
  tests/test_plane_client.py \
  tests/test_plane_service.py
```

Expected: all pass. Any failure here blocks merge because it indicates a live regression.

- [ ] **Step 3: Build image locally**

```bash
docker build -t 10.10.200.61:5000/jarvios-platform:plugin-forward-port .
```

Expected: build succeeds and `python scripts/gen_supervisord.py` still includes all live agents and workers.

- [ ] **Step 4: Smoke plugin presence in image**

```bash
docker run --rm -e PYTHONPATH=/app/src \
  10.10.200.61:5000/jarvios-platform:plugin-forward-port \
  python - <<'PY'
import importlib.util
from pathlib import Path
print("plugin_runtime", bool(importlib.util.find_spec("plugin_runtime.loader")))
print("plugins", Path("/app/plugins").exists())
PY
```

Expected output:

```text
plugin_runtime True
plugins True
```

- [ ] **Step 5: Commit verification docs if needed**

If verification reveals no source changes, do not create an empty commit. If a small compatibility fix is needed, commit it with:

```bash
git add <changed-files>
git commit -m "fix(plugin): preserve live compatibility"
```

## Branch Cleanup Rule

After this plan is committed on `feature/plugin-live-forward-port`, remove stale branches and worktrees:

```bash
git worktree remove --force .worktrees/plane-task-sync
git branch -D feature/plane-task-sync
git worktree remove .worktrees/plugin-directory-migration
git branch -D feature/plugin-directory-migration
git push origin --delete feature/plugin-directory-migration
git worktree remove .worktrees/plugin-kernel-tool-migration
git branch -D feature/plugin-kernel-tool-migration
```

`feature/plugin-live-forward-port` becomes the canonical branch for future plugin integration work.

## Self-Review

- Spec coverage: covers runtime contract, loader, registry, core plugins, MT productivity plugins, Perplexity, Docker packaging, inventory, and live-regression gates.
- Placeholder scan: no task depends on direct merge of stale branches; all branch-derived work is framed as forward-port on current `main`.
- Type consistency: uses `PluginContext`, `PluginManifest`, and `ToolSpec` consistently across tasks.
