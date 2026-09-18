from __future__ import annotations

import asyncio
import collections.abc as cabc
import json
import typing

import pytest

import demo_domain as domain
import runtime_test_support as support
import sergent_py_core.errors as core_errors
import sergent_py_core.mindbuf as core_mindbuf
import sergent_py_core.model_calls as core_model_calls
import sergent_py_core.operation as core_operation
import sergent_py_core.patch as core_patch
import sergent_py_core.plan as core_plan
import sergent_py_core.recipe as core_recipe
import sergent_py_core.scene as core_scene
import sergent_py_core.target as core_target
import sergent_py_core.model_calls as model_calls
import sergent_py_core.proposals.operation_registry as operation_registry
import sergent_py_runtime.execution.scene_state as scene_state
import sergent_py_runtime.lifecycle.observe as observe
import sergent_py_runtime.proposals.intent_proposals as intent_proposals


_VISITS: list[tuple[str, tuple[str, ...], str]] = []
_ADMISSIBILITY_TARGETS: list[tuple[str, core_target.Target]] = []
_APPLICATION_TARGETS: list[tuple[str, core_target.Target]] = []


@pytest.fixture(autouse=True)
def _isolate_probe_observations() -> typing.Iterator[None]:
    _VISITS.clear()
    _ADMISSIBILITY_TARGETS.clear()
    _APPLICATION_TARGETS.clear()
    yield
    _VISITS.clear()
    _ADMISSIBILITY_TARGETS.clear()
    _APPLICATION_TARGETS.clear()


class ProbeTarget(core_target.Target):
    mode: typing.Literal["probe"] = "probe"


class ProbeOperation(core_operation.Operation, frozen=True):
    call: typing.Literal["probe"] = "probe"
    label: str
    failure: typing.Literal["none", "reject", "unexpected", "process"] = "none"
    reject_when_populated: bool = False

    def validate_for(
        self,
        scene: object,
        intent: object,
        target: core_target.Target,
    ) -> None:
        if not isinstance(scene, domain.DemoScene) or not isinstance(intent, domain.DemoIntent):
            raise RuntimeError("probe received the wrong context")
        if not isinstance(target, ProbeTarget) or target.mode != "probe":
            raise ValueError("probe requires the exact selected target")
        block = next(item for item in scene.blocks if item.block_id == target.target_id)
        observed = tuple(block.generated)
        _VISITS.append((self.label, observed, target.mode))
        _ADMISSIBILITY_TARGETS.append((self.label, target))
        block.generated.append(f"validator:{self.label}")
        if self.failure == "reject":
            raise ValueError(f"{self.label} rejected")
        if self.failure == "unexpected":
            raise RuntimeError(f"{self.label} exploded")
        if self.failure == "process":
            raise SystemExit(f"{self.label} stopped the process")
        if self.reject_when_populated and observed:
            raise ValueError(f"{self.label} requires an empty target")

    def apply(self, scene: object, target: core_target.Target) -> object:
        if not isinstance(scene, domain.DemoScene):
            raise ValueError("probe apply requires DemoScene")
        if not isinstance(target, ProbeTarget) or target.mode != "probe":
            raise ValueError("probe apply requires the selected probe target")
        _APPLICATION_TARGETS.append((self.label, target))
        block = next(item for item in scene.blocks if item.block_id == target.target_id)
        block.generated.append(self.label)
        scene.selected_block_id = target.target_id
        return scene


_PROBE_OPERATION_REGISTRY = operation_registry.OperationRegistry((ProbeOperation,))


class ProbeActions(domain.DemoActions):
    def __init__(self) -> None:
        self.selected_targets: list[ProbeTarget] = []
        self.applied_targets: list[core_target.Target] = []

    def select_target(self, scene: domain.DemoScene) -> ProbeTarget | None:
        if scene.selected_block_id is None:
            return None
        target = ProbeTarget(target_id=scene.selected_block_id)
        self.selected_targets.append(target)
        return target

    def apply(
        self,
        scene: domain.DemoScene,
        target: core_target.Target,
        operations: list[core_operation.Operation],
    ) -> domain.DemoScene:
        self.applied_targets.append(target)
        return super().apply(scene, target, operations)

    def rebase_patch(
        self,
        request: core_patch.PatchRebaseRequest[domain.DemoScene],
    ) -> core_patch.RebasedPatch:
        current_base = core_scene.SceneIdentity(
            scene_id=request.current_identity.scene_id,
            revision=request.current_identity.revision,
        )
        return core_patch.RebasedPatch(
            patch=request.patch.model_copy(update={"base": current_base}),
            metadata={"index": "application index", "validation_error": "application detail"},
        )


class ProbeRecipe(domain.PassThroughDemoRecipe):
    operation_registry = _PROBE_OPERATION_REGISTRY

    def __init__(self) -> None:
        self.validated_targets: list[core_target.Target] = []
        self.derived_operations: list[core_operation.Operation] = []

    def derive_plan(
        self,
        scene: domain.DemoScene,
        identity: core_scene.SceneIdentity,
        target: core_target.Target,
        intent: domain.DemoIntent,
        plan_proposal: core_plan.PlanProposal,
        /,
    ) -> core_plan.ExecutionPlan:
        plan = super().derive_plan(scene, identity, target, intent, plan_proposal)
        self.derived_operations = list(plan.steps)
        return plan

    def validate_plan(
        self,
        _scene: domain.DemoScene,
        _identity: core_scene.SceneIdentity,
        target: core_target.Target,
        _intent: domain.DemoIntent,
        _plan: core_plan.ExecutionPlan,
        /,
    ) -> None:
        self.validated_targets.append(target)


class RejectIfPlanValidationRuns(ProbeRecipe):
    def validate_plan(self, *_args: object) -> None:
        raise AssertionError("operation rejection must stop before recipe plan validation")


class StopProbeIntent(domain.DemoIntent):
    flow: typing.Literal["stop"] = "stop"


class StopProbeRecipe(
    core_recipe.SergentRecipe[
        domain.DemoScene,
        intent_proposals.IntentProposal_PassThrough,
        StopProbeIntent,
    ]
):
    intent_proposal_type = intent_proposals.IntentProposal_PassThrough
    no_target_error = core_errors.RunError(kind="no_target", message="no target available")

    def derive_intent(
        self,
        _scene: domain.DemoScene,
        identity: core_scene.SceneIdentity,
        _target: core_target.Target,
        _intent_proposal: intent_proposals.IntentProposal_PassThrough,
    ) -> StopProbeIntent:
        intent = domain._intent(identity)
        return StopProbeIntent(**intent.model_dump())


class ProbeClient:
    def __init__(
        self,
        proposal: core_plan.PlanProposal,
        *,
        controlled: bool = False,
    ) -> None:
        self.proposal = proposal
        self.requests: list[model_calls.ModelRequest] = []
        self._control = domain.ControlledCallGate() if controlled else None

    async def invoke(
        self, request: model_calls.ModelRequest
    ) -> tuple[model_calls.ModelResponse, dict[str, typing.Any]]:
        self.requests.append(request)
        if self._control is not None:
            await self._control.park()
        payload: dict[str, typing.Any] = {
            "operations": [
                operation.model_dump(mode="json") for operation in self.proposal.operations
            ]
        }
        return _response(payload), payload

    async def wait_called(self) -> None:
        if self._control is None:
            raise AssertionError("client is not controlled")
        await self._control.wait_called()

    def release(self) -> None:
        if self._control is None:
            raise AssertionError("client is not controlled")
        self._control.release()


class FailingAdmissibilityCloneActions(ProbeActions):
    def __init__(self) -> None:
        super().__init__()
        self.clone_count = 0

    def clone(self, scene: domain.DemoScene) -> domain.DemoScene:
        self.clone_count += 1
        if self.clone_count == 2:
            raise ValueError("admissibility clone failed")
        return super().clone(scene)


def _response(
    payload: dict[str, typing.Any],
) -> model_calls.ModelResponse:
    response = model_calls.ModelResponse(
        identity=core_model_calls.ModelIdentity(provider="fake", model="fake-model"),
        raw_output=json.dumps(payload),
        usage=core_model_calls.CallUsage(latency_ms=1, request_id="req-plan"),
    )
    return response.model_copy(update={"parsed_json": payload})


def _operations(
    *labels: str,
) -> list[ProbeOperation]:
    return [ProbeOperation(label=label) for label in labels]


def _proposal(
    operations: cabc.Sequence[core_operation.Operation],
) -> core_plan.PlanProposal:
    return core_plan.PlanProposal(operations=list(operations))


def test_runtime_invokes_operations_in_order_on_isolated_base_clones() -> None:
    scene = domain.make_scene()
    recipe = ProbeRecipe()
    actions = ProbeActions()
    operations = _operations("first", "second")
    client = ProbeClient(_proposal(operations))

    result = asyncio.run(
        support.runtime(client, recipe=recipe, actions=actions).run(
            scene, core_mindbuf.MindBuf(), model_name="test/fake"
        )
    )

    assert result.status == "success"
    assert _VISITS == [("first", (), "probe"), ("second", (), "probe")]
    assert result.scene.blocks[0].generated == ["first", "second"]
    assert scene.blocks[0].generated == []
    assert len(client.requests) == 1
    selected_target = actions.selected_targets[0]
    assert isinstance(selected_target, ProbeTarget)
    assert selected_target.mode == "probe"
    assert recipe.validated_targets[0] is selected_target
    assert actions.applied_targets
    assert all(target is selected_target for target in actions.applied_targets)
    assert _ADMISSIBILITY_TARGETS
    assert all(target is selected_target for _label, target in _ADMISSIBILITY_TARGETS)
    assert _APPLICATION_TARGETS
    assert all(target is selected_target for _label, target in _APPLICATION_TARGETS)


def test_first_rejection_has_operation_metadata_and_stops_all_downstream_work() -> None:
    scene = domain.make_scene()
    recipe = RejectIfPlanValidationRuns()
    operations = [
        ProbeOperation(label="first"),
        ProbeOperation(label="reject", failure="reject"),
        ProbeOperation(label="never"),
    ]
    client = ProbeClient(_proposal(operations))

    result = asyncio.run(
        support.runtime(client, recipe=recipe, actions=ProbeActions()).run(
            scene, core_mindbuf.MindBuf(), model_name="test/fake"
        )
    )

    assert result.status == "failure"
    assert result.stage == observe.Stage.EXECUTION_PLAN
    assert result.error is not None
    assert result.error.kind == "validation_error"
    assert result.error.message == "reject rejected"
    assert result.error.metadata == {
        "index": 1,
        "call": "probe",
        "operation_id": recipe.derived_operations[1].op_id,
    }
    assert _VISITS == [("first", (), "probe"), ("reject", (), "probe")]
    assert [step.name for step in result.run_record.steps] == [
        "process_input",
        "intent",
        "execution_plan",
    ]
    assert result.scene == scene
    assert scene.blocks[0].generated == []
    assert len(client.requests) == 1


def test_clone_value_error_keeps_ordinary_mapping_without_operation_metadata() -> None:
    scene = domain.make_scene()
    recipe = ProbeRecipe()
    client = ProbeClient(_proposal(_operations("first")))
    actions = FailingAdmissibilityCloneActions()

    result = asyncio.run(
        support.runtime(client, recipe=recipe, actions=actions).run(
            scene,
            core_mindbuf.MindBuf(),
            model_name="test/fake",
        )
    )

    assert result.status == "failure"
    assert result.stage == observe.Stage.EXECUTION_PLAN
    assert result.error is not None
    assert result.error.kind == "validation_error"
    assert result.error.message == "admissibility clone failed"
    assert result.error.metadata == {}
    assert _VISITS == []


def test_stop_intent_never_enters_operation_admissibility() -> None:
    scene = domain.make_scene()
    recipe = StopProbeRecipe()
    client = ProbeClient(_proposal(_operations("never")))

    result = asyncio.run(
        support.runtime(client, recipe=recipe, actions=ProbeActions()).run(
            scene, core_mindbuf.MindBuf(), model_name="test/fake"
        )
    )

    assert result.status == "success"
    assert result.stage == observe.Stage.INTENT
    assert _VISITS == []
    assert client.requests == []


def test_unexpected_and_process_control_validator_exceptions_keep_their_mapping() -> None:
    scene = domain.make_scene()
    unexpected = [ProbeOperation(label="unexpected", failure="unexpected")]
    runtime = support.runtime(
        ProbeClient(_proposal(unexpected)),
        recipe=ProbeRecipe(),
        actions=ProbeActions(),
    )

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "failure"
    assert result.error is not None
    assert result.error.kind == "internal_error"
    assert "unexpected exploded" in result.error.message

    process = [ProbeOperation(label="process", failure="process")]
    process_runtime = support.runtime(
        ProbeClient(_proposal(process)),
        recipe=ProbeRecipe(),
        actions=ProbeActions(),
    )
    with pytest.raises(SystemExit, match="process stopped the process"):
        asyncio.run(process_runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))


def test_rebase_revalidates_every_operation_against_isolated_current_clones() -> None:
    scene = domain.make_scene()
    first_operations = [
        ProbeOperation(label="alpha-first"),
        ProbeOperation(label="alpha-second"),
    ]
    stale_operations = [
        ProbeOperation(label="beta-first"),
        ProbeOperation(
            label="beta-second",
            reject_when_populated=True,
        ),
    ]
    first_client = ProbeClient(
        _proposal(first_operations),
        controlled=True,
    )
    stale_client = ProbeClient(
        _proposal(stale_operations),
        controlled=True,
    )
    first_recipe = ProbeRecipe()
    stale_recipe = ProbeRecipe()
    first_actions = ProbeActions()
    stale_actions = ProbeActions()
    first_runtime = support.runtime(first_client, recipe=first_recipe, actions=first_actions)
    stale_runtime = support.runtime(stale_client, recipe=stale_recipe, actions=stale_actions)
    state: scene_state.SceneState[domain.DemoScene] = first_runtime.live_state(scene)

    first_result, stale_result = asyncio.run(
        support.interleave_two_writers(
            state,
            first_runtime,
            first_client,
            stale_runtime,
            stale_client,
        )
    )

    assert first_result.status == "success"
    assert stale_result.status == "failure"
    assert stale_result.stage == observe.Stage.COMMIT
    assert stale_result.error is not None
    assert stale_result.error.kind == "merge_conflict"
    assert stale_result.error.message == "operation_not_admissible"
    assert set(stale_result.error.metadata) == {
        "base_revision",
        "current_live_revision",
        "patch",
        "scene_metadata",
        "validation_error",
    }
    assert stale_result.error.metadata["scene_metadata"] == {
        "index": "application index",
        "validation_error": "application detail",
    }
    assert stale_result.error.metadata["current_live_revision"] == 1
    validation_error = stale_result.error.metadata["validation_error"]
    assert isinstance(validation_error, dict)
    assert set(validation_error) == {"kind", "message", "metadata"}
    assert validation_error["kind"] == "operation_admissibility"
    assert validation_error["metadata"] == {
        "index": 1,
        "call": "probe",
        "operation_id": stale_recipe.derived_operations[1].op_id,
    }
    beta_visits = [visit for visit in _VISITS if visit[0].startswith("beta")]
    assert beta_visits == [
        ("beta-first", (), "probe"),
        ("beta-second", (), "probe"),
        ("beta-first", ("alpha-first", "alpha-second"), "probe"),
        ("beta-second", ("alpha-first", "alpha-second"), "probe"),
    ]
    live_scene, identity = state.snapshot()
    assert identity.revision == 1
    assert live_scene.blocks[0].generated == ["alpha-first", "alpha-second"]
