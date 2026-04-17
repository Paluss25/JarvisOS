# src/agent_runner/memory/workspace_loader.py
"""Re-export shim — P0.T3 will replace with the full extracted implementation."""
from src.memory.workspace_loader import (
    load_workspace_context,
    get_today_memory_path,
)

__all__ = ["load_workspace_context", "get_today_memory_path"]
