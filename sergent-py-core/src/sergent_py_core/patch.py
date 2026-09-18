"""Define Patch and Scene-owned rebase values. @sergent/docs/framework.md
@sergent-py-core/docs/core-class-design-pattern.md"""

from __future__ import annotations

import typing

import pydantic

import sergent_py_core.operation as operation
import sergent_py_core.scene as scene
import sergent_py_core.strict_model as strict_model
import sergent_py_core.target as target_values

SceneT = typing.TypeVar("SceneT")


class Patch(strict_model.StrictModel):
    """Carry deterministic Scene modifications bound to one base identity. @sergent/docs/framework.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    base: scene.SceneIdentity
    operations: list[operation.Operation]
    operation_trace: list[operation.OperationTrace]


class PatchRebaseRequest(strict_model.StrictModel, typing.Generic[SceneT]):
    """Carry bounded facts for a Scene-owned stale Patch decision. @sergent/docs/framework.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    base_scene: SceneT
    current_scene: SceneT
    current_identity: scene.SceneIdentity
    target: target_values.Target
    patch: Patch


class RebasedPatch(strict_model.StrictModel):
    """Return a Scene-approved Patch replacement with bounded metadata. @sergent/docs/framework.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    patch: Patch
    metadata: dict[str, object] = pydantic.Field(default_factory=dict)


class MergeConflict(strict_model.StrictModel):
    """Describe a deterministic Scene-owned rebase rejection. @sergent/docs/framework.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    reason: str
    metadata: dict[str, object] = pydantic.Field(default_factory=dict)
