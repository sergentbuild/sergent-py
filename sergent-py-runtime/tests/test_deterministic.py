"""Unit tests for the synchronous validation/execution core.

These pin the exact rejection messages and the structural ordering rules in
``validate_patch``. The engine maps these into ``RunError`` kinds, so the
wording is load-bearing.
"""

from __future__ import annotations

import copy

import pytest
import demo_domain
import sergent_py_core.operation as core_operation
import sergent_py_core.patch as core_patch
import sergent_py_core.scene as core_scene
import sergent_py_core.target as core_target
import sergent_py_core.identifiers as identifiers
import sergent_py_runtime.execution.deterministic as deterministic
import sergent_py_runtime.execution.errors as errors


def _scene_and_id() -> tuple[
    demo_domain.DemoScene,
    core_scene.SceneIdentity,
    core_target.Target,
    demo_domain.DemoActions,
]:
    actions = demo_domain.DemoActions()
    scene = demo_domain.make_scene(block_count=1)
    identity = actions.identity(scene)
    target = core_target.Target(target_id=scene.blocks[0].block_id)
    return scene, identity, target, actions


def _patch(
    identity: core_scene.SceneIdentity,
    *,
    op_count: int = 1,
) -> demo_domain.DemoPatch:
    operations: list[core_operation.Operation] = [
        demo_domain.DemoOperation(text="hello") for _ in range(op_count)
    ]
    return core_patch.Patch(
        base=identity.model_copy(deep=True),
        operations=operations,
        operation_trace=[
            core_operation.OperationTrace(op_id=operation.op_id) for operation in operations
        ],
    )


def test_validate_patch_accepts_well_formed_patch() -> None:
    scene, identity, target, actions = _scene_and_id()
    deterministic.validate_patch(actions, scene, identity, target, _patch(identity))


def test_validate_patch_scene_mismatch() -> None:
    scene, identity, target, actions = _scene_and_id()
    patch = _patch(identity).model_copy(
        update={
            "base": core_scene.SceneIdentity(
                scene_id=identifiers.new_id("scene"), revision=identity.revision
            )
        }
    )
    with pytest.raises(errors.PatchValidationError, match="patch scene mismatch"):
        deterministic.validate_patch(actions, scene, identity, target, patch)


def test_validate_patch_stale_revision() -> None:
    scene, identity, target, actions = _scene_and_id()
    patch = _patch(identity).model_copy(
        update={"base": core_scene.SceneIdentity(scene_id=identity.scene_id, revision=99)}
    )
    with pytest.raises(errors.StalePatchError, match="stale patch"):
        deterministic.validate_patch(actions, scene, identity, target, patch)


def test_validate_patch_no_op() -> None:
    scene, identity, target, actions = _scene_and_id()
    empty: core_patch.Patch = core_patch.Patch(
        base=core_scene.SceneIdentity(scene_id=identity.scene_id, revision=identity.revision),
        operations=[],
        operation_trace=[],
    )
    with pytest.raises(errors.PatchValidationError, match="no-op patch"):
        deterministic.validate_patch(actions, scene, identity, target, empty)


def test_validate_patch_missing_target() -> None:
    scene, identity, _, actions = _scene_and_id()
    other = core_target.Target(target_id=identifiers.new_id("block"))
    with pytest.raises(errors.PatchValidationError, match="missing target"):
        deterministic.validate_patch(actions, scene, identity, other, _patch(identity))


def test_validate_patch_trace_length_mismatch() -> None:
    scene, identity, target, actions = _scene_and_id()
    patch = _patch(identity, op_count=2)
    patch = patch.model_copy(update={"operation_trace": patch.operation_trace[:1]})
    with pytest.raises(errors.PatchValidationError, match="operation trace must match operations"):
        deterministic.validate_patch(actions, scene, identity, target, patch)


def test_validate_patch_rejects_non_operation_objects() -> None:
    scene, identity, target, actions = _scene_and_id()
    op_id = identifiers.new_id("op")
    patch: core_patch.Patch = _patch(identity).model_copy(
        update={
            "operations": [{"op_id": op_id}],
            "operation_trace": [core_operation.OperationTrace(op_id=op_id)],
        }
    )
    with pytest.raises(errors.PatchValidationError, match="operation must subclass Operation"):
        deterministic.validate_patch(actions, scene, identity, target, patch)


def test_validate_patch_duplicate_op_id() -> None:
    scene, identity, target, actions = _scene_and_id()
    patch = _patch(identity)
    dup_ops = [patch.operations[0], patch.operations[0]]
    dup_trace = [patch.operation_trace[0], patch.operation_trace[0]]
    patch = patch.model_copy(update={"operations": dup_ops, "operation_trace": dup_trace})
    with pytest.raises(errors.PatchValidationError, match="duplicate op_id"):
        deterministic.validate_patch(actions, scene, identity, target, patch)


def test_validate_patch_trace_op_id_mismatch() -> None:
    scene, identity, target, actions = _scene_and_id()
    patch = _patch(identity)
    mismatched = [patch.operation_trace[0].model_copy(update={"op_id": identifiers.new_id("op")})]
    patch = patch.model_copy(update={"operation_trace": mismatched})
    with pytest.raises(errors.PatchValidationError, match="operation trace op_id mismatch"):
        deterministic.validate_patch(actions, scene, identity, target, patch)


def test_dry_run_returns_after_scene_without_mutating_snapshot() -> None:
    scene, identity, target, actions = _scene_and_id()
    snapshot = copy.deepcopy(scene)
    after = deterministic.dry_run(actions, scene, identity, target, _patch(identity))
    block_id = target.target_id
    after_block = next(b for b in after.blocks if b.block_id == block_id)
    assert after_block.generated == ["hello"]
    # Snapshot is untouched -- dry-run clones internally.
    assert scene == snapshot


def test_dry_run_rejects_scene_identity_replacement_without_mutating_snapshot() -> None:
    class IdentityReplacingActions(demo_domain.DemoActions):
        def apply(
            self,
            scene: demo_domain.DemoScene,
            target: core_target.Target,
            operations: list[core_operation.Operation],
        ) -> demo_domain.DemoScene:
            after = super().apply(scene, target, operations)
            return after.model_copy(update={"scene_id": identifiers.new_id("scene")})

    scene, identity, target, _ = _scene_and_id()
    snapshot = copy.deepcopy(scene)

    with pytest.raises(ValueError, match="dry-run scene mismatch"):
        deterministic.dry_run(IdentityReplacingActions(), scene, identity, target, _patch(identity))

    assert scene == snapshot


def test_commit_applies_to_clone() -> None:
    scene, identity, target, actions = _scene_and_id()
    snapshot = copy.deepcopy(scene)
    committed = deterministic.commit(scene, target, _patch(identity), actions)
    block_id = target.target_id
    committed_block = next(b for b in committed.blocks if b.block_id == block_id)
    assert committed_block.generated == ["hello"]
    assert scene == snapshot
