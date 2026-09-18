from __future__ import annotations

import asyncio

import demo_domain as domain
import runtime_test_support as support
import sergent_py_core.mindbuf as core_mindbuf
import sergent_py_core.result as core_result
import sergent_py_runtime.lifecycle.concurrency as concurrency
import sergent_py_runtime.lifecycle.observe as observe

_DemoResult = core_result.SergentResult[domain.DemoScene]


def test_handle_is_not_done_while_model_call_is_parked_then_done_after_success() -> None:
    client = domain.ControlledClient(["alpha"])
    runtime = support.runtime(client)
    scene = domain.make_scene(block_count=1)

    async def scenario() -> tuple[concurrency.RunHandle[domain.DemoScene], _DemoResult]:
        handle: concurrency.RunHandle[domain.DemoScene] = runtime.start(
            scene,
            core_mindbuf.MindBuf(),
            model_name="test/fake",
        )
        assert not handle.done()
        snapshot = handle.snapshot()
        assert isinstance(snapshot, observe.ProgressSnapshot)
        assert handle.run_id
        assert snapshot.run_id == handle.run_id
        await client.wait_called()
        assert not handle.done()
        client.release()
        result = await handle.result()
        return handle, result

    handle, result = asyncio.run(scenario())
    assert handle.done()
    assert result.status == "success"
    assert result.run_record.run_id == handle.run_id
