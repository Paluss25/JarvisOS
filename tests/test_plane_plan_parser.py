from integrations.plane.plan_parser import parse_homelab_plan


def test_parse_homelab_plan_extracts_title_phases_and_tasks(tmp_path):
    plan_path = tmp_path / "2026-05-04-plane-task-sync.md"
    plan_path.write_text(
        """---
project: JarvisOS
domain: jarvisos-platform
---

# Plane task sync

**Goal:** Sync HomeLab implementation plans into Plane.

## P0 — Foundation

### P0.T1 — Add config

### P0.T2 — Wire client

## P1 — Sync

### P1.T1 — Push tasks
""",
        encoding="utf-8",
    )

    parsed = parse_homelab_plan(plan_path)

    assert parsed.path == plan_path
    assert parsed.title == "Plane task sync"
    assert parsed.project == "JarvisOS"
    assert parsed.domain == "jarvisos-platform"
    assert parsed.goal == "Sync HomeLab implementation plans into Plane."
    assert parsed.external_id.endswith("2026-05-04-plane-task-sync.md")
    assert [phase.id for phase in parsed.phases] == ["P0", "P1"]
    assert [phase.name for phase in parsed.phases] == ["Foundation", "Sync"]
    assert [phase.external_id for phase in parsed.phases] == [
        f"{plan_path}#P0",
        f"{plan_path}#P1",
    ]
    assert [task.id for task in parsed.tasks] == ["P0.T1", "P0.T2", "P1.T1"]
    assert [task.name for task in parsed.tasks] == ["Add config", "Wire client", "Push tasks"]
    assert [task.phase_id for task in parsed.tasks] == ["P0", "P0", "P1"]
    assert [task.external_id for task in parsed.tasks] == [
        f"{plan_path}#P0.T1",
        f"{plan_path}#P0.T2",
        f"{plan_path}#P1.T1",
    ]


def test_parse_homelab_plan_ignores_frontmatter_and_fenced_code(tmp_path):
    plan_path = tmp_path / "plan.md"
    plan_path.write_text(
        """---
project: JarvisOS
domain: jarvisos-platform
# Fake title
---

# Real plan

```markdown
## P9 — Fake phase
### P9.T1 — Fake task
**Goal:** Fake goal
```

**Goal:** Real goal

## P0 — Foundation

### P0.T1 — Add parser
""",
        encoding="utf-8",
    )

    parsed = parse_homelab_plan(plan_path)

    assert parsed.title == "Real plan"
    assert parsed.goal == "Real goal"
    assert [phase.id for phase in parsed.phases] == ["P0"]
    assert [phase.name for phase in parsed.phases] == ["Foundation"]
    assert [task.id for task in parsed.tasks] == ["P0.T1"]
    assert [task.name for task in parsed.tasks] == ["Add parser"]
    assert [task.phase_id for task in parsed.tasks] == ["P0"]
