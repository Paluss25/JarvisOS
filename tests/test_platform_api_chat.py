from uuid import UUID

from platform_api.links import build_chat_link
from platform_api.chat import (
    build_chat_a2a_event,
    build_chat_a2a_message,
    build_chat_context,
    build_chat_decision_payload,
)


def test_build_chat_link_encodes_operational_context_in_stable_order():
    assert build_chat_link(
        "cio",
        task_id="00000000-0000-0000-0000-000000000002",
        trace_id="trace chat/1",
        log_event_id="log-1",
        memory_event_id="mem-1",
    ) == (
        "/agents/cio/chat?"
        "task_id=00000000-0000-0000-0000-000000000002"
        "&trace_id=trace+chat%2F1"
        "&log_event_id=log-1"
        "&memory_event_id=mem-1"
    )

    assert build_chat_link("cfo") == "/agents/cfo/chat"


def test_build_chat_context_exposes_attachments_metrics_and_links():
    context = build_chat_context(
        agent_id="cio",
        task_id="00000000-0000-0000-0000-000000000002",
        trace_id="trace-chat-1",
        log_event_id="00000000-0000-0000-0000-000000000003",
        memory_event_id="00000000-0000-0000-0000-000000000004",
    )

    assert context["agent_id"] == "cio"
    assert context["metrics"] == {"attachment_count": 4}
    assert context["links"] == {
        "agent": "/agents/cio",
        "chat": "/agents/cio/chat",
        "cockpit": "/agents/cio/cockpit",
        "task": "/tasks/00000000-0000-0000-0000-000000000002",
        "trace": "/traces/trace-chat-1",
        "log": "/logs/00000000-0000-0000-0000-000000000003",
        "logs": "/logs?trace_id=trace-chat-1",
        "memory": "/memory/events/00000000-0000-0000-0000-000000000004",
        "a2a": "/a2a",
    }
    assert context["attachments"] == [
        {"kind": "task", "id": "00000000-0000-0000-0000-000000000002", "href": "/tasks/00000000-0000-0000-0000-000000000002"},
        {"kind": "trace", "id": "trace-chat-1", "href": "/traces/trace-chat-1"},
        {"kind": "log", "id": "00000000-0000-0000-0000-000000000003", "href": "/logs/00000000-0000-0000-0000-000000000003"},
        {"kind": "memory", "id": "00000000-0000-0000-0000-000000000004", "href": "/memory/events/00000000-0000-0000-0000-000000000004"},
    ]


def test_build_chat_a2a_event_records_route_context_and_correlation():
    event = build_chat_a2a_event(
        from_agent="ceo",
        to_agent="cfo",
        message="Valuta esposizione BTC",
        task_id="00000000-0000-0000-0000-000000000002",
        trace_id="trace-chat-1",
        context={"attachments": [{"kind": "trace", "id": "trace-chat-1"}]},
        message_id="chat-a2a-1",
        correlation_id="corr-chat-1",
    )

    assert event["event_type"] == "a2a_request"
    assert event["severity"] == "info"
    assert event["agent_id"] == "ceo"
    assert event["task_id"] == UUID("00000000-0000-0000-0000-000000000002")
    assert event["trace_id"] == "trace-chat-1"
    assert event["a2a_message_id"] == "chat-a2a-1"
    assert event["source"] == "chat_hub"
    assert event["payload"] == {
        "id": "chat-a2a-1",
        "from_agent": "ceo",
        "to_agent": "cfo",
        "type": "request",
        "mode": "async",
        "status": "queued",
        "correlation_id": "corr-chat-1",
        "root_correlation_id": "corr-chat-1",
        "hop_count": 0,
        "max_hops": 5,
        "message": "Valuta esposizione BTC",
        "context": {"attachments": [{"kind": "trace", "id": "trace-chat-1"}]},
    }


def test_build_chat_a2a_message_matches_agent_pubsub_envelope():
    event = build_chat_a2a_event(
        from_agent="ceo",
        to_agent="cfo",
        message="Valuta esposizione BTC",
        message_id="chat-a2a-1",
        correlation_id="corr-chat-1",
    )

    message = build_chat_a2a_message(event)

    assert message.from_agent == "ceo"
    assert message.to_agent == "cfo"
    assert message.type == "request"
    assert message.payload == "Valuta esposizione BTC"
    assert message.id == "chat-a2a-1"
    assert message.correlation_id == "corr-chat-1"
    assert message.mode == "async"
    assert message.root_correlation_id == "corr-chat-1"
    assert message.hop_count == 0
    assert message.max_hops == 5


def test_build_chat_decision_payload_preserves_reply_and_context():
    decision = build_chat_decision_payload(
        agent_id="ciso",
        reply="Aprire incidente P1 e isolare il nodo.",
        title="Incident response recommendation",
        task_id="00000000-0000-0000-0000-000000000002",
        trace_id="trace-chat-1",
        message_id="msg-agent-1",
        context={"attachments": [{"kind": "log", "id": "event-1"}]},
    )

    assert decision["agent_id"] == "ciso"
    assert decision["task_id"] == UUID("00000000-0000-0000-0000-000000000002")
    assert decision["trace_id"] == "trace-chat-1"
    assert decision["title"] == "Incident response recommendation"
    assert decision["summary"] == "Aprire incidente P1 e isolare il nodo."
    assert decision["decision_type"] == "chat_saved_reply"
    assert decision["status"] == "approved"
    assert decision["evidence"] == [
        {"kind": "chat_message", "id": "msg-agent-1"},
        {"kind": "context", "value": {"attachments": [{"kind": "log", "id": "event-1"}]}},
    ]
    assert decision["payload"] == {
        "source": "chat_hub",
        "message_id": "msg-agent-1",
        "reply": "Aprire incidente P1 e isolare il nodo.",
        "context": {"attachments": [{"kind": "log", "id": "event-1"}]},
    }
