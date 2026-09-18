"""Define deterministic Scene capabilities required by the runtime. @sergent/docs/execution-model.md
@sergent-py-core/docs/core-class-design-pattern.md"""

from __future__ import annotations

import typing

import sergent_py_core.operation as operation_values
import sergent_py_core.scene as scene_values
import sergent_py_core.target as target_values

SceneT = typing.TypeVar("SceneT")


class SceneActions(typing.Protocol[SceneT]):
    """Provide synchronous deterministic authority over one Scene type. @sergent/docs/execution-model.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    def identity(self, scene: SceneT, /) -> scene_values.SceneIdentity:
        """Return the stable Scene identity and current revision view. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        ...

    def clone(self, scene: SceneT, /) -> SceneT:
        """Return an isolated snapshot copy of the Scene. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        ...

    def select_target(self, scene: SceneT, /) -> target_values.Target | None:
        """Choose a bounded target through a deterministic Scene read. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        ...

    def has_target(
        self,
        scene: SceneT,
        target: target_values.Target,
        /,
    ) -> bool:
        """Return whether the selected target still exists. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        ...

    def apply(
        self,
        scene: SceneT,
        target: target_values.Target,
        operations: list[operation_values.Operation],
        /,
    ) -> SceneT:
        """Return the after-Scene for Operations against the selected target. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        ...

    def verify(
        self,
        before: SceneT,
        after: SceneT,
        target: target_values.Target,
        operations: list[operation_values.Operation],
        /,
    ) -> scene_values.VerificationReport:
        """Report domain-invariant issues in the dry-run's resulting Scene. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        ...
