"""Async post-response memory pipeline — extract, dedup, store."""

import logging
from typing import Any

from agent_runner.memory.pipeline.queue import PipelineItem, PipelineQueue
from agent_runner.memory.pipeline.extractor import extract_memories
from agent_runner.memory.pipeline.deduplicator import deduplicate
from agent_runner.memory.pipeline.store import load_existing_for_agent, store_entry

logger = logging.getLogger(__name__)


async def run_pipeline(queue: PipelineQueue, config: Any) -> None:
    """Consume PipelineItems forever, running extract → dedup → store per item.

    Designed to run as a background asyncio.Task. Exits only on CancelledError.
    """
    agent_id = getattr(config, "id", "unknown")
    logger.info("pipeline[%s]: consumer started", agent_id)

    while True:
        item: PipelineItem = await queue.get()
        try:
            candidates = await extract_memories(item.agent_id, item.message, item.response)
            if not candidates:
                continue

            existing = load_existing_for_agent(config)

            for candidate in candidates:
                try:
                    action = await deduplicate(candidate, existing)
                    await store_entry(item.agent_id, candidate, action, config)
                except Exception as exc:
                    logger.warning("pipeline[%s]: entry error — %s", agent_id, exc)
        except Exception as exc:
            logger.warning("pipeline[%s]: item processing error — %s", agent_id, exc)
        finally:
            queue.task_done()
