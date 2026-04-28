"""Jarvis agent entry point — invoked by supervisord."""

import logging
import os
from pathlib import Path

import uvicorn

from agents.ceo.config import build_jarvis_config
from agent_runner.app import create_app


def main():
    workspace = os.environ.get("CEO_WORKSPACE", "/app/workspace/ceo")
    config = build_jarvis_config(workspace_root=Path(workspace))

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    app = create_app(config)
    port = int(os.environ.get("AGENT_PORT", str(config.port)))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=config.log_level.lower())


if __name__ == "__main__":
    main()
