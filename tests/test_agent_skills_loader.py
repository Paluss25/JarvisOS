from pathlib import Path

from src.agent_runner.client import _build_system_prompt
from src.agent_runner.memory.workspace_loader import load_workspace_context


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_loads_shared_agentskills_from_parent_workspace(tmp_path):
    agent_workspace = tmp_path / "ceo"
    _write(agent_workspace / "SOUL.md", "agent soul")
    _write(agent_workspace / "AGENTS.md", "agent manual")
    _write(agent_workspace / "USER.md", "user")
    _write(
        tmp_path / "skills" / "html-text-extract" / "SKILL.md",
        "---\n"
        "name: html-text-extract\n"
        "description: Extract clean text from HTML.\n"
        "---\n\n"
        "# HTML Text Extraction\n\n"
        "Use `html-text extract page.html`.\n",
    )

    ctx = load_workspace_context(agent_workspace)

    assert "html-text-extract" in ctx["skills"]
    assert "Extract clean text from HTML" in ctx["skills"]
    assert "html-text extract page.html" in ctx["skills"]


def test_system_prompt_includes_skills_section():
    prompt = _build_system_prompt({
        "soul": "identity",
        "skills": "### html-text-extract\nUse `html-text`.",
    })

    assert "## Skills" in prompt
    assert "### html-text-extract" in prompt
