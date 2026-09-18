"""Define sanitized progress and non-interfering observers. @sergent/docs/execution-model.md
@sergent-py-runtime/docs/KNOWLEDGE.md"""

from __future__ import annotations

import enum
import typing

import sergent_py_core.errors as core_errors
import sergent_py_core.result as core_result
import sergent_py_core.strict_model as core_strict_model

ProgressStatus = typing.Literal["queued", "running", "success", "failure", "cancelled"]

_OBSERVER_ERROR_MESSAGE_LIMIT = 2048


class Stage(enum.StrEnum):
    """Enumerate observable stages for one bounded run. @sergent/docs/execution-model.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    QUEUED = "queued"
    STARTED = "started"
    INTENT_CALL = "intent_call"
    INTENT = "intent"
    PLAN_CALL = "plan_call"
    EXECUTION_PLAN = "execution_plan"
    PATCH = "patch"
    DRY_RUN = "dry_run"
    COMMIT = "commit"


class ProgressSnapshot(core_strict_model.StrictModel):
    """Carry a sanitized point-in-time progress view. @sergent/docs/execution-model.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    run_id: str
    scene_id: str | None = None
    stage: str
    status: ProgressStatus
    revision: int


class RunObserver(typing.Protocol):
    """Receive ordered callbacks without outcome authority. @sergent/docs/execution-model.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    def progress(self, snapshot: ProgressSnapshot, /) -> None:
        """Receive one sanitized progress update. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        ...

    def finished(self, result: core_result.SergentResult[typing.Any], /) -> None:
        """Receive the result after its Run Record closes. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        ...


def _qualified_type(value: object) -> str:
    """Return a qualified type name without propagating introspection failures."""
    try:
        value_type = type(value)
        module = value_type.__module__
        qualname = value_type.__qualname__
        if isinstance(module, str) and isinstance(qualname, str):
            return f"{module}.{qualname}"
    except BaseException:
        pass
    return "builtins.object"


def _observer_error(
    callback: str,
    observer: object,
    exception: BaseException,
    stage: str,
) -> core_errors.RunError:
    """Contain an ordinary callback failure as a RunError. @sergent/docs/execution-model.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    observer_type = _qualified_type(observer)
    exception_type = _qualified_type(exception)
    try:
        detail = str(exception)
    except BaseException:
        detail = exception_type
    message = f"{callback} observer callback failed: {detail}"
    return core_errors.RunError(
        kind="observer_error",
        message=message[:_OBSERVER_ERROR_MESSAGE_LIMIT],
        metadata={
            "callback": callback,
            "observer_type": observer_type,
            "exception_type": exception_type,
            "stage": str(stage),
        },
    )
