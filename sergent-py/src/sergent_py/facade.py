"""Provide battery wiring and bounded app concurrency without engine, transport, or domain logic.
@sergent-py/docs/KNOWLEDGE.md"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import TYPE_CHECKING, Any, TypeVar

from sergent_py_providers.client import LlmClient
from sergent_py_runtime.execution.engine import SergentRuntime

if TYPE_CHECKING:
    from sergent_py_core.model_calls import ModelClient
    from sergent_py_core.recipe import SergentRecipe
    from sergent_py_core.scene_actions import SceneActions
    from sergent_py_runtime.lifecycle.observe import RunObserver

ItemT = TypeVar("ItemT")
OutcomeT = TypeVar("OutcomeT")
SceneT = TypeVar("SceneT")


async def fan_out(
    items: Iterable[ItemT],
    run_one: Callable[[ItemT], Awaitable[OutcomeT]],
    *,
    limit: int = 4,
) -> list[OutcomeT | BaseException]:
    """Settle bounded app-owned async work in input order, returning item failures in place.
    @sergent-py/docs/KNOWLEDGE.md"""
    semaphore = asyncio.Semaphore(limit)

    async def guarded(item: ItemT) -> OutcomeT:
        async with semaphore:
            return await run_one(item)

    return await asyncio.gather(
        *(guarded(item) for item in items),
        return_exceptions=True,
    )


def make_llm_client() -> ModelClient:
    """Build the real model client without binding a selected model.
    @sergent-py/docs/KNOWLEDGE.md"""
    return LlmClient()


def create_sergent(
    scene: SceneActions[SceneT],
    recipe: SergentRecipe[SceneT, Any, Any],
    *,
    client: ModelClient | None = None,
    observers: Iterable[RunObserver] = (),
) -> SergentRuntime[SceneT]:
    """Wire app domain interfaces into a runtime without fixing its per-run model name.
    @sergent-py/docs/KNOWLEDGE.md"""
    if client is None:
        client = make_llm_client()
    return SergentRuntime(client, scene, recipe, observers=observers)
