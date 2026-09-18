from __future__ import annotations

import typing

import pytest

import sergent_py_core.mindbuf as core_mindbuf
import sergent_py_core.model_calls as core_model_calls
import sergent_py_core.operation as core_operation
import sergent_py_core.plan as core_plan
import sergent_py_core.recipe as core_recipe
import sergent_py_core.scene as core_scene
import sergent_py_core.target as core_target
import sergent_py_core.identifiers as identifiers


class RecipeOperation(core_operation.Operation, frozen=True):
    call: typing.Literal["recipe"] = "recipe"
    values: list[str]

    def apply(self, scene: object, _target: core_target.Target) -> object:
        return scene


class RecipeIntent:
    pass


class MinimalRecipe(core_recipe.SergentRecipe[object, object, RecipeIntent]):
    def derive_intent(
        self,
        scene: object,
        identity: core_scene.SceneIdentity,
        target: core_target.Target,
        intent_proposal: object,
    ) -> RecipeIntent:
        return RecipeIntent()


def test_recipe_without_derive_intent_cannot_be_instantiated() -> None:
    class MissingIntentRecipe(core_recipe.SergentRecipe[object, object, RecipeIntent]):
        pass

    with pytest.raises(TypeError, match="derive_intent"):
        MissingIntentRecipe()  # pyright: ignore[reportAbstractUsage] - deliberate


def test_recipe_request_builder_defaults_raise() -> None:
    recipe = MinimalRecipe()
    scene = object()
    target = core_target.Target(target_id="target")
    mindbuf = core_mindbuf.MindBuf()
    intent = RecipeIntent()
    proposal_schema = core_model_calls.ProposalSchema(
        name="RecipeProposal",
        json_schema={"type": "object"},
    )

    with pytest.raises(AssertionError):
        recipe.build_intent_request(scene, mindbuf, target, "fake", proposal_schema)
    with pytest.raises(AssertionError):
        recipe.build_plan_request(scene, target, intent, mindbuf, "fake", proposal_schema)


def test_recipe_defaults_to_intent_only_without_a_plan_bound() -> None:
    recipe = MinimalRecipe()

    assert recipe.operation_registry is None
    assert recipe.max_operations is None


def test_recipe_empty_validators_accept() -> None:
    recipe = MinimalRecipe()
    scene = object()
    identity = core_scene.SceneIdentity(scene_id=identifiers.new_id("scene"), revision=3)
    target = core_target.Target(target_id="target")
    intent = RecipeIntent()
    operations: list[core_operation.Operation] = [RecipeOperation(values=[])]
    plan = core_plan.ExecutionPlan(
        base=identity,
        steps=operations,
    )

    assert recipe.validate_intent(scene, identity, intent) is None
    assert recipe.validate_plan(scene, identity, target, intent, plan) is None


def test_recipe_default_derive_plan_isolates_proposal_operations() -> None:
    recipe = MinimalRecipe()
    identity = core_scene.SceneIdentity(scene_id=identifiers.new_id("scene"), revision=7)
    intent = RecipeIntent()
    target = core_target.Target(target_id="target")
    operations: list[core_operation.Operation] = [
        RecipeOperation(values=["first"]),
        RecipeOperation(values=["second"]),
    ]
    proposal = core_plan.PlanProposal(operations=operations)
    expected_steps = list(proposal.operations)

    plan = recipe.derive_plan(object(), identity, target, intent, proposal)
    proposal.operations.clear()

    assert plan.steps is not proposal.operations
    assert plan.base is identity
    assert plan.steps == expected_steps


def test_recipe_default_compile_patch_deep_copies_operation_data_and_trace() -> None:
    recipe = MinimalRecipe()
    identity = core_scene.SceneIdentity(scene_id=identifiers.new_id("scene"), revision=7)
    plan_operation = RecipeOperation(values=["plan"])
    plan = core_plan.ExecutionPlan(
        base=identity,
        steps=[plan_operation],
    )

    patch = recipe.compile_patch(plan)
    patch_operation = patch.operations[0]

    assert isinstance(patch_operation, RecipeOperation)
    assert patch_operation is not plan_operation
    assert patch_operation.op_id == plan_operation.op_id
    assert patch.operation_trace == [core_operation.OperationTrace(op_id=plan_operation.op_id)]
    patch_operation.values.append("patch")
    assert patch_operation.values == ["plan", "patch"]
    assert plan_operation.values == ["plan"]


def test_recipe_default_compile_patch_rejects_empty_plan() -> None:
    recipe = MinimalRecipe()
    identity = core_scene.SceneIdentity(scene_id=identifiers.new_id("scene"), revision=0)
    plan = core_plan.ExecutionPlan(base=identity, steps=[])

    with pytest.raises(ValueError):
        recipe.compile_patch(plan)
