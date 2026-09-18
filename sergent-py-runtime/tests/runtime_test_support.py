"""Explicit shared mechanics for runtime tests."""

from __future__ import annotations

import asyncio
import typing

import demo_domain as domain
import sergent_py_core.model_calls as model_calls
import sergent_py_core.mindbuf as core_mindbuf
import sergent_py_core.recipe as core_recipe
import sergent_py_core.result as core_result
import sergent_py_core.run_record as core_run_record
import sergent_py_core.scene_actions as core_scene_actions
import sergent_py_runtime.execution.engine as engine
import sergent_py_runtime.execution.scene_state as scene_state
import sergent_py_runtime.lifecycle.observe as observe


class _ParkedClient(typing.Protocol):
    async def wait_called(self) -> None: ...

    def release(self) -> None: ...


def runtime(
    client: model_calls.ModelClient | None = None,
    *,
    actions: core_scene_actions.SceneActions[domain.DemoScene] | None = None,
    observers: tuple[observe.RunObserver, ...] = (),
    recipe: core_recipe.SergentRecipe[domain.DemoScene, typing.Any, typing.Any] | None = None,
) -> engine.SergentRuntime[domain.DemoScene]:
    return engine.SergentRuntime(
        client if client is not None else domain.StaticClient(["alpha"]),
        actions if actions is not None else domain.DemoActions(),
        recipe if recipe is not None else domain.DemoRecipe(),
        observers=observers,
    )


def block_generated(scene: domain.DemoScene, block_id: str) -> list[str]:
    for block in scene.blocks:
        if block.block_id == block_id:
            return block.generated
    raise AssertionError("block not found")


def step(
    result: core_result.SergentResult[domain.DemoScene],
    name: str,
) -> core_run_record.RunStepRecord:
    for item in result.run_record.steps:
        if item.name == name:
            return item
    raise AssertionError(f"step not found: {name}")


def output_value(
    result: core_result.SergentResult[domain.DemoScene],
    name: str,
) -> dict[str, typing.Any]:
    output = step(result, name).output
    assert output is not None
    assert isinstance(output.value, dict)
    return output.value


def request_ids(result: core_result.SergentResult[domain.DemoScene]) -> list[str]:
    ids: list[str] = []
    for item in result.run_record.steps:
        call = item.model_call
        if call is not None and call.usage is not None and call.usage.request_id is not None:
            ids.append(call.usage.request_id)
    return ids


async def interleave_two_writers(
    state: scene_state.SceneState[domain.DemoScene],
    first_runtime: engine.SergentRuntime[domain.DemoScene],
    first_client: _ParkedClient,
    second_runtime: engine.SergentRuntime[domain.DemoScene],
    second_client: _ParkedClient,
) -> tuple[
    core_result.SergentResult[domain.DemoScene],
    core_result.SergentResult[domain.DemoScene],
]:
    first_task = asyncio.create_task(
        first_runtime.run(state, core_mindbuf.MindBuf(), model_name="test/first")
    )
    second_task = asyncio.create_task(
        second_runtime.run(state, core_mindbuf.MindBuf(), model_name="test/second")
    )
    await first_client.wait_called()
    await second_client.wait_called()
    first_client.release()
    first_result = await first_task
    second_client.release()
    second_result = await second_task
    return first_result, second_result
