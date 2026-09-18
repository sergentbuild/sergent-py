"""End-to-end behavior tests for the Sergent runtime.

The repo ships pytest but not pytest-asyncio, so each async scenario is driven
from a sync test via :func:`asyncio.run` or a small explicit-loop helper for the
interleave/cancel cases that need two coroutines parked at once.
"""

from __future__ import annotations

import asyncio
import typing

import pydantic
import demo_domain as domain
import runtime_test_support as support
import sergent_py_core.model_calls as model_calls
import sergent_py_core.errors as core_errors
import sergent_py_core.mindbuf as core_mindbuf
import sergent_py_core.model_calls as core_model_calls
import sergent_py_core.recipe as core_recipe
import sergent_py_core.scene as core_scene
import sergent_py_core.strict_model as core_strict_model
import sergent_py_core.target as core_target
import sergent_py_core.timing as core_timing
import sergent_py_runtime.execution.scene_state as scene_state
import sergent_py_runtime.lifecycle.observe as observe


def test_happy_path_plain_scene() -> None:
    scene = domain.make_scene(block_count=1)
    block_id = scene.blocks[0].block_id
    client = domain.StaticClient(["alpha"])
    runtime = support.runtime(client)

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "success"
    assert support.block_generated(result.scene, block_id) == ["note:alpha"]
    transition = result.run_record.scene
    assert transition is not None
    assert transition.revision_after == transition.revision_before + 1
    assert result.identity.revision == transition.revision_after
    assert support.request_ids(result) == ["req-intent", "req-plan"]
    assert len(client.requests) == 2
    # The original plain scene is untouched (engine clones before mutating).
    assert scene.blocks[0].generated == []

    record = result.run_record
    assert record.model_name == "test/fake"
    assert [request.model_name for request in client.requests] == ["test/fake", "test/fake"]
    assert record.outcome.status == "success"
    assert record.timing.is_closed()
    assert record.scene is not None
    assert record.scene.scene_id == result.identity.scene_id
    assert [step.name for step in record.steps] == [
        "process_input",
        "intent",
        "execution_plan",
        "patch",
        "commit",
    ]
    assert [step.status for step in record.steps] == ["success"] * 5

    intent_call = support.step(result, "intent").model_call
    assert intent_call is not None
    assert intent_call.proposal_schema.name == "DemoIntentProposal"
    assert intent_call.payloads.request.status == "captured"
    assert intent_call.payloads.raw_response is not None
    assert intent_call.payloads.parsed_json is not None
    assert intent_call.payloads.parsed_proposal is not None
    assert intent_call.attempts == []

    plan_call = support.step(result, "execution_plan").model_call
    assert plan_call is not None
    assert plan_call.proposal_schema.name == "PlanProposal"
    assert plan_call.payloads.parsed_json == {
        "operations": [{"call": "demo_append", "text": "note:alpha"}]
    }
    assert plan_call.payloads.parsed_proposal is not None
    assert plan_call.payloads.parsed_proposal.value_type == "PlanProposal"

    patch_output = support.output_value(result, "patch")
    assert patch_output["compiled_patch"]["operation_count"] == 1
    assert patch_output["compiled_patch"]["operation_call_names"] == ["demo_append"]


def test_pass_through_intent_skips_intent_provider_call_and_stage() -> None:
    scene = domain.make_scene(block_count=1)
    block_id = scene.blocks[0].block_id
    client = domain.StaticClient(["alpha"], model_backed_intent=False)
    observer = domain.CapturingObserver()
    runtime = support.runtime(client, observers=(observer,), recipe=domain.PassThroughDemoRecipe())

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "success"
    assert support.block_generated(result.scene, block_id) == ["note:alpha"]
    assert len(client.requests) == 1
    assert client.requests[0].messages[1].content == f"target={block_id}"
    assert support.request_ids(result) == ["req-plan"]
    plan_call = support.step(result, "execution_plan").model_call
    assert plan_call is not None
    assert plan_call.proposal_schema.name == "PlanProposal"
    assert plan_call.payloads.parsed_proposal is not None
    assert plan_call.payloads.parsed_proposal.value_type == "PlanProposal"

    stages = [snapshot.stage for snapshot in observer.snapshots]
    assert observe.Stage.INTENT_CALL.value not in stages
    assert observe.Stage.INTENT.value in stages
    assert stages.index(observe.Stage.INTENT.value) < stages.index(observe.Stage.PLAN_CALL.value)


def test_happy_path_live_scene_advances_revision() -> None:
    runtime = support.runtime(domain.StaticClient(["alpha"]))
    state: scene_state.SceneState[domain.DemoScene] = runtime.live_state(
        domain.make_scene(block_count=1)
    )

    first = asyncio.run(runtime.run(state, core_mindbuf.MindBuf(), model_name="test/fake"))
    assert first.status == "success"
    assert first.identity.revision == 1

    _, identity_after_first = state.snapshot()
    assert identity_after_first.revision == 1

    second = asyncio.run(runtime.run(state, core_mindbuf.MindBuf(), model_name="test/fake"))
    assert second.status == "success"
    # The second run saw the advanced revision and advanced it again.
    second_transition = second.run_record.scene
    assert second_transition is not None
    assert second_transition.revision_before == 1
    assert second.identity.revision == 2

    live_scene, _ = state.snapshot()
    block_id = live_scene.blocks[0].block_id
    assert support.block_generated(live_scene, block_id) == ["note:alpha", "note:alpha"]


def test_no_target_leaves_scene_unchanged() -> None:
    scene = domain.make_scene(block_count=1, selected=False)
    runtime = support.runtime(domain.StaticClient(["alpha"]))

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "failure"
    error = result.error
    assert error is not None
    assert error.kind == "no_target"
    assert error.message == "no target available"
    assert error.metadata == {"target_selection": {"status": "missing"}}
    assert result.terminal_message == error.message
    assert result.terminal_metadata == error.metadata
    assert result.run_record.steps[0].error is error
    recipe_error = domain.DemoRecipe.no_target_error
    assert error is not recipe_error
    assert error.metadata is not recipe_error.metadata
    assert error.metadata["target_selection"] is not recipe_error.metadata["target_selection"]
    assert result.stage == observe.Stage.STARTED
    assert support.request_ids(result) == []
    assert result.scene.blocks[0].generated == []


def test_model_error_is_contained() -> None:
    scene = domain.make_scene(block_count=1)
    runtime = support.runtime(
        domain.ErrorClient(
            model_calls.ModelError(
                "provider_error",
                "boom",
                retryable=True,
                identity=core_model_calls.ModelIdentity(
                    provider="fake",
                    model="fake-model",
                    sdk_package="fake-sdk",
                    sdk_version="1.2.3",
                ),
                attempts=[
                    core_model_calls.ModelAttemptRecord(
                        timing=core_timing.TimeSpan(
                            started_at="2026-01-01T00:00:00.000000Z",
                            finished_at="2026-01-01T00:00:00.004000Z",
                            duration_ms=4,
                        ),
                        status="failure",
                        retryable=True,
                        error=core_errors.RunError(kind="provider_error", message="boom"),
                    )
                ],
            )
        )
    )

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "failure"
    assert result.error is not None
    assert result.error.kind == "provider_error"
    assert result.error.metadata["retryable"] is True
    assert result.scene.blocks[0].generated == []
    assert support.request_ids(result) == []
    intent_call = support.step(result, "intent").model_call
    assert intent_call is not None
    assert intent_call.identity is not None
    assert intent_call.identity.provider == "fake"
    assert intent_call.identity.model == "fake-model"
    assert intent_call.identity.sdk_package == "fake-sdk"
    assert intent_call.identity.sdk_version == "1.2.3"
    # A response-less failure honestly carries no payload or usage facts.
    assert intent_call.payloads.raw_response is None
    assert intent_call.payloads.parsed_json is None
    assert intent_call.payloads.parsed_proposal is None
    assert intent_call.usage is None
    # The failure facts live on the last attempt, not mirrored on the call row.
    assert [attempt.status for attempt in intent_call.attempts] == ["failure"]
    assert intent_call.attempts[-1].error is not None
    assert intent_call.attempts[-1].error.kind == "provider_error"
    assert intent_call.attempts[-1].retryable is True


def test_unexpected_exception_records_internal_error_details() -> None:
    class ExplodingActions(domain.DemoActions):
        def select_target(self, scene: domain.DemoScene):
            del scene
            try:
                raise ValueError("root cause")
            except ValueError as exc:
                raise RuntimeError("selection exploded") from exc

    scene = domain.make_scene(block_count=1)
    runtime = support.runtime(domain.StaticClient(["alpha"]), actions=ExplodingActions())

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "failure"
    assert result.error is not None
    assert result.error.kind == "internal_error"
    assert "selection exploded" in result.error.message
    assert result.error.metadata["exception_type"] == "RuntimeError"
    assert result.error.metadata["current_step"] == "process_input"
    traceback_text = result.error.metadata["traceback"]
    assert isinstance(traceback_text, str)
    assert "Traceback" in traceback_text
    assert "selection exploded" in traceback_text
    assert result.error.metadata["cause_chain"] == [
        {"exception_type": "ValueError", "message": "root cause"}
    ]


def test_capture_error_does_not_abort_successful_run() -> None:
    class BadProposal(core_strict_model.StrictModel):
        """An app intent proposal whose Run Record capture fails."""

        broken: str = "value"

        @pydantic.field_serializer("broken")
        def _serialize_broken(self, _value: str) -> str:
            raise RuntimeError("capture exploded")

    class BadProposalClient(domain.StaticClient):
        """Returns raw data that validates into an uncapturable app model."""

        async def invoke(
            self, request: model_calls.ModelRequest
        ) -> tuple[model_calls.ModelResponse, dict[str, typing.Any]]:
            response, payload = await super().invoke(request)
            if len(self.requests) == 1:
                payload = {"broken": "value"}
                response = response.model_copy(
                    update={"raw_output": '{"broken":"value"}', "parsed_json": payload}
                )
            return response, payload

    class BadRecipe(core_recipe.SergentRecipe[domain.DemoScene, BadProposal, domain.DemoIntent]):
        intent_proposal_type = BadProposal
        operation_registry = domain.DemoRecipe.operation_registry
        no_target_error = domain.DemoRecipe.no_target_error

        def build_intent_request(
            self,
            scene: domain.DemoScene,
            mindbuf: core_mindbuf.MindBuf,
            target: core_target.Target,
            model_name: str,
            proposal_schema: model_calls.ProposalSchema,
        ) -> model_calls.ModelRequest:
            return domain.DemoRecipe().build_intent_request(
                scene, mindbuf, target, model_name, proposal_schema
            )

        def derive_intent(
            self,
            _scene: domain.DemoScene,
            identity: core_scene.SceneIdentity,
            _target: core_target.Target,
            _intent_proposal: BadProposal,
        ) -> domain.DemoIntent:
            return domain.DemoIntent(
                base_scene_id=identity.scene_id,
                base_revision=identity.revision,
            )

        def build_plan_request(  # noqa: PLR0913 - exact Recipe override.
            self,
            scene: domain.DemoScene,
            target: core_target.Target,
            intent: domain.DemoIntent,
            mindbuf: core_mindbuf.MindBuf,
            model_name: str,
            proposal_schema: model_calls.ProposalSchema,
        ) -> model_calls.ModelRequest:
            return domain.DemoRecipe().build_plan_request(
                scene, target, intent, mindbuf, model_name, proposal_schema
            )

    scene = domain.make_scene(block_count=1)
    block_id = scene.blocks[0].block_id
    runtime = support.runtime(BadProposalClient(["alpha"]), recipe=BadRecipe())

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "success"
    assert support.block_generated(result.scene, block_id) == ["note:alpha"]
    intent_call = support.step(result, "intent").model_call
    assert intent_call is not None
    proposal = intent_call.payloads.parsed_proposal
    assert proposal is not None
    assert proposal.status == "capture_error"
    assert proposal.error is not None
    assert proposal.error.kind == "capture_error"


def test_dry_run_verification_failure() -> None:
    scene = domain.make_scene(block_count=1)
    runtime = support.runtime(domain.StaticClient(["alpha"]), actions=domain.TamperingActions())

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "failure"
    assert result.error is not None
    assert result.error.kind == "validation_error"
    assert "dry-run verification failed" in result.error.message
    assert result.stage == observe.Stage.DRY_RUN
    assert scene.blocks[0].generated == []
    patch_step = support.step(result, "patch")
    assert patch_step.status == "failure"
    assert patch_step.error is not None
    assert patch_step.error.metadata["verification_issues"] == ["target block text changed"]


def test_stale_patch_on_concurrent_commit() -> None:
    client_a = domain.ControlledClient(["alpha"])
    client_b = domain.ControlledClient(["beta"])
    runtime_a = support.runtime(client_a)
    runtime_b = support.runtime(client_b)
    state: scene_state.SceneState[domain.DemoScene] = runtime_a.live_state(
        domain.make_scene(block_count=1)
    )
    block_id = state.snapshot()[0].blocks[0].block_id

    result_a, result_b = asyncio.run(
        support.interleave_two_writers(state, runtime_a, client_a, runtime_b, client_b)
    )

    assert result_a.status == "success"
    assert result_b.status == "failure"
    assert result_b.error is not None
    assert result_b.error.kind == "stale_patch"
    assert result_b.error.metadata == {"base_revision": 0, "current_revision": 1}
    commit_step = support.step(result_b, "commit")
    assert commit_step.status == "failure"
    assert commit_step.error is not None
    assert commit_step.error.kind == "stale_patch"
    assert commit_step.error.metadata["current_revision"] == 1

    # The live scene reflects only A's commit; B never overwrote it.
    live_scene, identity = state.snapshot()
    assert identity.revision == 1
    assert support.block_generated(live_scene, block_id) == ["note:alpha"]


def test_progress_is_sanitized_and_ordered() -> None:
    observer = domain.CapturingObserver()
    scene = domain.make_scene(block_count=1)
    runtime = support.runtime(domain.StaticClient(["alpha"]), observers=(observer,))

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))
    assert result.status == "success"

    assert observer.snapshots, "observer received no progress"
    for snapshot in observer.snapshots:
        assert isinstance(snapshot, observe.ProgressSnapshot)
        assert set(snapshot.model_dump().keys()) == {
            "run_id",
            "scene_id",
            "stage",
            "status",
            "revision",
        }
        # No prompt/document/output text leaks into the snapshot.
        dumped = snapshot.model_dump_json()
        assert "demo" not in dumped  # system prompt content
        assert "note:" not in dumped  # generated body
        assert "block-" not in dumped  # document text

    stages = [snapshot.stage for snapshot in observer.snapshots]
    positions = [stages.index(stage.value) for stage in observe.Stage]
    assert positions == sorted(positions)


def test_model_error_on_plan_call_keeps_intent_provider_run() -> None:
    # A failure at the SECOND model call must still record the runs gathered so
    # far -- here the successful intent call -- so the Run Record survives a
    # plan-stage provider error. Contrast test 4, where the intent call itself
    # fails and no model-call usage is recorded.
    class PlanErrorClient(domain.StaticClient):
        async def invoke(
            self, request: model_calls.ModelRequest
        ) -> tuple[model_calls.ModelResponse, dict[str, object]]:
            if len(self.requests) == 1:
                self.requests.append(request)
                raise model_calls.ModelError("provider_error", "boom on plan")
            return await super().invoke(request)

    scene = domain.make_scene(block_count=1)
    block_id = scene.blocks[0].block_id
    client = PlanErrorClient(["alpha"])
    runtime = support.runtime(client)

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "failure"
    assert result.error is not None
    assert result.error.kind == "provider_error"
    assert result.stage == observe.Stage.PLAN_CALL
    # Both calls were attempted; only the intent call recorded usage in the Run Record.
    assert len(client.requests) == 2
    assert support.request_ids(result) == ["req-intent"]
    assert support.block_generated(result.scene, block_id) == []
    # A bare error supplies no provider attempt facts for the runtime to record.
    plan_call = support.step(result, "execution_plan").model_call
    assert plan_call is not None
    assert plan_call.attempts == []
