"""Coordinate deterministic live Patch rebase at commit. @sergent/docs/framework.md
@sergent-py-runtime/docs/KNOWLEDGE.md"""

from __future__ import annotations

import dataclasses
import typing

import sergent_py_core.patch as core_patch
import sergent_py_core.scene as core_scene
import sergent_py_core.scene_actions as core_scene_actions
import sergent_py_core.target as core_target
import sergent_py_runtime.execution.deterministic as runtime_deterministic
import sergent_py_runtime.execution.errors as runtime_errors
import sergent_py_runtime.execution.scene_state as runtime_scene_state

SceneT = typing.TypeVar("SceneT")


@typing.runtime_checkable
class _RebaseCapable(typing.Protocol):
    """Define optional Scene-owned stale Patch rebase. @sergent/docs/framework.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    def rebase_patch(
        self,
        request: core_patch.PatchRebaseRequest[typing.Any],
        /,
    ) -> core_patch.RebasedPatch | core_patch.MergeConflict:
        """Return a replacement Patch or merge conflict. @sergent/docs/framework.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        ...


@dataclasses.dataclass(frozen=True)
class _PatchRebaseBase(typing.Generic[SceneT]):
    """Carry immutable facts for one live rebase decision. @sergent/docs/framework.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    base_scene: SceneT
    base_identity: core_scene.SceneIdentity
    target: core_target.Target
    patch: core_patch.Patch


@dataclasses.dataclass(frozen=True)
class _RebaseMutation(typing.Generic[SceneT]):
    """Validate and rehearse a Scene-owned rebased Patch. @sergent/docs/framework.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    scene: core_scene_actions.SceneActions[SceneT]
    rebase: _RebaseCapable
    request: _PatchRebaseBase[SceneT]
    patch_summary: dict[str, object]
    intent: object

    def __call__(
        self,
        current_scene: SceneT,
        current_identity: core_scene.SceneIdentity,
    ) -> tuple[SceneT, dict[str, object]]:
        req = self.request
        merge = self.rebase.rebase_patch(
            core_patch.PatchRebaseRequest(
                base_scene=req.base_scene,
                current_scene=current_scene,
                current_identity=current_identity,
                target=req.target,
                patch=req.patch,
            )
        )
        if isinstance(merge, core_patch.MergeConflict):
            metadata = self._conflict_metadata(current_identity, dict(merge.metadata))
            raise runtime_errors.MergeConflictError(merge.reason, metadata=metadata)
        rebased_patch = merge.patch
        metadata = dict(merge.metadata)
        try:
            after = self._rehearse_rebased_patch(
                current_scene,
                current_identity,
                rebased_patch,
            )
        except (runtime_errors.PatchValidationError, ValueError) as exc:
            is_admissibility = isinstance(exc, runtime_errors._OperationAdmissibilityError)
            check_metadata = (
                exc.metadata
                if isinstance(
                    exc,
                    (
                        runtime_errors.PatchValidationError,
                        runtime_errors.DryRunError,
                        runtime_errors._OperationAdmissibilityError,
                    ),
                )
                else {}
            )
            conflict_metadata = self._conflict_metadata(current_identity, metadata)
            conflict_metadata["validation_error"] = {
                "kind": ("operation_admissibility" if is_admissibility else type(exc).__name__),
                "message": str(exc),
                "metadata": dict(check_metadata),
            }
            reason = "operation_not_admissible" if is_admissibility else "verification_failed"
            raise runtime_errors.MergeConflictError(
                reason,
                metadata=conflict_metadata,
            ) from exc
        return after, metadata

    def _rehearse_rebased_patch(
        self,
        current_scene: SceneT,
        current_identity: core_scene.SceneIdentity,
        rebased_patch: core_patch.Patch,
    ) -> SceneT:
        """Rehearse against the current Scene before commit. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        target = self.request.target
        runtime_deterministic.validate_patch(
            self.scene,
            current_scene,
            current_identity,
            target,
            rebased_patch,
        )
        runtime_deterministic._validate_operations(
            self.scene,
            current_scene,
            self.intent,
            target,
            rebased_patch.operations,
        )
        return runtime_deterministic.dry_run(
            self.scene,
            current_scene,
            current_identity,
            target,
            rebased_patch,
        )

    def _conflict_metadata(
        self, current_identity: core_scene.SceneIdentity, scene_metadata: dict[str, object]
    ) -> dict[str, object]:
        """Separate revision, Patch, and app conflict facts. @sergent/docs/run-record-spec.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        return {
            "base_revision": self.request.base_identity.revision,
            "current_live_revision": current_identity.revision,
            "patch": self.patch_summary,
            "scene_metadata": scene_metadata,
        }


def _commit_live(
    source: runtime_scene_state.SceneState[SceneT],
    scene: core_scene_actions.SceneActions[SceneT],
    request: _PatchRebaseBase[SceneT],
    patch_summary: dict[str, object],
    intent: object,
) -> runtime_scene_state.CommitResult[SceneT]:
    """Commit through live authority with optional Scene-owned rebase. @sergent/docs/framework.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    rebase_mutate = None
    if isinstance(scene, _RebaseCapable):
        rebase_mutate = _RebaseMutation(
            scene=scene,
            rebase=scene,
            request=request,
            patch_summary=patch_summary,
            intent=intent,
        )

    return source.try_commit_patch(
        request.base_identity.revision,
        lambda current: scene.apply(
            scene.clone(current), request.target, list(request.patch.operations)
        ),
        rebase_mutate,
    )
