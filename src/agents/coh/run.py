"""DrHouse agent entry point — invoked by supervisord."""

import logging
import os
from pathlib import Path

import uvicorn

from agents.coh.config import build_drhouse_config
from agent_runner.app import create_app


def main():
    workspace = os.environ.get("COH_WORKSPACE", "/app/workspace/coh")
    config = build_drhouse_config(workspace_root=Path(workspace))

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    app = create_app(config)

    # Mount the COH HTTP API (medical business plane) — additive; the existing
    # control-plane endpoints (/chat, /a2a, /health, ...) are untouched.
    try:
        from agents.coh.api import router as coh_router
        app.include_router(coh_router)
    except Exception as exc:  # pragma: no cover — defensive at startup
        logging.getLogger(__name__).error(
            "COH HTTP router failed to mount: %s", exc, exc_info=True
        )

    port = int(os.environ.get("AGENT_PORT", str(config.port)))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=config.log_level.lower())


if __name__ == "__main__":
    main()
