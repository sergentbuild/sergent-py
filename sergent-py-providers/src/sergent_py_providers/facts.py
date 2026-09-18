"""Build provider identity and completed-attempt evidence.
@sergent-py-providers/docs/KNOWLEDGE.md"""

from __future__ import annotations

import importlib.metadata
import time
import typing

import sergent_py_core.model_calls as core_model_calls
import sergent_py_core.errors as core_errors
import sergent_py_core.timing as core_timing

if typing.TYPE_CHECKING:
    import sergent_py_providers.client as pc


def _sdk_version(package: str) -> str | None:
    """Read the installed SDK version when its distribution is available."""
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _model_identity(selection: pc._ModelSelection) -> core_model_calls.ModelIdentity:
    """Build resolved endpoint identity with official SDK package facts.
    @sergent/docs/run-record-spec.md
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    adapter = selection.adapter
    return core_model_calls.ModelIdentity(
        provider=selection.provider,
        model=selection.model,
        sdk_package=adapter.sdk_package,
        sdk_version=_sdk_version(adapter.sdk_package),
    )


class _AttemptLog:
    """Accumulate closed evidence for completed outer provider attempts.
    @sergent-py-providers/docs/KNOWLEDGE.md"""

    def __init__(self) -> None:
        self.records: list[core_model_calls.ModelAttemptRecord] = []
        self._started_at: str
        self._t0: float

    def begin_attempt(self) -> None:
        """Start timing one outer provider attempt."""
        self._started_at = core_timing.utc_now()
        self._t0 = time.perf_counter()

    def record_failure(self, error: core_model_calls.ModelError) -> None:
        """Close the active attempt as a retry-aware failure."""
        self.records.append(
            core_model_calls.ModelAttemptRecord(
                timing=self._closed_timing(),
                status="failure",
                retryable=error.retryable,
                error=core_errors.RunError(kind=error.kind, message=error.message),
            )
        )

    def record_success(self) -> None:
        """Close the active attempt as successful."""
        self.records.append(
            core_model_calls.ModelAttemptRecord(
                timing=self._closed_timing(),
                status="success",
            )
        )

    def _closed_timing(self) -> core_timing.TimeSpan:
        """Build a closed timing span for the active attempt."""
        return core_timing.TimeSpan(
            started_at=self._started_at,
            finished_at=core_timing.utc_now(),
            duration_ms=int((time.perf_counter() - self._t0) * 1000),
        )
