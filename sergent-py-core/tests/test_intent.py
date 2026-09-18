from __future__ import annotations

import pytest

import sergent_py_core.intent as intent


def test_intent_flow_helpers_default_to_continue_and_read_stop_metadata() -> None:
    class StopIntent:
        flow = "stop"

        def terminal_message(self) -> str:
            return "already done"

        def terminal_metadata(self) -> dict[str, object]:
            return {"score": 3}

    class QuietStopIntent:
        flow = "stop"

        def terminal_message(self) -> str | None:
            return None

    assert intent.intent_flow(object()) == "continue"
    assert intent.intent_terminal_message(object()) is None
    assert intent.intent_terminal_metadata(object()) == {}
    stop_intent = StopIntent()
    assert intent.intent_flow(stop_intent) == "stop"
    assert intent.intent_terminal_message(stop_intent) == "already done"
    assert intent.intent_terminal_metadata(stop_intent) == {"score": 3}
    assert intent.intent_terminal_message(QuietStopIntent()) is None


def test_intent_flow_helpers_reject_invalid_shapes() -> None:
    class FanOutFlow:
        flow = "fan_out"

    class BadFlow:
        flow = "halt"

    class BadMessage:
        terminal_message = "done"

    class BadMessageReturn:
        def terminal_message(self) -> object:
            return 42

    class BadMetadata:
        def terminal_metadata(self) -> list[str]:
            return ["bad"]

    with pytest.raises(ValueError):
        intent.intent_flow(FanOutFlow())
    with pytest.raises(ValueError):
        intent.intent_flow(BadFlow())
    with pytest.raises(ValueError, match="terminal_message must be callable"):
        intent.intent_terminal_message(BadMessage())
    with pytest.raises(ValueError, match="terminal_message must return a str"):
        intent.intent_terminal_message(BadMessageReturn())
    with pytest.raises(ValueError, match="terminal_metadata must return a dict"):
        intent.intent_terminal_metadata(BadMetadata())
