from __future__ import annotations

import asyncio
import types

import demo_domain as domain
import flow_domain as flow
import runtime_test_support as support
import sergent_py_core.mindbuf as core_mindbuf
import sergent_py_core.result as core_result
import sergent_py_runtime.execution.scene_state as scene_state
import sergent_py_runtime.lifecycle.concurrency as concurrency
import sergent_py_runtime.lifecycle.observe as observe
import sergent_py_runtime.proposals.intents as runtime_intents

_DemoResult = core_result.SergentResult[domain.DemoScene]


def test_runtime_continue_intent_has_only_fixed_flow() -> None:
    intent = runtime_intents.Intent_Continue()

    assert intent.flow == "continue"
    assert intent.model_dump() == {"flow": "continue"}


def test_stop_intent_skips_plan_call_and_returns_success_at_intent() -> None:
    scene = domain.make_scene(block_count=1)
    block_id = scene.blocks[0].block_id
    client = domain.StaticClient(["alpha"])
    observer = domain.CapturingObserver()
    recipe = flow.StopDemoRecipe()
    runtime = support.runtime(client, observers=(observer,), recipe=recipe)

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "success"
    assert result.stage == observe.Stage.INTENT
    transition = result.run_record.scene
    assert transition is not None
    assert transition.revision_after == transition.revision_before
    assert result.identity.revision == transition.revision_before
    assert result.terminal_message == "scene already satisfies the target"
    assert result.terminal_metadata == {"decision": "done"}
    assert len(client.requests) == 1
    assert support.request_ids(result) == ["req-intent"]
    assert support.block_generated(result.scene, block_id) == []

    stages = [snapshot.stage for snapshot in observer.snapshots]
    assert observe.Stage.PLAN_CALL.value not in stages
    assert observe.Stage.COMMIT.value not in stages
    assert observe.Stage.INTENT.value in stages


def test_cancel_after_stop_intent_validation_wins_before_terminal_success() -> None:
    client = domain.CancellingIntentClient()
    runtime = support.runtime(client, recipe=flow.StopDemoRecipe())
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
    assert result.stage == observe.Stage.INTENT
    assert support.request_ids(result) == ["req-intent"]
    assert len(client.requests) == 1
    assert support.block_generated(result.scene, block_id) == []


def test_unsupported_intent_flow_is_contained_before_plan_call() -> None:
    scene = domain.make_scene(block_count=1)
    client = domain.StaticClient(["alpha"])
    runtime = support.runtime(client, recipe=flow.UnsupportedFlowDemoRecipe())

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "failure"
    assert result.error is not None
    assert result.error.kind == "validation_error"
    assert result.stage == observe.Stage.INTENT
    assert len(client.requests) == 1


def test_live_scene_rebase_commits_stale_patch_when_app_supports_merge() -> None:
    client_a = domain.ControlledClient(["alpha"])
    client_b = domain.ControlledClient(["beta"])
    actions_a = flow.RebaseDemoActions()
    actions_b = flow.RebaseDemoActions()
    runtime_a = support.runtime(client_a, actions=actions_a)
    runtime_b = support.runtime(client_b, actions=actions_b)
    state: scene_state.SceneState[domain.DemoScene] = runtime_a.live_state(
        domain.make_scene(block_count=1)
    )
    block_id = state.snapshot()[0].blocks[0].block_id

    result_a, result_b = asyncio.run(
        support.interleave_two_writers(state, runtime_a, client_a, runtime_b, client_b)
    )

    assert result_a.status == "success"
    assert result_b.status == "success"
    assert result_b.terminal_metadata == {"rebased": True}
    terminal = result_b.run_record.outcome.terminal
    assert terminal is not None
    assert terminal.message.status == "captured"
    assert terminal.message.value is None
    assert terminal.metadata.status == "captured"
    assert terminal.metadata.value == result_b.terminal_metadata

    stale_target = actions_b.selected_targets[0]
    assert len(actions_b.rebase_targets) == 1
    assert actions_b.rebase_targets[0] is stale_target
    assert len(actions_b.applied_targets) == 2
    assert all(target is stale_target for target in actions_b.applied_targets)

    live_scene, identity = state.snapshot()
    assert identity.revision == 2
    assert support.block_generated(live_scene, block_id) == ["note:alpha", "note:beta"]


def test_live_scene_rebase_conflict_returns_structured_failure() -> None:
    scene_metadata: dict[str, object] = {
        "base_revision": 99,
        "current_live_revision": 100,
        "patch": "application patch detail",
        "scene_metadata": "application scene detail",
        "validation_error": "application validation detail",
    }
    client_a = domain.ControlledClient(["alpha"])
    client_b = domain.ControlledClient(["beta"])
    runtime_a = support.runtime(client_a, actions=flow.RebaseDemoActions())
    runtime_b = support.runtime(
        client_b, actions=flow.RebaseDemoActions(conflict=True, metadata=scene_metadata)
    )
    state: scene_state.SceneState[domain.DemoScene] = runtime_a.live_state(
        domain.make_scene(block_count=1)
    )
    block_id = state.snapshot()[0].blocks[0].block_id

    result_a, result_b = asyncio.run(
        support.interleave_two_writers(state, runtime_a, client_a, runtime_b, client_b)
    )

    assert result_a.status == "success"
    assert result_b.status == "failure"
    assert result_b.error is not None
    assert result_b.error.kind == "merge_conflict"
    assert result_b.error.message == "demo conflict"
    assert set(result_b.error.metadata) == {
        "base_revision",
        "current_live_revision",
        "patch",
        "scene_metadata",
    }
    assert result_b.error.metadata["scene_metadata"] == scene_metadata
    assert result_b.error.metadata["base_revision"] == 0
    assert result_b.error.metadata["current_live_revision"] == 1
    patch_summary = result_b.error.metadata["patch"]
    assert isinstance(patch_summary, dict)
    assert patch_summary["operation_count"] == 1
    assert result_b.terminal_metadata == result_b.error.metadata

    live_scene, identity = state.snapshot()
    assert identity.revision == 1
    assert support.block_generated(live_scene, block_id) == ["note:alpha"]


def test_foreign_conflict_shaped_rebase_result_fails_loudly() -> None:
    """Rebase results must be the core RebasedPatch or MergeConflict types.

    A conflict-shaped foreign object is no longer silently tolerated as a
    merge conflict; the run still ends as a structured failure and the live
    scene stays unchanged.
    """

    class ForeignConflictRebaseActions(domain.DemoActions):
        def rebase_patch(self, _request: object) -> object:
            return types.SimpleNamespace(kind="conflict", reason="duck conflict", metadata={})

    client_a = domain.ControlledClient(["alpha"])
    client_b = domain.ControlledClient(["beta"])
    runtime_a = support.runtime(client_a, actions=flow.RebaseDemoActions())
    runtime_b = support.runtime(client_b, actions=ForeignConflictRebaseActions())
    state: scene_state.SceneState[domain.DemoScene] = runtime_a.live_state(
        domain.make_scene(block_count=1)
    )
    block_id = state.snapshot()[0].blocks[0].block_id

    result_a, result_b = asyncio.run(
        support.interleave_two_writers(state, runtime_a, client_a, runtime_b, client_b)
    )

    assert result_a.status == "success"
    assert result_b.status == "failure"
    assert result_b.error is not None
    assert result_b.error.kind == "internal_error"

    live_scene, identity = state.snapshot()
    assert identity.revision == 1
    assert support.block_generated(live_scene, block_id) == ["note:alpha"]


def test_invalid_rebased_patch_is_reported_as_merge_conflict() -> None:
    client_a = domain.ControlledClient(["alpha"])
    client_b = domain.ControlledClient(["beta"])
    runtime_a = support.runtime(client_a, actions=flow.RebaseDemoActions())
    runtime_b = support.runtime(client_b, actions=flow.InvalidRebaseDemoActions())
    state: scene_state.SceneState[domain.DemoScene] = runtime_a.live_state(
        domain.make_scene(block_count=1)
    )
    block_id = state.snapshot()[0].blocks[0].block_id

    result_a, result_b = asyncio.run(
        support.interleave_two_writers(state, runtime_a, client_a, runtime_b, client_b)
    )

    assert result_a.status == "success"
    assert result_b.status == "failure"
    assert result_b.error is not None
    assert result_b.error.kind == "merge_conflict"
    assert result_b.error.message == "verification_failed"
    scene_metadata = result_b.error.metadata["scene_metadata"]
    assert isinstance(scene_metadata, dict)
    assert scene_metadata["test_case"] == "invalid_revision"
    assert result_b.error.metadata["base_revision"] == 0
    assert result_b.error.metadata["current_live_revision"] == 1
    patch_summary = result_b.error.metadata["patch"]
    assert isinstance(patch_summary, dict)
    assert patch_summary["operation_count"] == 1
    validation_error = result_b.error.metadata["validation_error"]
    assert isinstance(validation_error, dict)
    assert validation_error == {"kind": "StalePatchError", "message": "stale patch", "metadata": {}}
    assert scene_metadata["message"] == "app merge detail"

    live_scene, identity = state.snapshot()
    assert identity.revision == 1
    assert support.block_generated(live_scene, block_id) == ["note:alpha"]
