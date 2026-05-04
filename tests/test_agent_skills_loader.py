from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.agent_runner.client import _build_system_prompt
from src.agent_runner import AgentConfig
from src.agent_runner.memory.workspace_loader import load_workspace_context
from src.agent_runner.memory.workspace_loader import skills_snapshot_signature


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


def test_skills_allowlist_filters_loaded_skills(tmp_path):
    agent_workspace = tmp_path / "ceo"
    _write(agent_workspace / "SOUL.md", "agent soul")
    _write(agent_workspace / "AGENTS.md", "agent manual")
    _write(agent_workspace / "USER.md", "user")
    _write(
        tmp_path / "skills" / "email-cli" / "SKILL.md",
        "---\nname: email-cli\ndescription: Email.\n---\n\n# Email\n",
    )
    _write(
        tmp_path / "skills" / "html-text-extract" / "SKILL.md",
        "---\nname: html-text-extract\ndescription: HTML.\n---\n\n# HTML\n",
    )

    ctx = load_workspace_context(agent_workspace, skills_allowlist=["email-cli"])

    assert "email-cli" in ctx["skills"]
    assert "html-text-extract" not in ctx["skills"]


def test_skills_requires_bins_gates_missing_binary(tmp_path):
    agent_workspace = tmp_path / "ceo"
    _write(agent_workspace / "SOUL.md", "agent soul")
    _write(agent_workspace / "AGENTS.md", "agent manual")
    _write(agent_workspace / "USER.md", "user")
    _write(
        tmp_path / "skills" / "missing-tool" / "SKILL.md",
        "---\n"
        "name: missing-tool\n"
        "description: Missing tool.\n"
        "metadata: {\"agentSkills\":{\"requires\":{\"bins\":[\"definitely-not-installed-bin\"]}}}\n"
        "---\n\n"
        "# Missing\n",
    )

    ctx = load_workspace_context(agent_workspace)

    assert "missing-tool" not in ctx["skills"]


def test_skills_snapshot_signature_changes_when_skill_changes(tmp_path):
    agent_workspace = tmp_path / "ceo"
    _write(agent_workspace / "SOUL.md", "agent soul")
    _write(agent_workspace / "AGENTS.md", "agent manual")
    _write(agent_workspace / "USER.md", "user")
    skill = tmp_path / "skills" / "email-cli" / "SKILL.md"
    _write(skill, "---\nname: email-cli\ndescription: Email.\n---\n\n# Email\n")

    before = skills_snapshot_signature(agent_workspace, skills_allowlist=None)
    _write(skill, "---\nname: email-cli\ndescription: Email changed.\n---\n\n# Email\n")
    after = skills_snapshot_signature(agent_workspace, skills_allowlist=None)

    assert before != after


def test_agent_config_skill_allowlist_from_env(monkeypatch):
    monkeypatch.setenv("JARVIOS_SKILLS_CEO", "email-cli,html-text-extract")
    config = AgentConfig(
        id="ceo",
        name="Jarvis",
        port=8000,
        workspace_path=Path("/tmp/ceo"),
        telegram_token_env="T",
        telegram_chat_id_env="C",
    )

    assert config.skill_allowlist == ["email-cli", "html-text-extract"]


def test_client_refreshes_system_prompt_when_skill_snapshot_changes(tmp_path):
    from src.agent_runner import client as client_mod

    agent_workspace = tmp_path / "ceo"
    _write(agent_workspace / "SOUL.md", "agent soul")
    _write(agent_workspace / "AGENTS.md", "agent manual")
    _write(agent_workspace / "USER.md", "user")
    skill = tmp_path / "skills" / "email-cli" / "SKILL.md"
    _write(skill, "---\nname: email-cli\ndescription: Email.\n---\n\n# Email\n")
    config = AgentConfig(
        id="ceo",
        name="Jarvis",
        port=8000,
        workspace_path=agent_workspace,
        telegram_token_env="T",
        telegram_chat_id_env="C",
    )
    config.skills_watch_debounce_s = 0.0

    with patch("src.agent_runner.client.DailyLogger"):
        agent = client_mod.BaseAgentClient(
            config=config,
            system_prompt="old prompt",
            options=client_mod.ClaudeAgentOptions(system_prompt="old prompt"),
            skills_signature="old",
        )

    _write(skill, "---\nname: email-cli\ndescription: Email changed.\n---\n\n# Email\n")
    refreshed = agent._refresh_skill_snapshot_options()

    assert refreshed is True
    assert "Email changed" in agent._system_prompt
    assert "Email changed" in agent._options.system_prompt
