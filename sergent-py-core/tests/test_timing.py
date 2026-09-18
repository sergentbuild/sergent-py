from __future__ import annotations

import datetime

import pytest

import sergent_py_core.timing as timing


def test_utc_now_is_iso8601_with_trailing_z() -> None:
    stamp = timing.utc_now()
    assert stamp.endswith("Z")
    parsed = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


def test_time_span_opens_then_closes_with_paired_finish_facts() -> None:
    span = timing.TimeSpan.begin()
    assert not span.is_closed()
    assert span.finished_at is None
    assert span.duration_ms is None

    closed = span.closed_now(25)
    assert closed.is_closed()
    assert closed.started_at == span.started_at
    assert closed.finished_at is not None
    assert closed.duration_ms == 25

    with pytest.raises(ValueError, match="set together"):
        timing.TimeSpan(started_at=span.started_at, finished_at=timing.utc_now())
    with pytest.raises(ValueError, match="set together"):
        timing.TimeSpan(started_at=span.started_at, duration_ms=25)
