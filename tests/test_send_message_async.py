"""Unit tests for the async send_message path.

Covers the pure helpers (no Redis required):
- ``_coerce_mode`` normalisation
- ``_truncate`` boundary behaviour
- ``_build_continuation_envelope`` envelope shape and chain propagation
- ``MAX_HOPS`` resolution from env

The Redis-backed integration is exercised end-to-end in the P5 deploy
smoke tests; here we keep things hermetic and fast.
"""

import importlib
import os
import time

import pytest

from agent_runner.comms.message import A2AMessage
from agent_runner.comms.pending_store import PendingEntry
from agent_runner.tools import send_message as sm


def test_coerce_mode_defaults_to_sync_when_missing():
    assert sm._coerce_mode(None) == "sync"
    assert sm._coerce_mode("") == "sync"
    assert sm._coerce_mode("nonsense") == "sync"


def test_coerce_mode_accepts_async_and_is_case_insensitive():
    assert sm._coerce_mode("async") == "async"
    assert sm._coerce_mode("ASYNC") == "async"
    assert sm._coerce_mode(" Async ") == "async"


def test_coerce_mode_accepts_sync_explicitly():
    assert sm._coerce_mode("sync") == "sync"
    assert sm._coerce_mode("SYNC") == "sync"


def test_truncate_returns_none_for_empty_inputs():
    assert sm._truncate(None, 100) is None
    assert sm._truncate("", 100) is None
    assert sm._truncate("   ", 100) is None


def test_truncate_keeps_short_strings_intact():
    assert sm._truncate("short", 100) == "short"


def test_truncate_clips_long_strings_with_ellipsis():
    out = sm._truncate("x" * 600, 500)
    assert out is not None
    assert len(out) == 500
    assert out.endswith("…")


def test_max_hops_default_is_5():
    # Unset any override before reload to assert the default.
    os.environ.pop("JARVIOS_A2A_MAX_HOPS", None)
    importlib.reload(sm)
    assert sm.MAX_HOPS == 5


def test_max_hops_env_override():
    os.environ["JARVIOS_A2A_MAX_HOPS"] = "3"
    importlib.reload(sm)
    try:
        assert sm.MAX_HOPS == 3
    finally:
        del os.environ["JARVIOS_A2A_MAX_HOPS"]
        importlib.reload(sm)


def test_continuation_envelope_basic_shape():
    entry = PendingEntry(
        correlation_id="cid-12345678",
        from_agent="ceo",
        to_agent="cio",
        original_message="build the WHOOP CLI",
        sent_at=time.time(),
        mode="async",
        root_correlation_id="cid-12345678",
        hop_count=1,
        max_hops=5,
        context_hint=None,
    )
    response = A2AMessage(
        from_agent="cio",
        to_agent="ceo",
        type="response",
        payload="Done. CLI built and registered at /opt/cli/whoop.",
        correlation_id="cid-12345678",
    )
    envelope = sm._build_continuation_envelope(
        self_id="ceo", entry=entry, response=response
    )
    assert envelope.type == "notification"
    assert envelope.from_agent == "cio"           # responder
    assert envelope.to_agent == "ceo"             # ourselves
    assert envelope.correlation_id == "cid-12345678"
    assert envelope.mode == "async"
    assert envelope.parent_correlation_id == "cid-12345678"
    assert envelope.hop_count == 1
    assert envelope.max_hops == 5
    # Payload is self-contained: original request, reply text, chain metadata.
    assert "[A2A-CONTINUATION]" in envelope.payload
    assert "build the WHOOP CLI" in envelope.payload
    assert "Done. CLI built" in envelope.payload
    assert "From cio" not in envelope.payload  # responder name appears differently
    assert "Reply from cio" in envelope.payload
    assert "cid=cid-1234" in envelope.payload  # truncated cid hint


def test_continuation_envelope_includes_context_hint_when_set():
    entry = PendingEntry(
        correlation_id="cid-with-hint",
        from_agent="ceo",
        to_agent="cio",
        original_message="ping",
        sent_at=time.time(),
        mode="async",
        root_correlation_id="cid-with-hint",
        hop_count=1,
        max_hops=5,
        context_hint="Was checking infra health before EOD.",
    )
    response = A2AMessage(
        from_agent="cio",
        to_agent="ceo",
        type="response",
        payload="all green",
        correlation_id="cid-with-hint",
    )
    envelope = sm._build_continuation_envelope(
        self_id="ceo", entry=entry, response=response
    )
    assert "Your original context note: Was checking infra health" in envelope.payload


def test_continuation_envelope_propagates_chain_for_nested_hops():
    """Hop=3 should appear verbatim and root_correlation_id propagates."""
    entry = PendingEntry(
        correlation_id="cid-grandchild",
        from_agent="ceo",
        to_agent="dos",
        original_message="generate week plan",
        sent_at=time.time(),
        mode="async",
        root_correlation_id="cid-original-root",
        hop_count=3,
        max_hops=5,
    )
    response = A2AMessage(
        from_agent="dos",
        to_agent="ceo",
        type="response",
        payload="plan ready",
        correlation_id="cid-grandchild",
    )
    envelope = sm._build_continuation_envelope(
        self_id="ceo", entry=entry, response=response
    )
    assert envelope.root_correlation_id == "cid-original-root"
    assert envelope.hop_count == 3
    assert "hop=3/5" in envelope.payload
    assert "root=cid-orig" in envelope.payload  # 8-char prefix of root


@pytest.mark.parametrize(
    "fallback_input,expected",
    [
        (None, "sync"),
        ({"foo": "bar"}, "sync"),
        ([], "sync"),
        (123, "sync"),
    ],
)
def test_coerce_mode_garbage_falls_back_to_default(fallback_input, expected):
    assert sm._coerce_mode(fallback_input) == expected
