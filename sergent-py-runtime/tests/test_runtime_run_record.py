from __future__ import annotations

import asyncio
import base64
import typing

import pydantic
import pytest
import demo_domain as domain
import runtime_test_support as support
import sergent_py_core.errors as core_errors
import sergent_py_core.mindbuf as core_mindbuf
import sergent_py_core.model_calls as core_model_calls
import sergent_py_core.operation as core_operation
import sergent_py_core.plan as core_plan
import sergent_py_core.recipe as core_recipe
import sergent_py_core.scene as core_scene
import sergent_py_core.strict_model as core_strict_model
import sergent_py_core.target as core_target
import sergent_py_core.timing as core_timing
import sergent_py_core.model_calls as model_calls
import sergent_py_runtime.execution.engine as engine
import sergent_py_runtime.run_record.run_capture as run_capture

PNG_BYTES = b"\x89PNG\r\n\x1a\nabc"
PNG_BASE64 = base64.b64encode(PNG_BYTES).decode("ascii")


def test_run_record_preserves_raw_output_sdk_and_attempts() -> None:
    class RetryIntentClient(domain.StaticClient):
        async def invoke(
            self, request: model_calls.ModelRequest
        ) -> tuple[model_calls.ModelResponse, dict[str, typing.Any]]:
            if not self.requests:
                self.requests.append(request)
                payload: dict[str, typing.Any] = {}
                response = model_calls.ModelResponse(
                    identity=core_model_calls.ModelIdentity(
                        provider="fake",
                        model="fake-model",
                        sdk_package="fake-sdk",
                        sdk_version="1.2.3",
                    ),
                    raw_output='{"raw":"value"}',
                    attempts=[
                        core_model_calls.ModelAttemptRecord(
                            timing=core_timing.TimeSpan(
                                started_at="2026-01-01T00:00:00.000000Z",
                                finished_at="2026-01-01T00:00:00.001000Z",
                                duration_ms=1,
                            ),
                            status="failure",
                            error=core_errors.RunError(kind="timeout", message="first try"),
                        ),
                        core_model_calls.ModelAttemptRecord(
                            timing=core_timing.TimeSpan(
                                started_at="2026-01-01T00:00:00.002000Z",
                                finished_at="2026-01-01T00:00:00.003000Z",
                                duration_ms=1,
                            ),
                            status="success",
                        ),
                    ],
                    usage=core_model_calls.CallUsage(latency_ms=9, request_id="req-retry"),
                )
                return response.model_copy(update={"parsed_json": payload}), payload
            return await super().invoke(request)

    scene = domain.make_scene(block_count=1)
    client = RetryIntentClient(["alpha"])
    runtime = support.runtime(client)

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))

    intent_call = support.step(result, "intent").model_call
    assert intent_call is not None
    assert intent_call.proposal_schema.name == "DemoIntentProposal"
    assert intent_call.proposal_schema is client.requests[0].proposal_schema
    assert intent_call.payloads.raw_response == '{"raw":"value"}'
    assert intent_call.payloads.parsed_json == {}
    assert intent_call.identity is not None
    assert intent_call.identity.sdk_package == "fake-sdk"
    assert intent_call.identity.sdk_version == "1.2.3"
    assert intent_call.usage is not None
    assert intent_call.usage.latency_ms == 9
    assert intent_call.usage.request_id == "req-retry"
    assert [attempt.status for attempt in intent_call.attempts] == ["failure", "success"]
    first_attempt_error = intent_call.attempts[0].error
    assert first_attempt_error is not None
    assert first_attempt_error.kind == "timeout"
    captured_request = intent_call.payloads.request.value
    assert isinstance(captured_request, dict)
    assert set(captured_request) == {"model_name", "messages", "model_settings"}
    assert captured_request["model_settings"] == domain.DemoModelSettings().model_dump(mode="json")

    process_output = support.output_value(result, "process_input")
    assert process_output["selected_target"]["target_id"] == scene.blocks[0].block_id
    intent_output = support.output_value(result, "intent")
    assert "target_id" not in intent_output["derived_intent"]
    plan_step = support.output_value(result, "execution_plan")
    plan_capture = plan_step["derived_execution_plan"]
    plan_operation = plan_capture["steps"][0]
    patch_summary = support.output_value(result, "patch")["compiled_patch"]
    patch_operation = patch_summary["operations"][0]["value"]
    assert "plan_id" not in plan_capture
    assert "intent_id" not in plan_capture
    assert plan_capture["base"] == {"scene_id": scene.scene_id, "revision": 0}
    assert set(plan_capture) == {"base", "steps"}
    assert "patch_id" not in patch_summary
    assert "op_id" not in plan_operation
    assert "run_id" not in plan_operation
    assert "target_id" not in plan_operation
    assert "target_id" not in patch_operation
    assert patch_summary["operation_ids"] == patch_summary["operation_trace_ids"]
    assert patch_summary["operation_call_names"] == ["demo_append"]
    assert result.run_record.run_id.startswith("run_")


def test_compiled_stale_patch_preserves_error_and_patch_evidence() -> None:
    class StalePatchRecipe(domain.DemoRecipe):
        def compile_patch(self, plan: core_plan.ExecutionPlan) -> domain.DemoPatch:
            patch = super().compile_patch(plan)
            return patch.model_copy(
                update={"base": patch.base.model_copy(update={"revision": patch.base.revision + 1})}
            )

    scene = domain.make_scene(block_count=1)
    runtime = engine.SergentRuntime(
        domain.StaticClient(["alpha"]),
        domain.DemoActions(),
        StalePatchRecipe(),
    )

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "failure"
    assert result.error is not None
    assert result.error.kind == "stale_patch"
    assert result.error.metadata == {"base_revision": 1, "current_revision": 0}
    patch_output = support.output_value(result, "patch")
    patch_summary = patch_output["compiled_patch"]
    assert isinstance(patch_summary, dict)
    base = patch_summary["base"]
    assert isinstance(base, dict)
    assert base["revision"] == 1
    assert patch_summary["operation_count"] == 1
    patch_step = support.step(result, "patch")
    assert patch_step.status == "failure"
    assert patch_step.error == result.error
    assert patch_output["patch_validation"] == {"status": "failure"}


def test_terminal_record_survives_step_output_capture_error() -> None:
    class UncapturableStopIntent(core_strict_model.StrictModel):
        flow: typing.Literal["stop"] = "stop"
        broken: str = "value"

        @pydantic.field_serializer("broken")
        def _serialize_broken(self, _value: str) -> str:
            raise RuntimeError("intent capture exploded")

        def terminal_message(self) -> str:
            return "independent terminal"

        def terminal_metadata(self) -> dict[str, object]:
            return {"decision": "done"}

    class UncapturableStopRecipe(
        core_recipe.SergentRecipe[
            domain.DemoScene,
            domain.DemoIntentProposal,
            UncapturableStopIntent,
        ]
    ):
        intent_proposal_type = domain.DemoIntentProposal
        no_target_error = core_errors.RunError(kind="no_target", message="no target available")

        def build_intent_request(
            self,
            _scene: domain.DemoScene,
            _mindbuf: core_mindbuf.MindBuf,
            target: core_target.Target,
            model_name: str,
            proposal_schema: model_calls.ProposalSchema,
        ) -> model_calls.ModelRequest:
            return domain._request(target, model_name, proposal_schema)

        def derive_intent(
            self,
            _scene: domain.DemoScene,
            _identity: core_scene.SceneIdentity,
            _target: core_target.Target,
            _intent_proposal: domain.DemoIntentProposal,
        ) -> UncapturableStopIntent:
            return UncapturableStopIntent()

    scene = domain.make_scene(block_count=1)
    runtime = engine.SergentRuntime(
        domain.StaticClient(["alpha"]),
        domain.DemoActions(),
        UncapturableStopRecipe(),
    )

    result = asyncio.run(runtime.run(scene, core_mindbuf.MindBuf(), model_name="test/fake"))

    assert result.status == "success"
    intent_step = support.step(result, "intent")
    intent_output = intent_step.output
    assert intent_output is not None
    assert intent_output.status == "capture_error"
    terminal = result.run_record.outcome.terminal
    assert terminal is not None
    assert terminal.message.status == "captured"
    assert terminal.message.value == "independent terminal"
    assert terminal.metadata.status == "captured"
    assert terminal.metadata.value == {"decision": "done"}
    # The step capture failure is recorded in place on the step output slot,
    # isolated from the cleanly-captured terminal.
    assert intent_output.error is not None
    assert intent_output.error.kind == "capture_error"
    assert terminal.message.error is None
    assert terminal.metadata.error is None


def test_capture_preserves_operation_domain_fields_under_base_typed_field() -> None:
    """A base-typed ``list[Operation]`` proposal must capture subclass fields.

    Pydantic serializes a base-typed field with the base schema, dropping the
    operation's own domain fields (call args). The Run Record capture must keep them
    so forensics can read the proposed operation from ``parsed_proposal`` without
    falling back to ``raw_response``.
    """

    class BaseTypedProposal(core_strict_model.StrictModel):
        operations: list[core_operation.Operation]

    proposal = BaseTypedProposal(operations=[domain.DemoOperation(text="hello")])

    captured = run_capture.capture_value(proposal)

    assert captured.status == "captured"
    assert captured.value == {"operations": [{"call": "demo_append", "text": "hello"}]}
    assert captured.error is None


def test_capture_falls_back_when_forward_ref_model_is_never_rebuilt() -> None:
    """An unrebuilt forward-ref model must capture through the plain dump.

    Live proposals arrive as raw JSON validated through the outer schema, so a
    nested class with an unresolved self-referential forward reference keeps
    pydantic's mock serializer and the richer dump raises TypeError. The capture
    must fall back to the static-schema dump, not lose the value.
    """

    class Node(core_strict_model.StrictModel):
        title: str
        subgraph: Graph | None = None

    class Graph(core_strict_model.StrictModel):
        nodes: list[Node]

    graph = Graph.model_validate({"nodes": [{"title": "leaf", "subgraph": None}]})
    with pytest.raises(TypeError, match="MockValSer"):
        graph.model_dump(mode="json", serialize_as_any=True)

    captured = run_capture.capture_value(graph)

    assert captured.status == "captured"
    assert captured.value == {"nodes": [{"title": "leaf", "subgraph": None}]}
    assert captured.error is None


def test_capture_records_image_parts_without_base64_payload() -> None:
    request = model_calls.ModelRequest(
        model_name="openai/gpt",
        messages=[
            model_calls.ModelMessage(
                role="user",
                content="look",
                images=[model_calls.ImagePart(data_base64=PNG_BASE64)],
            )
        ],
        model_settings=domain.DemoModelSettings(),
        proposal_schema=model_calls.ProposalSchema(
            name="ImageProposal",
            json_schema={"type": "object"},
        ),
    )

    captured = run_capture.capture_value(request)

    assert captured.status == "captured"
    captured_request = captured.value
    assert isinstance(captured_request, dict)
    assert captured_request["messages"][0]["images"] == [
        {"media_type": "image/png", "bytes": len(PNG_BYTES)}
    ]
    assert "data_base64" not in repr(captured.value)
    assert PNG_BASE64 not in repr(captured.value)
    assert captured.error is None


def test_exception_format_with_and_without_message() -> None:
    assert run_capture._format_exception(ValueError("boom")) == "ValueError: boom"
    assert run_capture._format_exception(ValueError()) == "ValueError"
