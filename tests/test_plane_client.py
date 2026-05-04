import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from integrations.plane.config import PlaneConfig, load_plane_config


def test_load_plane_config_reads_env_without_exposing_key(monkeypatch):
    monkeypatch.setenv("PLANE_API_KEY", "plane_api_secret")
    monkeypatch.setenv("PLANE_BASE_URL", "https://api.plane.so")
    monkeypatch.setenv("PLANE_WORKSPACE_SLUG", "homelab")
    monkeypatch.setenv("PLANE_DEFAULT_PROJECT_ID", "project-123")
    monkeypatch.setenv("PLANE_PROJECT_MAP_JSON", '{"jarvios-platform": "project-ai"}')

    config = load_plane_config()

    assert config.api_key == "plane_api_secret"
    assert config.base_url == "https://api.plane.so"
    assert config.workspace_slug == "homelab"
    assert config.default_project_id == "project-123"
    assert config.project_map == {"jarvios-platform": "project-ai"}
    assert "plane_api_secret" not in repr(config)


def test_load_plane_config_requires_api_key(monkeypatch):
    for key in list(os.environ):
        if key.startswith("PLANE_"):
            monkeypatch.delenv(key, raising=False)

