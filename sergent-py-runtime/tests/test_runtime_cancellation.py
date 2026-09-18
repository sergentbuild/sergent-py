from __future__ import annotations

import asyncio

import pytest

import demo_domain as domain
import runtime_test_support as support
import sergent_py_core.mindbuf as core_mindbuf
import sergent_py_core.result as core_result
import sergent_py_runtime.lifecycle.concurrency as concurrency
import sergent_py_runtime.lifecycle.observe as observe

_DemoResult = core_result.SergentResult[domain.DemoScene]


class _CancellingObserver:
    def __init__(self, stage: str) -> None:
        self.stage = stage
        self.handle: concurrency.RunHandle[domain.DemoScene] | None = None
        self._cancelled = False

    def progress(self, snapshot: observe.ProgressSnapshot) -> None:
        if snapshot.stage != self.stage or self._cancelled:
            return
        assert self.handle is not None
        self._cancelled = True
        self.handle.cancel()

    def finished(self, _result: core_result.SergentResult[domain.DemoScene]) -> None:
        return None


@pytest.mark.parametrize(
    ("stage", "checkpoint", "call_count"),
    [
        (observe.Stage.STARTED, "before_intent", 0),
        (observe.Stage.DRY_RUN, "before_commit", 2),
    ],
)
def test_observer_cancellation_checkpoint_leaves_scene_unchanged(
    stage: str,
    checkpoint: str,
    call_count: int,
) -> None:
    client = domain.StaticClient(["alpha"])
    observer = _CancellingObserver(stage)
    runtime = support.runtime(client, observers=(observer,))
    scene = domain.make_scene(block_count=1)
    block_id = scene.blocks[0].block_id

    async def scenario() -> _DemoResult:
        handle: concurrency.RunHandle[domain.DemoScene] = runtime.start(
            scene,
            core_mindbuf.MindBuf(),
            model_name="test/fake",
        )
        observer.handle = handle
        return await handle.result()

    result = asyncio.run(scenario())

    assert result.status == "cancelled"
    assert result.stage == stage
    assert result.run_record.cancellation is not None
    assert result.run_record.cancellation.checkpoint == checkpoint
    assert len(client.requests) == call_count
    assert "commit" not in [step.name for step in result.run_record.steps]
    assert support.block_generated(result.scene, block_id) == []
    assert scene.blocks[0].generated == []


def test_cancel_before_plan_call() -> None:
    client = domain.CancellingIntentClient()
    runtime = support.runtime(client)
    scene = domain.make_scene(block_count=1)
    block_id = scene.blocks[0].block_id

    async def scenario() -> _DemoResult:
        handle: concurrency.RunHandle[domain.DemoScene] = runtime.start(
            scene,
            core_mindbuf.MindBuf(),
            model_name="test/fake",
        )
        client.cancel = handle.cancel
        return await handle.result()

    result = asyncio.run(scenario())

    assert result.status == "cancelled"
    assert result.error is not None
    assert result.error.kind == "cancelled"
    assert len(client.requests) == 1
    assert support.block_generated(result.scene, block_id) == []
    assert scene.blocks[0].generated == []
    assert len(support.request_ids(result)) == 1
    assert result.run_record.cancellation is not None
    assert result.run_record.cancellation.requested_at is not None
    assert result.run_record.cancellation.checkpoint == "after_intent_validation"
    assert [step.name for step in result.run_record.steps] == ["process_input", "intent"]
    intent_step = support.step(result, "intent")
    assert intent_step.status == "cancelled"
    assert intent_step.model_call is not None
    assert [attempt.status for attempt in intent_step.model_call.attempts] == ["success"]


def test_cancel_during_model_call_interrupts_await() -> None:
    client = domain.ControlledClient(["alpha"])
    runtime = support.runtime(client)
    scene = domain.make_scene(block_count=1)
    block_id = scene.blocks[0].block_id

    async def scenario() -> tuple[concurrency.RunHandle[domain.DemoScene], _DemoResult]:
        handle: concurrency.RunHandle[domain.DemoScene] = runtime.start(
            scene,
            core_mindbuf.MindBuf(),
            model_name="test/fake",
        )
        await client.wait_called()
        assert not handle.done()
        handle.cancel()
        result = await handle.result()
        return handle, result

    handle, result = asyncio.run(scenario())

    assert handle.done()
    assert result.status == "cancelled"
    assert result.error is not None
    assert result.error.kind == "cancelled"
    assert len(client.requests) == 1
    assert support.request_ids(result) == []
    assert support.block_generated(result.scene, block_id) == []
    assert scene.blocks[0].generated == []
    assert result.run_record.cancellation is not None
    assert result.run_record.cancellation.checkpoint == "task_cancelled"
    intent_step = support.step(result, "intent")
    assert intent_step.status == "cancelled"
    assert intent_step.model_call is not None
    assert intent_step.model_call.attempts == []


def test_external_task_cancellation_propagates() -> None:
    client = domain.ControlledClient(["alpha"])
    runtime = support.runtime(client)
    scene = domain.make_scene(block_count=1)

    async def scenario() -> None:
        handle: concurrency.RunHandle[domain.DemoScene] = runtime.start(
            scene,
            core_mindbuf.MindBuf(),
            model_name="test/fake",
        )
        await client.wait_called()
        waiter = asyncio.create_task(handle.result())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert handle.done()
        with pytest.raises(asyncio.CancelledError):
            await handle.result()

    asyncio.run(scenario())


def test_cancel_after_plan_before_commit() -> None:
    client = domain.CancellingPlanClient()
    runtime = support.runtime(client)
    scene = domain.make_scene(block_count=1)
    block_id = scene.blocks[0].block_id

    async def scenario() -> _DemoResult:
        handle: concurrency.RunHandle[domain.DemoScene] = runtime.start(
            scene,
            core_mindbuf.MindBuf(),
            model_name="test/fake",
        )
        client.cancel = handle.cancel
        return await handle.result()

    result = asyncio.run(scenario())

    assert result.status == "cancelled"
    assert support.block_generated(result.scene, block_id) == []
    assert scene.blocks[0].generated == []
    assert len(client.requests) == 2
    assert len(support.request_ids(result)) == 2
