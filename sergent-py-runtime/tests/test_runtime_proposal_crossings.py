"""Runtime-owned Intent validation and Plan decoding tests."""

from __future__ import annotations

import asyncio
import json
import typing

import pytest
import demo_domain as domain
import runtime_test_support as support
import sergent_py_core.mindbuf as core_mindbuf
import sergent_py_core.model_calls as core_model_calls
import sergent_py_core.plan as core_plan
import sergent_py_core.proposals.schema as core_proposal_schema
import sergent_py_core.scene as core_scene
import sergent_py_core.strict_model as core_strict_model
import sergent_py_core.target as core_target
import sergent_py_core.timing as core_timing
import sergent_py_runtime.lifecycle.observe as observe
import sergent_py_runtime.proposals.intent_proposals as runtime_intent_proposals


class _RawPayloadClient:
    def __init__(self, outputs: list[dict[str, typing.Any]]) -> None:
        self.outputs = list(outputs)
        self.requests: list[core_model_calls.ModelRequest] = []

    async def invoke(
        self, request: core_model_calls.ModelRequest
    ) -> tuple[core_model_calls.ModelResponse, dict[str, typing.Any]]:
        self.requests.append(request)
        payload = self.outputs.pop(0)
        attempt = core_model_calls.ModelAttemptRecord(
            timing=core_timing.TimeSpan(
                started_at="2026-01-01T00:00:00.000000Z",
                finished_at="2026-01-01T00:00:00.001000Z",
                duration_ms=1,
            ),
            status="success",
        )
        response = core_model_calls.ModelResponse(
            identity=core_model_calls.ModelIdentity(
                provider="fake",
                model="fake-model",
                sdk_package="fake-sdk",
                sdk_version="1.0",
            ),
            raw_output=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            attempts=[attempt],
            usage=core_model_calls.CallUsage(
                latency_ms=1,
                tokens={"input": 2, "output": 3},
                request_id=f"req-raw-{len(self.requests)}",
            ),
        ).model_copy(update={"parsed_json": payload})
        return response, payload


def test_malformed_intent_payload_closes_call_and_fails_the_crossing() -> None:
    scene = domain.make_scene(block_count=1)
    client = _RawPayloadClient([{"unexpected": True}])

    result = asyncio.run(
        support.runtime(client).run(scene, core_mindbuf.MindBuf(), model_name="test/fake")
    )

    assert result.status == "failure"
    assert result.stage == observe.Stage.INTENT_CALL
    assert result.error is not None
    assert result.error.kind == "schema_validation_failed"
    assert "DemoIntentProposal" in result.error.message
    assert "unexpected" in result.error.message
    assert result.scene == scene
    assert scene.blocks[0].generated == []
    intent_step = support.step(result, "intent")
    assert intent_step.status == "failure"
    assert intent_step.error is result.error
    call = intent_step.model_call
    assert call is not None
    assert call.proposal_schema.name == "DemoIntentProposal"
    assert call.identity is not None
    assert call.identity.provider == "fake"
    assert call.usage is not None
    assert call.usage.request_id == "req-raw-1"
    assert [attempt.status for attempt in call.attempts] == ["success"]
    assert call.payloads.request.status == "captured"
    assert call.payloads.raw_response == '{"unexpected":true}'
    assert call.payloads.parsed_json == {"unexpected": True}
    assert call.payloads.parsed_proposal is None


def test_malformed_plan_payload_closes_call_and_fails_the_crossing() -> None:
    scene = domain.make_scene(block_count=1)
    client = _RawPayloadClient([{}, {"operations": [{"call": "missing"}]}])

    result = asyncio.run(
        support.runtime(client).run(scene, core_mindbuf.MindBuf(), model_name="test/fake")
    )

    assert result.status == "failure"
    assert result.stage == observe.Stage.PLAN_CALL
    assert result.error is not None
    assert result.error.kind == "schema_validation_failed"
    assert "operation 0 (call='missing')" in result.error.message
    assert "unknown operation call" in result.error.message
    assert result.scene == scene
    assert scene.blocks[0].generated == []
    plan_step = support.step(result, "execution_plan")
    assert plan_step.status == "failure"
    assert plan_step.error is result.error
    call = plan_step.model_call
    assert call is not None
    assert call.proposal_schema.name == "PlanProposal"
    assert call.identity is not None
    assert call.identity.provider == "fake"
    assert call.usage is not None
    assert call.usage.request_id == "req-raw-2"
    assert [attempt.status for attempt in call.attempts] == ["success"]
    assert call.payloads.request.status == "captured"
    assert call.payloads.raw_response == '{"operations":[{"call":"missing"}]}'
    assert call.payloads.parsed_json == {"operations": [{"call": "missing"}]}
    assert call.payloads.parsed_proposal is None


def test_recipe_hook_value_error_stays_a_validation_error() -> None:
    class RejectingRecipe(domain.DemoRecipe):
        def derive_plan(
            self,
            _scene: domain.DemoScene,
            _identity: core_scene.SceneIdentity,
            _target: core_target.Target,
            _intent: domain.DemoIntent,
            _plan_proposal: core_plan.PlanProposal,
        ) -> core_plan.ExecutionPlan:
            raise ValueError("recipe rejected the typed Plan proposal")

    scene = domain.make_scene(block_count=1)
    client = _RawPayloadClient(
        [{}, {"operations": [{"call": "demo_append", "text": "note:alpha"}]}]
    )

    result = asyncio.run(
        support.runtime(client, recipe=RejectingRecipe()).run(
            scene, core_mindbuf.MindBuf(), model_name="test/fake"
        )
    )

    assert result.status == "failure"
    assert result.stage == observe.Stage.EXECUTION_PLAN
    assert result.error is not None
    assert result.error.kind == "validation_error"
    assert result.error.message == "recipe rejected the typed Plan proposal"
    assert result.scene == scene


@pytest.mark.parametrize(
    ("bad_maximum", "error_type"),
    (
        (0, ValueError),
        (-1, ValueError),
        (True, TypeError),
        (False, TypeError),
        (1.5, TypeError),
        ("1", TypeError),
    ),
)
def test_runtime_construction_rejects_invalid_max_operations(
    bad_maximum: typing.Any,
    error_type: type[Exception],
) -> None:
    recipe = domain.DemoRecipe()
    recipe.max_operations = bad_maximum

    with pytest.raises(error_type, match="max_operations"):
        support.runtime(domain.StaticClient(), recipe=recipe)


def test_successful_crossings_deliver_typed_proposals_to_recipe_hooks() -> None:
    class CapturingRecipe(domain.DemoRecipe):
        def __init__(self) -> None:
            self.intent_proposal: domain.DemoIntentProposal | None = None
            self.plan_proposal: core_plan.PlanProposal | None = None

        def derive_intent(
            self,
            scene: domain.DemoScene,
            identity: core_scene.SceneIdentity,
            target: core_target.Target,
            intent_proposal: domain.DemoIntentProposal,
        ) -> domain.DemoIntent:
            self.intent_proposal = intent_proposal
            return super().derive_intent(scene, identity, target, intent_proposal)

        def derive_plan(
            self,
            scene: domain.DemoScene,
            identity: core_scene.SceneIdentity,
            target: core_target.Target,
            intent: domain.DemoIntent,
            plan_proposal: core_plan.PlanProposal,
        ) -> core_plan.ExecutionPlan:
            self.plan_proposal = plan_proposal
            return super().derive_plan(scene, identity, target, intent, plan_proposal)

    recipe = CapturingRecipe()
    result = asyncio.run(
        support.runtime(domain.StaticClient(["alpha"]), recipe=recipe).run(
            domain.make_scene(), core_mindbuf.MindBuf(), model_name="test/fake"
        )
    )

    assert result.status == "success"
    assert type(recipe.intent_proposal) is domain.DemoIntentProposal
    assert recipe.intent_proposal.model_dump() == {}
    assert type(recipe.plan_proposal) is core_plan.PlanProposal
    assert recipe.plan_proposal is not None
    operation = recipe.plan_proposal.operations[0]
    assert isinstance(operation, domain.DemoOperation)
    assert operation.text == "note:alpha"


def test_runtime_construction_derives_no_schema_for_pass_through_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_derivation(
        proposal_type: type[typing.Any], /
    ) -> core_model_calls.ProposalSchema:
        raise AssertionError(f"unexpected schema derivation for {proposal_type.__name__}")

    monkeypatch.setattr(
        core_proposal_schema,
        "derive_proposal_schema",
        unexpected_derivation,
    )

    support.runtime(
        domain.StaticClient(model_backed_intent=False),
        recipe=domain.PassThroughDemoRecipe(),
    )


def test_runtime_construction_adds_recipe_context_to_intent_schema_failure() -> None:
    class UnsupportedIntentProposal(core_strict_model.StrictModel):
        values: dict[str, str]

    recipe = domain.DemoRecipe()
    mutable_recipe: typing.Any = recipe
    mutable_recipe.intent_proposal_type = UnsupportedIntentProposal

    with pytest.raises(
        ValueError,
        match=r"DemoRecipe Intent proposal UnsupportedIntentProposal: .* schema at /",
    ):
        support.runtime(domain.StaticClient(), recipe=recipe)


def test_runtime_construction_rejects_plan_bound_without_registry() -> None:
    recipe = domain.PassThroughDemoRecipe()
    recipe.operation_registry = None
    recipe.max_operations = 1

    with pytest.raises(ValueError, match="max_operations requires operation_registry"):
        support.runtime(domain.StaticClient(model_backed_intent=False), recipe=recipe)


def test_runtime_captures_recipe_types_registry_bound_and_schema_objects() -> None:
    recipe = domain.DemoRecipe()
    recipe.max_operations = 2
    client = domain.StaticClient(["alpha", "beta"])
    runtime = support.runtime(client, recipe=recipe)

    mutable_recipe: typing.Any = recipe
    mutable_recipe.intent_proposal_type = runtime_intent_proposals.IntentProposal_PassThrough
    mutable_recipe.operation_registry = None
    mutable_recipe.max_operations = 1

    first = asyncio.run(
        runtime.run(domain.make_scene(), core_mindbuf.MindBuf(), model_name="test/fake")
    )
    second = asyncio.run(
        runtime.run(domain.make_scene(), core_mindbuf.MindBuf(), model_name="test/fake")
    )

    assert (first.status, second.status) == ("success", "success")
    assert len(client.requests) == 4
    first_intent, first_plan, second_intent, second_plan = client.requests
    assert first_intent.proposal_schema.name == "DemoIntentProposal"
    assert first_intent.proposal_schema is second_intent.proposal_schema
    assert first_plan.proposal_schema.name == "PlanProposal"
    assert first_plan.proposal_schema is second_plan.proposal_schema
    operations_schema = first_plan.proposal_schema.json_schema["properties"]["operations"]
    assert operations_schema["maxItems"] == 2
    first_plan_call = support.step(first, "execution_plan").model_call
    assert first_plan_call is not None
    assert first_plan_call.proposal_schema is first_plan.proposal_schema


def test_intent_builder_must_return_the_exact_cached_schema() -> None:
    class CopyingIntentSchemaRecipe(domain.DemoRecipe):
        def build_intent_request(
            self,
            _scene: domain.DemoScene,
            _mindbuf: core_mindbuf.MindBuf,
            target: core_target.Target,
            model_name: str,
            proposal_schema: core_model_calls.ProposalSchema,
        ) -> core_model_calls.ModelRequest:
            return domain._request(target, model_name, proposal_schema.model_copy(deep=True))

    client = domain.StaticClient()
    result = asyncio.run(
        support.runtime(client, recipe=CopyingIntentSchemaRecipe()).run(
            domain.make_scene(), core_mindbuf.MindBuf(), model_name="test/fake"
        )
    )

    assert result.status == "failure"
    assert result.error is not None
    assert "build_intent_request must return the provided schema object" in result.error.message
    assert client.requests == []
    assert support.step(result, "intent").model_call is None


def test_plan_builder_must_return_the_exact_cached_schema() -> None:
    class CopyingPlanSchemaRecipe(domain.PassThroughDemoRecipe):
        def build_plan_request(
            self,
            _scene: domain.DemoScene,
            target: core_target.Target,
            _intent: domain.DemoIntent,
            _mindbuf: core_mindbuf.MindBuf,
            model_name: str,
            proposal_schema: core_model_calls.ProposalSchema,
        ) -> core_model_calls.ModelRequest:
            return domain._request(target, model_name, proposal_schema.model_copy(deep=True))

    client = domain.StaticClient(model_backed_intent=False)
    result = asyncio.run(
        support.runtime(client, recipe=CopyingPlanSchemaRecipe()).run(
            domain.make_scene(), core_mindbuf.MindBuf(), model_name="test/fake"
        )
    )

    assert result.status == "failure"
    assert result.error is not None
    assert "build_plan_request must return the provided schema object" in result.error.message
    assert client.requests == []
    assert support.step(result, "execution_plan").model_call is None


def test_intent_only_continue_fails_before_plan_builder_or_provider() -> None:
    recipe = domain.PassThroughDemoRecipe()
    recipe.operation_registry = None
    client = domain.StaticClient(model_backed_intent=False)
    result = asyncio.run(
        support.runtime(client, recipe=recipe).run(
            domain.make_scene(), core_mindbuf.MindBuf(), model_name="test/fake"
        )
    )

    assert result.status == "failure"
    assert result.error is not None
    assert (
        result.error.message == "AssertionError: continue-flow recipe requires operation_registry"
    )
    assert client.requests == []
    assert support.step(result, "execution_plan").model_call is None
