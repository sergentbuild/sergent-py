"""Provide the pure synchronous Patch execution core. @sergent/docs/execution-model.md
@sergent-py-runtime/docs/KNOWLEDGE.md"""

from __future__ import annotations

import collections.abc as cabc
import typing

import sergent_py_core.operation as core_operation
import sergent_py_core.patch as core_patch
import sergent_py_core.scene as core_scene
import sergent_py_core.scene_actions as core_scene_actions
import sergent_py_core.target as core_target
import sergent_py_runtime.execution.errors as runtime_errors

SceneT = typing.TypeVar("SceneT")


def _validate_operations(
    scene_actions: core_scene_actions.SceneActions[SceneT],
    scene: SceneT,
    intent: object,
    target: core_target.Target,
    operations: cabc.Sequence[core_operation.Operation],
) -> None:
    """Reject the first Operation inadmissible for one bounded pass. @sergent/docs/framework.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    for index, operation in enumerate(operations):
        isolated_scene = scene_actions.clone(scene)
        try:
            operation.validate_for(isolated_scene, intent, target)
        except ValueError as exc:
            metadata = {"index": index, "call": operation.call, "operation_id": operation.op_id}
            raise runtime_errors._OperationAdmissibilityError(str(exc), metadata) from exc


def validate_patch(
    scene: core_scene_actions.SceneActions[SceneT],
    snapshot: SceneT,
    identity: core_scene.SceneIdentity,
    target: core_target.Target,
    patch: core_patch.Patch,
) -> None:
    """Reject a Patch unsafe for its captured Scene context. @sergent/docs/framework.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    if patch.base.scene_id != identity.scene_id:
        raise runtime_errors.PatchValidationError("patch scene mismatch")
    if patch.base.revision != identity.revision:
        raise runtime_errors.StalePatchError(
            "stale patch",
            base_revision=patch.base.revision,
            current_revision=identity.revision,
        )
    if not patch.operations:
        raise runtime_errors.PatchValidationError("no-op patch")
    if not scene.has_target(snapshot, target):
        raise runtime_errors.PatchValidationError("missing target")
    if len(patch.operation_trace) != len(patch.operations):
        raise runtime_errors.PatchValidationError("operation trace must match operations")

    seen_ops: set[str] = set()
    for trace, operation in zip(patch.operation_trace, patch.operations):
        if not isinstance(operation, core_operation.Operation):
            raise runtime_errors.PatchValidationError("operation must subclass Operation")
        op_id = operation.op_id
        if op_id in seen_ops:
            raise runtime_errors.PatchValidationError("duplicate op_id")
        seen_ops.add(op_id)
        if trace.op_id != op_id:
            raise runtime_errors.PatchValidationError("operation trace op_id mismatch")


def dry_run(
    scene: core_scene_actions.SceneActions[SceneT],
    snapshot: SceneT,
    identity: core_scene.SceneIdentity,
    target: core_target.Target,
    patch: core_patch.Patch,
) -> SceneT:
    """Rehearse a Patch without source mutation. @sergent/docs/execution-model.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    after = scene.apply(scene.clone(snapshot), target, list(patch.operations))
    report = scene.verify(snapshot, after, target, list(patch.operations))
    if not report.ok:
        raise runtime_errors.DryRunError(
            "dry-run verification failed: " + "; ".join(report.issues),
            metadata={"verification_issues": list(report.issues)},
        )
    if scene.identity(after).scene_id != identity.scene_id:
        raise ValueError("dry-run scene mismatch")
    return after


def commit(
    snapshot: SceneT,
    target: core_target.Target,
    patch: core_patch.Patch,
    scene: core_scene_actions.SceneActions[SceneT],
) -> SceneT:
    """Apply a Patch to an isolated plain Scene. @sergent/docs/execution-model.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    return scene.apply(scene.clone(snapshot), target, list(patch.operations))
