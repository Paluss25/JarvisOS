#!/usr/bin/env python3
"""Generate supervisord program configs from agents.yaml.

Writes one .conf file per agent to /etc/supervisor/conf.d/.
Run at container startup before supervisord.
"""

import sys
from pathlib import Path

import yaml

AGENTS_YAML = Path("/app/agents.yaml")
OUTPUT_DIR = Path("/etc/supervisor/conf.d")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(AGENTS_YAML) as f:
        data = yaml.safe_load(f)

    for agent in data.get("agents", []):
        agent_id = agent["id"]
        port = agent["port"]
        conf = f"""[program:{agent_id}]
command=python -m agents.{agent_id}.run
directory=/app
environment=AGENT_PORT={port}
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
"""
        (OUTPUT_DIR / f"{agent_id}.conf").write_text(conf)
        print(f"Generated config for agent '{agent_id}' on port {port}")


if __name__ == "__main__":
    main()
