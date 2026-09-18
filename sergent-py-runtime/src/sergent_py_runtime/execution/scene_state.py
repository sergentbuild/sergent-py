"""Provide lock-guarded live Scene commit authority. @sergent/docs/framework.md
@sergent-py-runtime/docs/KNOWLEDGE.md"""

from __future__ import annotations

import dataclasses
import threading
import typing

import sergent_py_core.scene as core_scene
import sergent_py_runtime.execution.errors as runtime_errors

SceneT = typing.TypeVar("SceneT")


@dataclasses.dataclass(frozen=True)
class CommitResult(typing.Generic[SceneT]):
    """Carry an exact or rebased live Scene commit. @sergent/docs/framework.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    kind: typing.Literal["exact", "rebased"]
    scene: SceneT
    identity: core_scene.SceneIdentity
    metadata: dict[str, object]


class SceneState(typing.Generic[SceneT]):
    """Guard live Scene mutation with revision checks. @sergent/docs/framework.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    def __init__(
        self,
        identity: typing.Callable[[SceneT], core_scene.SceneIdentity],
        clone: typing.Callable[[SceneT], SceneT],
        scene: SceneT,
        *,
        enforce_embedded_identity: bool = False,
    ) -> None:
        self._identify = identity
        self._clone = clone
        self._scene = clone(scene)
        self._identity = identity(scene)
        self._enforce_embedded_identity = enforce_embedded_identity
        self._lock = threading.Lock()

    def snapshot(self) -> tuple[SceneT, core_scene.SceneIdentity]:
        """Return an isolated Scene snapshot and identity. @sergent/docs/framework.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        with self._lock:
            return (self._clone(self._scene), self._identity.model_copy(deep=True))

    def try_commit(
        self,
        base_revision: int,
        mutate: typing.Callable[[SceneT], SceneT],
    ) -> core_scene.SceneIdentity:
        """Commit only while the observed revision is current. @sergent/docs/framework.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        return self.try_commit_patch(base_revision, mutate).identity

    def try_commit_patch(
        self,
        base_revision: int,
        strict_mutate: typing.Callable[[SceneT], SceneT],
        rebase_mutate: typing.Callable[
            [SceneT, core_scene.SceneIdentity],
            tuple[SceneT, dict[str, object]],
        ]
        | None = None,
    ) -> CommitResult[SceneT]:
        """Commit exactly or invoke Scene-owned rebase after drift. @sergent/docs/framework.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        with self._lock:
            if self._identity.revision == base_revision:
                updated = strict_mutate(self._scene)
                kind: typing.Literal["exact", "rebased"] = "exact"
                metadata: dict[str, object] = {}
            elif rebase_mutate is None:
                raise runtime_errors.StalePatchError(
                    "stale patch",
                    base_revision=base_revision,
                    current_revision=self._identity.revision,
                )
            else:
                updated, metadata = rebase_mutate(
                    self._clone(self._scene),
                    self._identity.model_copy(deep=True),
                )
                kind = "rebased"
            next_identity = self._identity.model_copy(
                update={"revision": self._identity.revision + 1}
            )
            self._validate_updated_identity(updated, next_identity)
            self._scene = self._clone(updated)
            self._identity = next_identity
            return CommitResult(
                kind=kind,
                scene=self._clone(self._scene),
                identity=self._identity.model_copy(deep=True),
                metadata=dict(metadata),
            )

    def _validate_updated_identity(
        self,
        updated: SceneT,
        next_identity: core_scene.SceneIdentity,
    ) -> None:
        """Reject mutation that violates identity representation. @sergent/docs/framework.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        updated_identity = self._identify(updated)
        if not self._enforce_embedded_identity:
            if updated_identity.scene_id != self._identity.scene_id:
                raise runtime_errors.PatchValidationError("commit scene mismatch")
            return
        issues = core_scene.identity_transition_issues(self._identity, updated_identity)
        if issues:
            raise runtime_errors.PatchValidationError(
                "commit embedded identity mismatch",
                metadata={
                    "identity_issues": list(issues),
                    "expected_identity": next_identity.model_dump(mode="json"),
                    "actual_identity": updated_identity.model_dump(mode="json"),
                },
            )
