"""Define cancellation and background run coordination. @sergent/docs/execution-model.md
@sergent-py-runtime/docs/KNOWLEDGE.md"""

from __future__ import annotations

import asyncio
import dataclasses
import typing

import sergent_py_core.result as core_result
import sergent_py_core.timing as core_timing

if typing.TYPE_CHECKING:
    import sergent_py_runtime.run_record.run as runtime_run
    import sergent_py_runtime.lifecycle.observe as runtime_observe

SceneT = typing.TypeVar("SceneT")


class CancelToken:
    """Record cancellation with one stable request time. @sergent/docs/execution-model.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    def __init__(self) -> None:
        self._cancelled = False
        self.requested_at: str | None = None

    def cancel(self) -> None:
        """Request cancellation with a stable first timestamp. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        if not self._cancelled:
            self.requested_at = core_timing.utc_now()
        self._cancelled = True

    def cancelled(self) -> bool:
        """Report whether cancellation has been requested. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        return self._cancelled


@dataclasses.dataclass
class RunHandle(typing.Generic[SceneT]):
    """Expose run progress, cancellation, and completion. @sergent/docs/execution-model.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    run_id: str
    _run: runtime_run.Run
    _task: asyncio.Task[core_result.SergentResult[SceneT]]
    _cancel: CancelToken

    def snapshot(self) -> runtime_observe.ProgressSnapshot:
        """Return the run's current sanitized progress. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        return self._run.snapshot()

    def done(self) -> bool:
        """Report completion after terminal observer delivery.
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        return self._task.done()

    def cancel(self) -> None:
        """Request cancellation and interrupt an awaited call. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        self._cancel.cancel()
        if not self._task.done():
            self._task.get_loop().call_soon_threadsafe(self._task.cancel)

    async def result(self) -> core_result.SergentResult[SceneT]:
        """Await the scheduled run's terminal result. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        return await self._task
