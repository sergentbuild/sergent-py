"""Provide generic helpers for deterministic Scene adapters.
@sergent/docs/execution-model.md
@sergent-py/docs/KNOWLEDGE.md"""

from __future__ import annotations

import collections.abc as cabc
import typing

import sergent_py_core.operation as core_operation
import sergent_py_core.scene as core_scene
import sergent_py_core.target as core_target

SceneT = typing.TypeVar("SceneT")
IdentitySource = cabc.Callable[[typing.Any], core_scene.SceneIdentity] | str


def pydantic_clone(scene: SceneT) -> SceneT:
    """Produce an isolated Pydantic Scene snapshot. @sergent/docs/execution-model.md
    @sergent-py/docs/KNOWLEDGE.md"""
    model_copy = getattr(scene, "model_copy", None)
    if not callable(model_copy):
        raise TypeError("scene must provide model_copy")
    return typing.cast(SceneT, model_copy(deep=True))


def field_identity(
    id_attr: str,
    revision_attr: str,
) -> cabc.Callable[[typing.Any], core_scene.SceneIdentity]:
    """Build a Scene identity projector from non-empty model field names.
    @sergent/docs/execution-model.md
    @sergent-py/docs/KNOWLEDGE.md"""
    if not id_attr or not revision_attr:
        raise ValueError("identity field names must be non-empty")

    def identity(scene: typing.Any) -> core_scene.SceneIdentity:
        return core_scene.SceneIdentity(
            scene_id=getattr(scene, id_attr),
            revision=getattr(scene, revision_attr),
        )

    return identity


def apply_operations_in_order(
    scene: SceneT,
    target: core_target.Target,
    operations: cabc.Iterable[core_operation.Operation],
) -> SceneT:
    """Apply a non-empty Operation sequence in order with the exact selected target.
    @sergent/docs/execution-model.md
    @sergent-py/docs/KNOWLEDGE.md"""
    ordered = list(operations)
    if not ordered:
        raise ValueError("apply requires at least one operation")
    updated = scene
    for operation in ordered:
        updated = operation.apply(updated, target)
    return updated


def whole_scene_target(
    scene: typing.Any,
    identity_or_target_id: IdentitySource,
) -> core_target.Target:
    """Bind the complete Scene to one deterministic target identity.
    @sergent/docs/execution-model.md
    @sergent-py/docs/KNOWLEDGE.md"""
    return core_target.Target(target_id=_whole_scene_target_id(scene, identity_or_target_id))


def whole_scene_has_target(
    scene: typing.Any,
    target: core_target.Target,
    identity_or_target_id: IdentitySource,
) -> bool:
    """Confirm that a target names the complete Scene under the app identity rule.
    @sergent/docs/execution-model.md
    @sergent-py/docs/KNOWLEDGE.md"""
    return target.target_id == _whole_scene_target_id(scene, identity_or_target_id)


def basic_identity_verifier(
    before: SceneT,
    after: SceneT,
    identity: cabc.Callable[[SceneT], core_scene.SceneIdentity],
) -> list[str]:
    """Report Scene ID drift or a revision advance other than one.
    @sergent/docs/execution-model.md
    @sergent-py/docs/KNOWLEDGE.md"""
    before_identity = identity(before)
    after_identity = identity(after)
    return core_scene.identity_transition_issues(
        before_identity,
        after_identity,
    )


def _whole_scene_target_id(
    scene: typing.Any,
    identity_or_target_id: IdentitySource,
) -> str:
    """Resolve the target identity used by whole-Scene helpers."""
    if callable(identity_or_target_id):
        return identity_or_target_id(scene).scene_id
    return identity_or_target_id
