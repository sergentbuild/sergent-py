"""Define application policy for Intent, Plan, and Patch stages. @sergent/docs/framework.md
@sergent-py-core/docs/core-class-design-pattern.md"""

from __future__ import annotations

import abc
import typing

import sergent_py_core.errors as errors
import sergent_py_core.mindbuf as mindbuf_values
import sergent_py_core.model_calls as model_calls
import sergent_py_core.operation as operation_values
import sergent_py_core.patch as patch_values
import sergent_py_core.plan as plan_values
import sergent_py_core.proposals.operation_registry as operation_registry
import sergent_py_core.scene as scene_values
import sergent_py_core.target as target_values

SceneT = typing.TypeVar("SceneT")
IntentProposalT = typing.TypeVar("IntentProposalT")
IntentT = typing.TypeVar("IntentT")


class SergentRecipe(abc.ABC, typing.Generic[SceneT, IntentProposalT, IntentT]):
    """Own application policy while providing mechanical Run-stage defaults. @sergent/docs/framework.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    intent_proposal_type: type[IntentProposalT]
    operation_registry: operation_registry.OperationRegistry | None = None
    max_operations: int | None = None
    no_target_error: errors.RunError

    def build_intent_request(
        self,
        scene: SceneT,
        mindbuf: mindbuf_values.MindBuf,
        target: target_values.Target,
        model_name: str,
        proposal_schema: model_calls.ProposalSchema,
        /,
    ) -> model_calls.ModelRequest:
        """Build the request for a model-backed Intent phase. @sergent/docs/framework.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        raise AssertionError("model-backed Intent recipe must implement build_intent_request")

    @abc.abstractmethod
    def derive_intent(
        self,
        scene: SceneT,
        identity: scene_values.SceneIdentity,
        target: target_values.Target,
        intent_proposal: IntentProposalT,
        /,
    ) -> IntentT:
        """Derive application Intent from a typed proposal and bounded context. @sergent/docs/framework.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        raise NotImplementedError

    def validate_intent(
        self,
        scene: SceneT,
        identity: scene_values.SceneIdentity,
        intent: IntentT,
        /,
    ) -> None:
        """Reject Intent that violates application semantic rules. @sergent/docs/framework.md
        @sergent-py-core/docs/core-class-design-pattern.md"""

    def build_plan_request(  # noqa: PLR0913 - exact Recipe interface contract.
        self,
        scene: SceneT,
        target: target_values.Target,
        intent: IntentT,
        mindbuf: mindbuf_values.MindBuf,
        model_name: str,
        proposal_schema: model_calls.ProposalSchema,
        /,
    ) -> model_calls.ModelRequest:
        """Build the request for a continuing Intent's Plan phase. @sergent/docs/framework.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        raise AssertionError("continue-flow recipe must implement build_plan_request")

    def derive_plan(
        self,
        scene: SceneT,
        identity: scene_values.SceneIdentity,
        target: target_values.Target,
        intent: IntentT,
        plan_proposal: plan_values.PlanProposal,
        /,
    ) -> plan_values.ExecutionPlan:
        """Derive an Execution Plan from the typed Plan Proposal envelope. @sergent/docs/framework.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        return plan_values.ExecutionPlan(
            base=identity,
            steps=list(plan_proposal.operations),
        )

    def validate_plan(
        self,
        scene: SceneT,
        identity: scene_values.SceneIdentity,
        target: target_values.Target,
        intent: IntentT,
        plan: plan_values.ExecutionPlan,
        /,
    ) -> None:
        """Reject an ExecutionPlan that violates application semantic rules. @sergent/docs/framework.md
        @sergent-py-core/docs/core-class-design-pattern.md"""

    def compile_patch(self, plan: plan_values.ExecutionPlan, /) -> patch_values.Patch:
        """Deep-copy a non-empty ExecutionPlan into an identity-bound Patch. @sergent/docs/framework.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        if not plan.steps:
            raise ValueError("patch requires at least one operation")
        operations = [operation_value.model_copy(deep=True) for operation_value in plan.steps]
        return patch_values.Patch(
            base=plan.base,
            operations=operations,
            operation_trace=[
                operation_values.OperationTrace(op_id=operation_value.op_id)
                for operation_value in operations
            ],
        )
