import os
from pathlib import Path

import yaml
from pydantic import BaseModel


class CfoCliConfig(BaseModel):
    sidecar_url: str = "http://cfo-data-service:8000"
    token: str


def load_config() -> CfoCliConfig:
    env_token = os.environ.get("CFO_CLI_TOKEN")
    cfg_path = Path.home() / ".cfo-cli" / "config.yml"
    data: dict = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text()) or {}
    if env_token:
        data["token"] = env_token
    return CfoCliConfig(**data)
