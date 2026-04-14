"""Unit tests for FallbackModel — no real API calls."""

import pytest
from unittest.mock import MagicMock, call


def _make_model(model_id: str, *, fail: bool = False, fail_times: int = 0):
    """Create a mock Agno model."""
    m = MagicMock()
    m.id = model_id
    m.name = model_id

    call_count = {"n": 0}

    def invoke(messages, **kwargs):
        call_count["n"] += 1
        if fail or call_count["n"] <= fail_times:
            raise ConnectionError(f"{model_id} simulated failure")
        return MagicMock(content=f"response from {model_id}")

    m.invoke.side_effect = invoke
    return m


class TestFallbackModelBasic:

    def test_primary_success(self):
        from src.models.fallback_model import FallbackModel
        primary = _make_model("gpt-5.4")
        fallback = _make_model("llama-3.3")
        model = FallbackModel([primary, fallback])

        result = model.invoke(["msg"])

        primary.invoke.assert_called_once()
        fallback.invoke.assert_not_called()
        assert "gpt-5.4" in result.content

    def test_primary_fails_fallback_succeeds(self):
        from src.models.fallback_model import FallbackModel
        primary = _make_model("gpt-5.4", fail=True)
        fallback = _make_model("llama-3.3")
        model = FallbackModel([primary, fallback], max_retries_per_model=0)

        result = model.invoke(["msg"])

        assert "llama-3.3" in result.content

    def test_all_models_fail_raises(self):
        from src.models.fallback_model import FallbackModel
        models = [_make_model(f"model-{i}", fail=True) for i in range(3)]
        fm = FallbackModel(models, max_retries_per_model=0)

        with pytest.raises(Exception):
            fm.invoke(["msg"])

    def test_on_fallback_callback_invoked(self):
        from src.models.fallback_model import FallbackModel
        primary = _make_model("gpt-5.4", fail=True)
        fallback = _make_model("llama-3.3")
        callback = MagicMock()

        model = FallbackModel([primary, fallback], max_retries_per_model=0, on_fallback=callback)
        model.invoke(["msg"])

        callback.assert_called_once()
        from_m, to_m, err = callback.call_args[0]
        assert from_m.id == "gpt-5.4"
        assert to_m.id == "llama-3.3"
        assert isinstance(err, ConnectionError)

    def test_repr(self):
        from src.models.fallback_model import FallbackModel
        models = [_make_model("gpt-5.4"), _make_model("llama-3.3")]
        fm = FallbackModel(models)
        assert repr(fm) == "FallbackModel(gpt-5.4 → llama-3.3)"

    def test_id_is_primary_id(self):
        from src.models.fallback_model import FallbackModel
        models = [_make_model("gpt-5.4"), _make_model("llama-3.3")]
        fm = FallbackModel(models)
        assert fm.id == "gpt-5.4"

    def test_retry_exhaustion_before_cascade(self):
        from src.models.fallback_model import FallbackModel
        primary = _make_model("gpt-5.4", fail=True)
        fallback = _make_model("llama-3.3")
        model = FallbackModel([primary, fallback], max_retries_per_model=2, retry_delay=0)

        model.invoke(["msg"])

        # primary called 3 times (1 + 2 retries), fallback called once
        assert primary.invoke.call_count == 3
        assert fallback.invoke.call_count == 1

    def test_requires_at_least_one_model(self):
        from src.models.fallback_model import FallbackModel
        with pytest.raises(ValueError, match="at least one model"):
            FallbackModel([])

    def test_streaming_primary_success(self):
        from src.models.fallback_model import FallbackModel
        primary = _make_model("gpt-5.4")
        primary.invoke_stream.return_value = iter(["chunk1", "chunk2"])
        fallback = _make_model("llama-3.3")
        model = FallbackModel([primary, fallback])

        stream = model.invoke_stream(["msg"])
        chunks = list(stream)

        primary.invoke_stream.assert_called_once()
        fallback.invoke_stream.assert_not_called()
        assert chunks == ["chunk1", "chunk2"]

    def test_streaming_fallback_on_failure(self):
        from src.models.fallback_model import FallbackModel
        primary = _make_model("gpt-5.4")
        primary.invoke_stream.side_effect = ConnectionError("stream fail")
        fallback = _make_model("llama-3.3")
        fallback.invoke_stream.return_value = iter(["fallback-chunk"])
        model = FallbackModel([primary, fallback], max_retries_per_model=0)

        stream = model.invoke_stream(["msg"])
        chunks = list(stream)

        assert chunks == ["fallback-chunk"]
