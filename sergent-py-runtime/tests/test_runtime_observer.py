from __future__ import annotations

import asyncio
import typing

import pytest

import demo_domain as domain
import runtime_test_support as support
import sergent_py_core.mindbuf as core_mindbuf
import sergent_py_core.result as core_result
import sergent_py_runtime.execution.engine as engine
import sergent_py_runtime.execution.scene_state as scene_state
import sergent_py_runtime.lifecycle.concurrency as concurrency
import sergent_py_runtime.lifecycle.observe as observe

_DemoResult = core_result.SergentResult[domain.DemoScene]


class _CallbackFailureObserver:
    def __init__(
        self,
        callback: str,
        error: BaseException,
        *,
        stage: str | None = None,
        status: str | None = None,
    ) -> None:
        self.callback = callback
        self.error = error
        self.stage = stage
        self.status = status
        self._raised = False

    def progress(self, snapshot: observe.ProgressSnapshot) -> None:
        if self.callback != "progress" or self._raised:
            return
        if self.stage is not None and snapshot.stage != self.stage:
            return
        if self.status is not None and snapshot.status != self.status:
            return
        self._raised = True
        raise self.error

    def finished(self, result: core_result.SergentResult[typing.Any]) -> None:
        if self.callback == "finished" and not self._raised:
            self._raised = True
            raise self.error


class _CompletionObserver:
    def __init__(self) -> None:
        self.handle: concurrency.RunHandle[domain.DemoScene] | None = None
        self.done_during_finished: list[bool] = []

    def progress(self, snapshot: observe.ProgressSnapshot) -> None:
        return None

    def finished(self, result: core_result.SergentResult[typing.Any]) -> None:
        assert self.handle is not None
        self.done_during_finished.append(self.handle.done())


class _BrokenMessageError(Exception):
    def __str__(self) -> str:
        raise RuntimeError("broken exception string")


def _live_state(
    runtime: engine.SergentRuntime[domain.DemoScene],
) -> scene_state.SceneState[domain.DemoScene]:
    return runtime.live_state(domain.make_scene(block_count=1))


def test_queued_and_intermediate_failures_do_not_change_success_or_block_delivery() -> None:
    queued = _CallbackFailureObserver(
        "progress",
        OSError("queued observer failed"),
        stage=observe.Stage.QUEUED,
    )
    intermediate = _CallbackFailureObserver(
        "progress",
        RuntimeError("intermediate observer failed"),
        stage=observe.Stage.PLAN_CALL,
    )
    recorder = domain.CapturingObserver()
    runtime = support.runtime(observers=(queued, intermediate, recorder))
    scene = domain.make_scene(block_count=1)

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "success"
    assert support.block_generated(result.scene, result.scene.blocks[0].block_id) == ["note:alpha"]
    assert len(result.observer_errors) == 2
    assert [error.kind for error in result.observer_errors] == [
        "observer_error",
        "observer_error",
    ]
    assert [error.metadata["stage"] for error in result.observer_errors] == [
        observe.Stage.QUEUED,
        observe.Stage.PLAN_CALL,
    ]
    for error in result.observer_errors:
        assert set(error.metadata) == {
            "callback",
            "observer_type",
            "exception_type",
            "stage",
        }
        assert error.metadata["callback"] == "progress"
        observer_type = error.metadata["observer_type"]
        assert isinstance(observer_type, str)
        assert observer_type.endswith("._CallbackFailureObserver")
        assert type(error.metadata["stage"]) is str
    assert result.observer_errors[0].metadata["exception_type"] == "builtins.OSError"
    assert result.observer_errors[1].metadata["exception_type"] == "builtins.RuntimeError"
    assert recorder.snapshots[0].scene_id is None
    assert all(snapshot.scene_id == scene.scene_id for snapshot in recorder.snapshots[1:])


def test_terminal_progress_failure_returns_one_live_commit_and_is_visible_to_finished() -> None:
    failing = _CallbackFailureObserver(
        "progress",
        OSError("terminal progress failed"),
        stage=observe.Stage.COMMIT,
        status="success",
    )
    recorder = domain.CapturingObserver()
    runtime = support.runtime(observers=(failing, recorder))
    state = _live_state(runtime)

    result = asyncio.run(runtime.run(state, core_mindbuf.MindBuf(), model_name="test/fake"))

    live_scene, identity = state.snapshot()
    assert result.status == "success"
    assert identity.revision == 1
    assert support.block_generated(live_scene, live_scene.blocks[0].block_id) == ["note:alpha"]
    assert len(result.observer_errors) == 1
    assert result.observer_errors[0].metadata["stage"] == observe.Stage.COMMIT
    assert recorder.finished_results == [result]
    assert recorder.finished_error_counts == [1]


def test_finished_failure_through_handle_returns_same_result_after_one_live_commit() -> None:
    failing = _CallbackFailureObserver("finished", OSError("finished failed"))
    recorder = domain.CapturingObserver()
    runtime = support.runtime(observers=(failing, recorder))
    state = _live_state(runtime)

    async def scenario() -> _DemoResult:
        handle: concurrency.RunHandle[domain.DemoScene] = runtime.start(
            state,
            core_mindbuf.MindBuf(),
            model_name="test/fake",
        )
        return await handle.result()

    result = asyncio.run(scenario())

    live_scene, identity = state.snapshot()
    assert result.status == "success"
    assert identity.revision == 1
    assert support.block_generated(live_scene, live_scene.blocks[0].block_id) == ["note:alpha"]
    assert len(result.observer_errors) == 1
    error = result.observer_errors[0]
    assert error.metadata["callback"] == "finished"
    assert error.metadata["stage"] == observe.Stage.COMMIT
    assert recorder.finished_results[0] is result
    assert recorder.finished_error_counts == [1]


def test_handle_is_not_done_until_terminal_observer_delivery_returns() -> None:
    observer = _CompletionObserver()
    runtime = support.runtime(observers=(observer,))
    state = _live_state(runtime)

    async def scenario() -> tuple[concurrency.RunHandle[domain.DemoScene], _DemoResult]:
        handle: concurrency.RunHandle[domain.DemoScene] = runtime.start(
            state,
            core_mindbuf.MindBuf(),
            model_name="test/fake",
        )
        observer.handle = handle
        result = await handle.result()
        return handle, result

    handle, result = asyncio.run(scenario())

    assert result.status == "success"
    assert observer.done_during_finished == [False]
    assert handle.done()


def test_callback_cancelled_error_and_hostile_messages_are_bounded() -> None:
    cancelled = _CallbackFailureObserver(
        "progress",
        asyncio.CancelledError("callback cancellation"),
        stage=observe.Stage.QUEUED,
    )
    broken = _CallbackFailureObserver(
        "progress",
        _BrokenMessageError(),
        stage=observe.Stage.QUEUED,
    )
    oversized = _CallbackFailureObserver(
        "progress",
        RuntimeError("x" * 4096),
        stage=observe.Stage.QUEUED,
    )
    runtime = support.runtime(observers=(cancelled, broken, oversized))

    result = asyncio.run(
        runtime.run(domain.make_scene(), core_mindbuf.MindBuf(), model_name="test/fake")
    )

    assert result.status == "success"
    assert len(result.observer_errors) == 3
    assert all(len(error.message) <= 2048 for error in result.observer_errors)
    assert result.observer_errors[0].metadata["exception_type"] == (
        "asyncio.exceptions.CancelledError"
    )
    broken_error = result.observer_errors[1]
    exception_type = broken_error.metadata["exception_type"]
    assert isinstance(exception_type, str)
    assert exception_type.endswith("._BrokenMessageError")
    assert exception_type in broken_error.message
    assert len(result.observer_errors[2].message) == 2048


def test_observer_failure_preserves_precommit_cancellation_and_live_state() -> None:
    client = domain.ControlledClient(["alpha"])
    failing = _CallbackFailureObserver(
        "progress",
        OSError("queued observer failed"),
        stage=observe.Stage.QUEUED,
    )
    runtime = support.runtime(client, observers=(failing,))
    state = _live_state(runtime)

    async def scenario() -> _DemoResult:
        handle: concurrency.RunHandle[domain.DemoScene] = runtime.start(
            state,
            core_mindbuf.MindBuf(),
            model_name="test/fake",
        )
        await client.wait_called()
        handle.cancel()
        return await handle.result()

    result = asyncio.run(scenario())

    live_scene, identity = state.snapshot()
    assert result.status == "cancelled"
    assert result.error is not None
    assert result.error.kind == "cancelled"
    assert identity.revision == 0
    assert support.block_generated(live_scene, live_scene.blocks[0].block_id) == []
    assert len(result.observer_errors) == 1


@pytest.mark.parametrize("process_error", [KeyboardInterrupt(), SystemExit()])
def test_postcommit_process_control_propagates_with_truthful_live_revision(
    process_error: BaseException,
) -> None:
    failing = _CallbackFailureObserver("finished", process_error)
    runtime = support.runtime(observers=(failing,))
    state = _live_state(runtime)

    with pytest.raises(type(process_error)):
        asyncio.run(runtime.run(state, core_mindbuf.MindBuf(), model_name="test/fake"))

    live_scene, identity = state.snapshot()
    assert identity.revision == 1
    assert support.block_generated(live_scene, live_scene.blocks[0].block_id) == ["note:alpha"]
