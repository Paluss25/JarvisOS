"""Platform API entry point — invoked by supervisord."""

import logging
import os

import uvicorn

from platform_api.app import create_platform_app


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    app = create_platform_app()
    port = int(os.environ.get("PLATFORM_PORT", "8900"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
