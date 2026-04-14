"""Unit tests for ModelFactory — no real API calls, no file I/O.

agno is NOT installed in the test venv; we mock sys.modules for all agno
imports so tests run without the full dependency stack.
"""

import sys
import pytest
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Stub out agno so factory.py imports don't crash
# ---------------------------------------------------------------------------
def _make_agno_stubs():
    """Insert mock agno modules into sys.modules before any src import."""
    for mod in ["agno", "agno.models", "agno.models.openai", "agno.models.groq",
                "agno.models.anthropic", "agno.models.google", "agno.models.ollama"]:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)

    # Each provider module needs a class with the right name
    _add_class("agno.models.openai", "OpenAIChat")
    _add_class("agno.models.groq", "Groq")
    _add_class("agno.models.anthropic", "Claude")
    _add_class("agno.models.google", "Gemini")
    _add_class("agno.models.ollama", "Ollama")


def _add_class(module_path: str, class_name: str):
    mod = sys.modules[module_path]
    if not hasattr(mod, class_name):
        cls = MagicMock(name=class_name)
        setattr(mod, class_name, cls)


_make_agno_stubs()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_AGENT_MODELS_YAML = """
agents:
  jarvis:
    role: "CEO"
    primary:
      provider: openai-codex
      model: "gpt-5.4"
    fallback:
      - provider: groq
        model: "llama-3.3-70b-versatile"
  simple:
    role: "Simple"
    primary:
      provider: groq
      model: "llama-3.3-70b-versatile"
"""


@pytest.fixture
def workspace_dir(tmp_path):
    """Temporary workspace with config/agent-models.yaml."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "agent-models.yaml").write_text(MINIMAL_AGENT_MODELS_YAML)
    return tmp_path


def _settings_mock(workspace_path: str):
    """Return a mock settings object for patching src.config.settings."""
    ms = MagicMock()
    ms.workspace_path = Path(workspace_path)
    ms.groq_key = "test-groq-key"
    ms.codex_auth_path = Path("/nonexistent/auth.json")
    ms.ANTHROPIC_API_KEY = ""
    ms.GOOGLE_API_KEY = ""
    ms.OPENAI_API_KEY = ""
    return ms


# ---------------------------------------------------------------------------
# _build_single_model
# ---------------------------------------------------------------------------

class TestBuildSingleModel:

    def test_groq_model_instantiated(self):
        """Groq provider → Groq() called with correct args."""
        from src.models.factory import _build_single_model

        with patch("src.config.settings") as ms:
            ms.groq_key = "test-key"
            ms.codex_auth_path = Path("/nonexistent/auth.json")
            result = _build_single_model("groq", "llama-3.3-70b-versatile")

        # agno.models.groq.Groq is a MagicMock — verify it was called
        import agno.models.groq as groq_mod
        groq_mod.Groq.assert_called_with(id="llama-3.3-70b-versatile", api_key="test-key")

    def test_unknown_provider_raises(self):
        from src.models.factory import _build_single_model
        with pytest.raises(ValueError, match="Unknown model provider"):
            _build_single_model("unknown-provider", "model-x")


# ---------------------------------------------------------------------------
# build_agent_model
# ---------------------------------------------------------------------------

class TestBuildAgentModel:

    def test_valid_agent_returns_fallback_model(self, workspace_dir):
        """build_agent_model returns FallbackModel with correct chain."""
        mock_codex = MagicMock()
        mock_codex.id = "gpt-5.4"
        mock_groq = MagicMock()
        mock_groq.id = "llama-3.3-70b-versatile"

        with patch("src.config.settings", _settings_mock(str(workspace_dir))):
            with patch("src.models.factory._build_single_model",
                       side_effect=[mock_codex, mock_groq]):
                from src.models.factory import build_agent_model
                result = build_agent_model("jarvis")

        from src.models.fallback_model import FallbackModel
        assert isinstance(result, FallbackModel)
        assert result.id == "gpt-5.4"
        assert len(result.models) == 2

    def test_invalid_agent_raises(self, workspace_dir):
        with patch("src.config.settings", _settings_mock(str(workspace_dir))):
            with patch("src.models.factory._build_single_model"):
                from src.models.factory import build_agent_model
                with pytest.raises(ValueError, match="No model config for agent"):
                    build_agent_model("nonexistent")

    def test_single_model_no_fallback(self, workspace_dir):
        """Agent with no fallback list gets a single-model FallbackModel."""
        mock_groq = MagicMock()
        mock_groq.id = "llama-3.3-70b-versatile"

        with patch("src.config.settings", _settings_mock(str(workspace_dir))):
            with patch("src.models.factory._build_single_model", return_value=mock_groq):
                from src.models.factory import build_agent_model
                result = build_agent_model("simple")

        from src.models.fallback_model import FallbackModel
        assert isinstance(result, FallbackModel)
        assert len(result.models) == 1

    def test_missing_yaml_raises(self, tmp_path):
        """Raises FileNotFoundError when config file is missing."""
        with patch("src.config.settings", _settings_mock(str(tmp_path))):
            from src.models.factory import build_agent_model
            with pytest.raises(FileNotFoundError):
                build_agent_model("jarvis")

    def test_repr_shows_chain(self, workspace_dir):
        """FallbackModel repr shows the full fallback chain."""
        models = [MagicMock(id="gpt-5.4"), MagicMock(id="llama-3.3")]

        with patch("src.config.settings", _settings_mock(str(workspace_dir))):
            with patch("src.models.factory._build_single_model",
                       side_effect=models):
                from src.models.factory import build_agent_model
                result = build_agent_model("jarvis")

        assert "gpt-5.4" in repr(result)
        assert "llama-3.3" in repr(result)
