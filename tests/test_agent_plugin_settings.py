from pathlib import Path

from src.agent_runner.config import AgentConfig


def _config(agent_id: str = "ceo", **kwargs) -> AgentConfig:
    return AgentConfig(
        id=agent_id,
        name="Test Agent",
        port=8099,
        workspace_path=Path("/tmp/workspace/test"),
        telegram_token_env="TELEGRAM_TEST_TOKEN",
        telegram_chat_id_env="TELEGRAM_TEST_CHAT_ID",
        **kwargs,
    )


def test_plugin_root_defaults_to_app_plugins(monkeypatch):
    monkeypatch.delenv("JARVIOS_PLUGIN_ROOT", raising=False)

    config = _config()

    assert config.effective_plugin_root == Path("/app/plugins")


def test_plugin_root_can_be_overridden_by_environment(monkeypatch):
    monkeypatch.setenv("JARVIOS_PLUGIN_ROOT", "/tmp/jarvisos/plugins")

    config = _config()

    assert config.effective_plugin_root == Path("/tmp/jarvisos/plugins")


def test_plugin_loading_can_be_disabled(monkeypatch):
    monkeypatch.delenv("JARVIOS_PLUGINS_ENABLED", raising=False)
    config = _config(plugins_enabled=False)

    assert config.effective_plugins_enabled is False

    monkeypatch.setenv("JARVIOS_PLUGINS_ENABLED", "off")
    config = _config(plugins_enabled=True)

    assert config.effective_plugins_enabled is False


def test_default_plugin_allowlist_is_conservative(monkeypatch):
    monkeypatch.delenv("JARVIOS_PLUGINS", raising=False)
    monkeypatch.delenv("JARVIOS_PLUGINS_CEO", raising=False)

    assert _config("ceo").plugin_allowlist == (
        "memory-box-tools",
        "report-issue-tools",
        "task-tools",
    )
    assert _config("dos").plugin_allowlist == ()


def test_agent_specific_plugin_names_can_be_configured(monkeypatch):
    monkeypatch.delenv("JARVIOS_PLUGINS", raising=False)
    monkeypatch.setenv("JARVIOS_PLUGINS_CEO", "memory-box-tools,task-tools")

    config = _config("ceo", plugins=["report-issue-tools"])

    assert config.plugin_allowlist == ("memory-box-tools", "task-tools")


def test_configured_empty_plugin_list_disables_agent_plugins(monkeypatch):
    monkeypatch.delenv("JARVIOS_PLUGINS", raising=False)
    monkeypatch.delenv("JARVIOS_PLUGINS_CIO", raising=False)

    config = _config("cio", plugins=[])

    assert config.plugin_allowlist == ()
