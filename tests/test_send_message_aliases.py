import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_runner.tools.send_message import create_send_message_tool


class _FakeRedisA2A:
    def __init__(self):
        self.callbacks = []
        self.published = []

    def on_message(self, callback):
        self.callbacks.append(callback)

    async def publish(self, msg):
        self.published.append(msg)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_send_message_resolves_business_alias_for_notifications():
    redis_a2a = _FakeRedisA2A()
    send_message = create_send_message_tool("ceo", redis_a2a)

    result = _run(send_message({
        "to": "drhouse",
        "message": "HDL handoff",
        "wait_response": False,
    }))

    assert "to coh" in result
    assert redis_a2a.published[0].to_agent == "coh"
