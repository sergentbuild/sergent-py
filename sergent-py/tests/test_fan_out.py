from __future__ import annotations

import asyncio

import pytest
import sergent_py

from sergent_py import fan_out


def test_fan_out_preserves_item_order() -> None:
    async def scenario() -> list[str | BaseException]:
        async def run_one(item: int) -> str:
            await asyncio.sleep((4 - item) * 0.01)
            return f"done-{item}"

        return await fan_out([1, 2, 3], run_one, limit=3)

    assert asyncio.run(scenario()) == ["done-1", "done-2", "done-3"]


def test_fan_out_respects_concurrency_limit() -> None:
    async def scenario() -> tuple[list[int | BaseException], int, int]:
        active = 0
        max_active = 0
        started = 0
        first_batch_started = asyncio.Event()
        release = asyncio.Event()

        async def run_one(item: int) -> int:
            nonlocal active, max_active, started
            active += 1
            started += 1
            max_active = max(max_active, active)
            if started == 2:
                first_batch_started.set()
            try:
                await release.wait()
                return item
            finally:
                active -= 1

        task = asyncio.create_task(fan_out([1, 2, 3, 4, 5], run_one, limit=2))
        await asyncio.wait_for(first_batch_started.wait(), timeout=1)
        await asyncio.sleep(0)
        before_release_started = started
        release.set()
        results = await task
        return results, max_active, before_release_started

    results, max_active, before_release_started = asyncio.run(scenario())
    assert results == [1, 2, 3, 4, 5]
    assert max_active == 2
    assert before_release_started == 2


def test_fan_out_returns_item_exceptions_without_cancelling_siblings() -> None:
    class ItemFailure(Exception):
        pass

    async def scenario() -> list[int | BaseException]:
        async def run_one(item: int) -> int:
            await asyncio.sleep(0)
            if item == 2:
                raise ItemFailure("bad item")
            return item * 10

        return await fan_out([1, 2, 3], run_one, limit=2)

    results = asyncio.run(scenario())
    assert results[0] == 10
    assert isinstance(results[1], ItemFailure)
    assert str(results[1]) == "bad item"
    assert results[2] == 30


def test_fan_out_parent_cancellation_propagates() -> None:
    async def scenario() -> list[int]:
        started = 0
        first_batch_started = asyncio.Event()
        never_release = asyncio.Event()
        cancelled_items: list[int] = []

        async def run_one(item: int) -> int:
            nonlocal started
            started += 1
            if started == 2:
                first_batch_started.set()
            try:
                await never_release.wait()
                return item
            finally:
                cancelled_items.append(item)

        task = asyncio.create_task(fan_out([1, 2, 3], run_one, limit=2))
        await asyncio.wait_for(first_batch_started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return cancelled_items

    assert sorted(asyncio.run(scenario())) == [1, 2]


def test_fan_out_is_exported() -> None:
    assert sergent_py.fan_out is fan_out
