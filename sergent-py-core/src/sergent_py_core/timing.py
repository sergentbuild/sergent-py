"""Define wall-clock facts carried by run evidence. @sergent/docs/execution-model.md
@sergent-py-core/docs/core-class-design-pattern.md"""

from __future__ import annotations

import datetime

import pydantic

import sergent_py_core.strict_model as strict_model


def utc_now() -> str:
    """Return the current UTC instant with an ISO-8601 trailing ``Z``. @sergent/docs/execution-model.md"""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class TimeSpan(strict_model.StrictModel):
    """Carry a wall-clock lifecycle with caller-measured duration. @sergent/docs/execution-model.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    started_at: str
    finished_at: str | None = None
    duration_ms: int | None = pydantic.Field(default=None, ge=0)

    @pydantic.model_validator(mode="after")
    def _finish_facts_set_together(self) -> TimeSpan:
        """Require closing timestamp and duration to travel together."""
        if (self.finished_at is None) != (self.duration_ms is None):
            msg = "finished_at and duration_ms must be set together"
            raise ValueError(msg)
        return self

    @classmethod
    def begin(cls) -> TimeSpan:
        """Open a wall-clock span. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        return cls(started_at=utc_now())

    def closed_now(self, duration_ms: int) -> TimeSpan:
        """Return a closed replacement with measured duration. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        return TimeSpan(
            started_at=self.started_at,
            finished_at=utc_now(),
            duration_ms=duration_ms,
        )

    def is_closed(self) -> bool:
        """Return whether both closing facts are present. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        return self.finished_at is not None
