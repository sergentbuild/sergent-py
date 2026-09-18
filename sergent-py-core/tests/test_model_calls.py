from __future__ import annotations

import base64
import math

import pytest

import sergent_py_core.errors as errors
import sergent_py_core.model_calls as model_calls
import sergent_py_core.strict_model as strict_model
import sergent_py_core.timing as timing

PNG_BYTES = b"\x89PNG\r\n\x1a\nabc"
PNG_BASE64 = base64.b64encode(PNG_BYTES).decode("ascii")


@pytest.mark.parametrize("name", ("A", "proposal_name-1", "x" * 64))
def test_proposal_schema_accepts_exact_stable_names(name: str) -> None:
    schema = model_calls.ProposalSchema(name=name, json_schema={"type": "object"})
    assert schema.name == name


@pytest.mark.parametrize("name", ("", "x" * 65, "has space", "non_ascii_\u00e9"))
def test_proposal_schema_rejects_invalid_stable_names(name: str) -> None:
    with pytest.raises(ValueError):
        model_calls.ProposalSchema(name=name, json_schema={"type": "object"})


@pytest.mark.parametrize(
    "json_schema",
    (
        {"value": (1, 2)},
        {"value": {1, 2}},
        {"value": math.nan},
        {"value": object()},
    ),
)
def test_proposal_schema_requires_exact_json_data(
    json_schema: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="JSON-compatible"):
        model_calls.ProposalSchema(name="Proposal", json_schema=json_schema)


def _closed_span() -> timing.TimeSpan:
    return timing.TimeSpan(
        started_at="2026-04-26T00:00:00Z",
        finished_at="2026-04-26T00:00:01Z",
        duration_ms=1000,
    )


def _endpoint_identity() -> model_calls.ModelIdentity:
    return model_calls.ModelIdentity(
        provider="openai",
        model="gpt-5.5",
        sdk_package="openai",
        sdk_version="9.9.9",
    )


def test_model_identity_preserves_exact_nonblank_endpoint_evidence() -> None:
    identity = model_calls.ModelIdentity(provider=" openai ", model=" native/model ")

    assert identity.provider == " openai "
    assert identity.model == " native/model "

    with pytest.raises(ValueError):
        model_calls.ModelIdentity(provider="openai", model="   ")


def test_image_part_validates_png_base64_and_reports_byte_count() -> None:
    image = model_calls.ImagePart(data_base64=f" {PNG_BASE64} ")

    assert image.media_type == "image/png"
    assert image.data_base64 == PNG_BASE64
    assert image.decoded_byte_count() == len(PNG_BYTES)
    assert image.decoded_bytes() == PNG_BYTES


def test_image_part_rejects_bad_base64_non_png_and_large_bytes() -> None:
    with pytest.raises(ValueError, match="valid base64"):
        model_calls.ImagePart(data_base64="not base64")

    with pytest.raises(ValueError, match="PNG"):
        model_calls.ImagePart(data_base64=base64.b64encode(b"not png").decode("ascii"))

    too_large = b"\x89PNG\r\n\x1a\n" + (b"x" * 1_000_000)
    with pytest.raises(ValueError, match="decoded image bytes"):
        model_calls.ImagePart(data_base64=base64.b64encode(too_large).decode("ascii"))


def test_model_message_allows_images_only_on_user_messages() -> None:
    image = model_calls.ImagePart(data_base64=PNG_BASE64)
    message = model_calls.ModelMessage(role="user", content="look", images=[image])

    assert message.images == [image]
    with pytest.raises(ValueError, match="only on user messages"):
        model_calls.ModelMessage(role="system", content="look", images=[image])


def test_model_request_carries_full_model_name() -> None:
    proposal_schema = model_calls.ProposalSchema(
        name="PlanProposal",
        json_schema={"type": "object"},
    )
    request = model_calls.ModelRequest(
        model_name="openai/gpt-5.6-sol",
        messages=[model_calls.ModelMessage(role="user", content="plan")],
        model_settings=strict_model.StrictModel(),
        proposal_schema=proposal_schema,
    )

    assert request.model_name == "openai/gpt-5.6-sol"
    assert request.proposal_schema is proposal_schema
    assert set(request.model_dump()) == {
        "model_name",
        "messages",
        "model_settings",
        "proposal_schema",
    }


def test_model_attempt_record_requires_closed_timing() -> None:
    with pytest.raises(ValueError, match="closed span"):
        model_calls.ModelAttemptRecord(timing=timing.TimeSpan.begin(), status="failure")

    attempt = model_calls.ModelAttemptRecord(timing=_closed_span(), status="success")
    assert attempt.timing.is_closed()
    assert set(attempt.model_dump()) == {"timing", "status", "retryable", "error"}


def test_model_error_reads_call_facts_through_held_response() -> None:
    attempt = model_calls.ModelAttemptRecord(
        timing=_closed_span(),
        status="failure",
        retryable=True,
        error=errors.RunError(kind="timeout", message="slow"),
    )
    response = model_calls.ModelResponse(
        identity=_endpoint_identity(),
        raw_output='{"ok":',
        attempts=[attempt],
        usage=model_calls.CallUsage(latency_ms=1000),
    )
    err = model_calls.ModelError(
        "invalid_response",
        "bad json",
        retryable=True,
        response=response,
    )

    assert err.retryable is True
    assert err.response is not None
    assert err.response is response
    assert err.response.raw_output == '{"ok":'
    assert err.identity is response.identity
    assert err.attempts is response.attempts


def test_model_error_without_response_carries_identity_and_attempts_directly() -> None:
    endpoint = _endpoint_identity()
    attempt = model_calls.ModelAttemptRecord(
        timing=_closed_span(),
        status="failure",
        retryable=False,
        error=errors.RunError(kind="connection_error", message="unreachable"),
    )
    err = model_calls.ModelError(
        "connection_error",
        "unreachable",
        identity=endpoint,
        attempts=[attempt],
    )

    assert err.response is None
    assert err.identity is endpoint
    assert err.attempts == [attempt]


def test_call_usage_exposes_output_token_entry() -> None:
    usage = model_calls.CallUsage(latency_ms=1000, tokens={"input": 3, "output": 5})
    assert usage.output_tokens() == 5

    absent = model_calls.CallUsage(latency_ms=0)
    assert absent.output_tokens() is None

    partial = model_calls.CallUsage(latency_ms=0, tokens={"input": 3})
    assert partial.output_tokens() is None

    with pytest.raises(ValueError):
        model_calls.CallUsage(latency_ms=0, tokens={"output": -1})
