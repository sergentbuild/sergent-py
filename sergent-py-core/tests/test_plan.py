from __future__ import annotations

import typing

import pydantic
import pytest

import sergent_py_core.identifiers as identifiers
import sergent_py_core.operation as operation
import sergent_py_core.plan as plan
import sergent_py_core.scene as scene
import sergent_py_core.target as target


class PlanOperation(operation.Operation, frozen=True):
    call: typing.Literal["plan"] = "plan"

    def apply(self, scene: object, _target: target.Target) -> object:
        return scene


def test_plan_proposal_enforces_a_non_empty_typed_operation_list() -> None:
    plan_operation = PlanOperation()

    proposal = plan.PlanProposal(operations=[plan_operation])

    assert proposal.operations == [plan_operation]
    assert proposal.operations[0] is plan_operation
    with pytest.raises(pydantic.ValidationError) as error:
        plan.PlanProposal(operations=[])
    assert error.value.errors(include_url=False)[0]["type"] == "too_short"


def test_execution_plan_uses_scene_identity_owner() -> None:
    scene_id = identifiers.new_id("doc")
    base = scene.SceneIdentity(scene_id=scene_id, revision=0)
    execution_plan = plan.ExecutionPlan(
        base=base,
        steps=[PlanOperation()],
    )

    assert execution_plan.base is base
    assert set(execution_plan.model_dump()) == {"base", "steps"}
