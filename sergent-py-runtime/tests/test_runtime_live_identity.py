from __future__ import annotations

import asyncio

import pytest

import demo_domain as domain
import runtime_test_support as support
import sergent_py_core.mindbuf as core_mindbuf
import sergent_py_core.scene as core_scene
import sergent_py_core.strict_model as core_strict_model
import sergent_py_core.identifiers as identifiers
import sergent_py_runtime.execution.errors as errors
import sergent_py_runtime.execution.scene_state as scene_state
import sergent_py_runtime.lifecycle.observe as observe


class _EmbeddedScene(core_strict_model.StrictModel):
    scene_id: str
    revision: int = 0
    body: str = ""


def _embedded_identity(scene: _EmbeddedScene) -> core_scene.SceneIdentity:
    return core_scene.SceneIdentity(scene_id=scene.scene_id, revision=scene.revision)


def _embedded_clone(scene: _EmbeddedScene) -> _EmbeddedScene:
    return scene.model_copy(deep=True)


def _embedded_state(scene: _EmbeddedScene) -> scene_state.SceneState[_EmbeddedScene]:
    return scene_state.SceneState(
        _embedded_identity,
        _embedded_clone,
        scene,
        enforce_embedded_identity=True,
    )


def test_live_state_default_preserves_external_revision_ownership() -> None:
    runtime = support.runtime(domain.StaticClient(["alpha"]))
    state: scene_state.SceneState[domain.DemoScene] = runtime.live_state(
        domain.make_scene(block_count=1),
        enforce_embedded_identity=False,
    )

    result = asyncio.run(runtime.run(state, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "success"
    live_scene, stored_identity = state.snapshot()
    assert stored_identity.revision == 1
    assert domain.DemoActions().identity(live_scene).revision == 0


def test_live_state_embedded_identity_enforcement_rejects_scene_id_drift() -> None:
    scene = _EmbeddedScene(scene_id=identifiers.new_id("scene"))
    state = _embedded_state(scene)

    with pytest.raises(errors.PatchValidationError) as raised:
        state.try_commit_patch(
            0,
            lambda current: current.model_copy(
                update={"scene_id": identifiers.new_id("scene"), "revision": 1}
            ),
        )

    assert str(raised.value) == "commit embedded identity mismatch"
    assert raised.value.metadata["identity_issues"] == ["scene identity changed"]
    live_scene, identity = state.snapshot()
    assert live_scene == scene
    assert identity.revision == 0


def test_live_state_embedded_identity_enforcement_rejects_revision_mismatch() -> None:
    runtime = support.runtime(domain.StaticClient(["alpha"]))
    scene = domain.make_scene(block_count=1)
    block_id = scene.blocks[0].block_id
    state: scene_state.SceneState[domain.DemoScene] = runtime.live_state(
        scene,
        enforce_embedded_identity=True,
    )

    result = asyncio.run(runtime.run(state, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "failure"
    assert result.error is not None
    assert result.error.kind == "patch_validation"
    assert result.error.message == "commit embedded identity mismatch"
    assert result.error.metadata["identity_issues"] == ["scene revision mismatch"]
    assert result.stage == observe.Stage.COMMIT
    commit_step = support.step(result, "commit")
    assert commit_step.status == "failure"

    live_scene, identity = state.snapshot()
    assert identity.revision == 0
    assert support.block_generated(live_scene, block_id) == []


@pytest.mark.parametrize(
    ("violation", "expected_issue"),
    [
        ("scene_id", "scene identity changed"),
        ("revision", "scene revision mismatch"),
    ],
)
def test_live_state_embedded_identity_rejects_rebased_violation(
    violation: str, expected_issue: str
) -> None:
    scene = _EmbeddedScene(scene_id=identifiers.new_id("scene"))
    state = _embedded_state(scene)
    state.try_commit_patch(
        0,
        lambda current: current.model_copy(update={"revision": 1, "body": "first"}),
    )
    live_before_rebase, identity_before_rebase = state.snapshot()

    def rebase_mutate(
        current: _EmbeddedScene,
        current_identity: core_scene.SceneIdentity,
    ) -> tuple[_EmbeddedScene, dict[str, object]]:
        update: dict[str, object] = {
            "revision": current_identity.revision + 1,
            "body": "rebased",
        }
        if violation == "scene_id":
            update["scene_id"] = identifiers.new_id("scene")
        else:
            update["revision"] = current_identity.revision
        return (
            current.model_copy(update=update),
            {"commit": "rebased"},
        )

    with pytest.raises(errors.PatchValidationError) as raised:
        state.try_commit_patch(
            0,
            lambda current: current.model_copy(update={"revision": current.revision + 1}),
            rebase_mutate,
        )

    assert str(raised.value) == "commit embedded identity mismatch"
    assert raised.value.metadata["identity_issues"] == [expected_issue]
    live_after_rebase, identity_after_rebase = state.snapshot()
    assert live_after_rebase == live_before_rebase
    assert identity_after_rebase == identity_before_rebase
