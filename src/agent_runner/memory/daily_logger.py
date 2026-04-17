# src/agent_runner/memory/daily_logger.py
"""Re-export shim — P0.T3 will replace with the full extracted implementation."""
from src.memory.daily_logger import DailyLogger, log_fallback_event

__all__ = ["DailyLogger", "log_fallback_event"]
