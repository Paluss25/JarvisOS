import httpx

from cfo_cli.config import load_config


def client() -> httpx.Client:
    cfg = load_config()
    return httpx.Client(
        base_url=cfg.sidecar_url,
        headers={"Authorization": f"Bearer {cfg.token}"},
        timeout=30.0,
    )
