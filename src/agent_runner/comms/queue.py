"""Agent-level message queue with priority ordering.

Priority values: 0 = a2a (higher), 1 = user (lower).
asyncio.PriorityQueue ensures lower numeric priority is served first.
"""

import asyncio
from dataclasses import dataclass, field


@dataclass(order=True)
class QueueItem:
    priority: int                          # 0=a2a, 1=user
    message: str = field(compare=False)
    session_id: str = field(compare=False)
    source: str = field(compare=False)     # "a2a", "telegram", "dashboard"
    correlation_id: str | None = field(default=None, compare=False)
    from_agent: str | None = field(default=None, compare=False)


class AgentQueue:
    """Priority queue for incoming agent messages.

    A2A messages (priority=0) are dequeued before user Telegram messages
    (priority=1) when the agent is busy.
    """

    def __init__(self, maxsize: int = 50):
        self._queue: asyncio.PriorityQueue[QueueItem] = asyncio.PriorityQueue(maxsize=maxsize)

    async def put(self, item: QueueItem) -> None:
        await self._queue.put(item)

    async def get(self) -> QueueItem:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    def qsize(self) -> int:
        return self._queue.qsize()
