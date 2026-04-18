"""Async FIFO queue for memory pipeline — a2a messages get higher priority."""

import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(order=True)
class PipelineItem:
    priority: int                          # 0 = a2a (highest), 1 = user
    agent_id: str = field(compare=False)
    message: str = field(compare=False)
    response: str = field(compare=False)
    source: str = field(compare=False)     # "telegram" | "a2a" | "dashboard"


class PipelineQueue:
    """Priority queue: a2a (priority=0) > user (priority=1)."""

    def __init__(self, maxsize: int = 100):
        self._queue: asyncio.PriorityQueue[PipelineItem] = asyncio.PriorityQueue(maxsize=maxsize)

    async def put(self, item: PipelineItem) -> None:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            logger.warning("pipeline_queue: full — dropping item from %s", item.agent_id)

    async def get(self) -> PipelineItem:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    def qsize(self) -> int:
        return self._queue.qsize()
