# src/agent_runner/__init__.py
"""Generic agent runner package — reused by all peer agents."""

from .config import AgentConfig
from .client import BaseAgentClient, create_agent_client

__all__ = ["AgentConfig", "BaseAgentClient", "create_agent_client"]
