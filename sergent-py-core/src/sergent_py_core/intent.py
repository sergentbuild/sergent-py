"""Read Intent flow control and stop terminal facts. @sergent/docs/framework.md"""

from __future__ import annotations

import typing


def intent_flow(intent: object) -> typing.Literal["continue", "stop"]:
    """Read bounded flow control, defaulting an absent fact to continue. @sergent/docs/framework.md"""
    flow = getattr(intent, "flow", "continue")
    if flow not in {"continue", "stop"}:
        msg = f"unsupported intent flow: {flow!r}"
        raise ValueError(msg)
    return typing.cast(typing.Literal["continue", "stop"], flow)


def intent_terminal_message(intent: object) -> str | None:
    """Read an optional terminal message from a stop Intent. @sergent/docs/framework.md"""
    terminal_message = getattr(intent, "terminal_message", None)
    if terminal_message is None:
        return None
    if not callable(terminal_message):
        msg = "intent terminal_message must be callable"
        raise ValueError(msg)
    message = terminal_message()
    if message is None:
        return None
    if not isinstance(message, str):
        msg = "intent terminal_message must return a str"
        raise ValueError(msg)
    return message


def intent_terminal_metadata(intent: object) -> dict[str, object]:
    """Read terminal metadata from a stop Intent. @sergent/docs/framework.md"""
    terminal_metadata = getattr(intent, "terminal_metadata", None)
    if terminal_metadata is None:
        return {}
    if not callable(terminal_metadata):
        msg = "intent terminal_metadata must be callable"
        raise ValueError(msg)
    metadata = terminal_metadata()
    if not isinstance(metadata, dict):
        msg = "intent terminal_metadata must return a dict"
        raise ValueError(msg)
    return dict(metadata)
