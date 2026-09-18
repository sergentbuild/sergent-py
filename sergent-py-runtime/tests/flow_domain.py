from __future__ import annotations

import typing

import demo_domain
import sergent_py_core.operation as core_operation
import sergent_py_core.patch as core_patch
import sergent_py_core.scene as core_scene
import sergent_py_core.target as core_target


class StopDemoIntent(demo_domain.DemoIntent):
    flow: typing.Literal["stop"] = "stop"
    reason: str = "scene already satisfies the target"

    def terminal_message(self) -> str:
        return self.reason

    def terminal_metadata(self) -> dict[str, object]:
        return {"decision": "done"}


class UnsupportedFlowDemoIntent(demo_domain.DemoIntent):
    flow: typing.Literal["fan_out"] = "fan_out"


class StopDemoRecipe(demo_domain.DemoRecipe):
    """Derives a stop Intent from a model-backed Intent proposal."""

    def derive_intent(
        self,
        scene: demo_domain.DemoScene,
        identity: core_scene.SceneIdentity,
        target: core_target.Target,
        intent_proposal: demo_domain.DemoIntentProposal,
    ) -> StopDemoIntent:
        intent = super().derive_intent(scene, identity, target, intent_proposal)
        return StopDemoIntent(**intent.model_dump())


class UnsupportedFlowDemoRecipe(demo_domain.DemoRecipe):
    """Derive an Intent outside the closed flow vocabulary for containment coverage."""

    def derive_intent(
        self,
        scene: demo_domain.DemoScene,
        identity: core_scene.SceneIdentity,
        target: core_target.Target,
        intent_proposal: demo_domain.DemoIntentProposal,
    ) -> UnsupportedFlowDemoIntent:
        intent = super().derive_intent(scene, identity, target, intent_proposal)
        return UnsupportedFlowDemoIntent(**intent.model_dump())


class RebaseDemoActions(demo_domain.DemoActions):
    """DemoActions that additionally rebases stale demo patches."""

    def __init__(
        self, *, conflict: bool = False, metadata: dict[str, object] | None = None
    ) -> None:
        self.conflict = conflict
        self.metadata: dict[str, object] = (
            metadata
            if metadata is not None
            else ({"cause": "test_conflict"} if conflict else {"rebased": True})
        )
        self.selected_targets: list[core_target.Target] = []
        self.rebase_targets: list[core_target.Target] = []
        self.applied_targets: list[core_target.Target] = []

    def select_target(self, scene: demo_domain.DemoScene) -> core_target.Target | None:
        target = super().select_target(scene)
        if target is not None:
            self.selected_targets.append(target)
        return target

    def apply(
        self,
        scene: demo_domain.DemoScene,
        target: core_target.Target,
        operations: list[core_operation.Operation],
    ) -> demo_domain.DemoScene:
        self.applied_targets.append(target)
        return super().apply(scene, target, operations)

    def rebase_patch(
        self,
        request: core_patch.PatchRebaseRequest[demo_domain.DemoScene],
    ) -> core_patch.RebasedPatch | core_patch.MergeConflict:
        self.rebase_targets.append(request.target)
        if self.conflict:
            return core_patch.MergeConflict(
                reason="demo conflict",
                metadata=self.metadata,
            )
        return core_patch.RebasedPatch(
            patch=request.patch.model_copy(
                update={
                    "base": core_scene.SceneIdentity(
                        scene_id=request.current_identity.scene_id,
                        revision=request.current_identity.revision,
                    )
                }
            ),
            metadata=self.metadata,
        )


class InvalidRebaseDemoActions(RebaseDemoActions):
    """Returns a rebased patch that fails runtime validation."""

    def rebase_patch(
        self,
        request: core_patch.PatchRebaseRequest[demo_domain.DemoScene],
    ) -> core_patch.RebasedPatch | core_patch.MergeConflict:
        rebased = super().rebase_patch(request)
        if isinstance(rebased, core_patch.MergeConflict):
            return rebased
        return core_patch.RebasedPatch(
            patch=rebased.patch.model_copy(
                update={
                    "base": core_scene.SceneIdentity(
                        scene_id=request.current_identity.scene_id,
                        revision=request.current_identity.revision + 1,
                    )
                }
            ),
            metadata={
                "rebased": True,
                "test_case": "invalid_revision",
                "message": "app merge detail",
            },
        )
