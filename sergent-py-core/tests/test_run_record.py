from __future__ import annotations

import pytest

import sergent_py_core.errors as errors
import sergent_py_core.identifiers as identifiers
import sergent_py_core.model_calls as model_calls
import sergent_py_core.run_record as run_record
import sergent_py_core.timing as timing


def _closed_span() -> timing.TimeSpan:
    return timing.TimeSpan(
        started_at="2026-04-26T00:00:00Z",
        finished_at="2026-04-26T00:00:01Z",
        duration_ms=1000,
    )


def test_captured_value_derives_and_serializes_status() -> None:
    captured = run_record.CapturedValue(value={"answer": 42}, value_type="dict")
    capture_error = errors.RunError(kind="capture_error", message="failed")
    failed = run_record.CapturedValue(value_type="Opaque", error=capture_error)

    assert set(run_record.CapturedValue.model_fields) == {"value", "value_type", "error"}
    assert set(run_record.CapturedValue.model_computed_fields) == {"status"}
    assert (captured.status, failed.status) == ("captured", "capture_error")
    assert captured.model_dump(mode="json") == {
        "value": {"answer": 42},
        "value_type": "dict",
        "error": None,
        "status": "captured",
    }
    assert failed.model_dump(mode="json")["status"] == "capture_error"

    serialization_schema = run_record.CapturedValue.model_json_schema(mode="serialization")
    status_schema = serialization_schema["properties"]["status"]
    assert status_schema["enum"] == ["captured", "capture_error"]
    assert (status_schema["type"], status_schema["readOnly"]) == ("string", True)
    validation_schema = run_record.CapturedValue.model_json_schema(mode="validation")
    assert "status" not in validation_schema["properties"]
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        run_record.CapturedValue.model_validate({"status": "captured", "value_type": "dict"})


def test_run_outcome_enforces_status_error_terminal_coherence() -> None:
    error = errors.RunError(kind="validation_error", message="bad plan")
    terminal = run_record.RunTerminalRecord(
        message=run_record.CapturedValue(value="done", value_type="str"),
        metadata=run_record.CapturedValue(value={}, value_type="dict"),
    )

    assert run_record.RunOutcome().status == "running"
    assert run_record.RunOutcome(status="failure", error=error).error is error
    assert run_record.RunOutcome(status="cancelled", error=error).status == "cancelled"
    assert run_record.RunOutcome(status="success", terminal=terminal).terminal is terminal

    with pytest.raises(ValueError, match="cannot carry an error"):
        run_record.RunOutcome(status="running", error=error)
    with pytest.raises(ValueError, match="cannot carry an error"):
        run_record.RunOutcome(status="success", error=error)
    with pytest.raises(ValueError, match="requires an error"):
        run_record.RunOutcome(status="failure")
    with pytest.raises(ValueError, match="requires an error"):
        run_record.RunOutcome(status="cancelled")
    with pytest.raises(ValueError, match="only on a success"):
        run_record.RunOutcome(status="running", terminal=terminal)
    with pytest.raises(ValueError, match="only on a success"):
        run_record.RunOutcome(status="failure", error=error, terminal=terminal)


def test_run_record_model_call_usages_preserves_order_and_missing_slots() -> None:
    first = model_calls.CallUsage(latency_ms=1, tokens={"input": 2, "output": 3})
    last = model_calls.CallUsage(latency_ms=2, tokens={"input": 4, "output": 5})
    record = _record_with_model_call_usages(first, None, last)

    assert record.model_call_usages() == [first, None, last]


def test_run_record_selection_uses_full_model_name() -> None:
    record = _record_with_model_call_usages(None)
    model_call = record.steps[0].model_call

    assert model_call is not None
    assert record.model_name == "test/fake"
    assert model_call.model_name == "test/fake"
    assert model_call.proposal_schema.name == "Proposal"
    assert "schema_name" not in run_record.ModelCallRecord.model_fields


def test_run_record_total_output_tokens_requires_complete_usage() -> None:
    assert _record_with_model_call_usages().total_output_tokens() == 0
    assert (
        _record_with_model_call_usages(
            model_calls.CallUsage(latency_ms=1, tokens={"output": 3}),
            model_calls.CallUsage(latency_ms=2, tokens={"output": 5}),
        ).total_output_tokens()
        == 8
    )
    assert _record_with_model_call_usages(None).total_output_tokens() is None
    assert (
        _record_with_model_call_usages(
            model_calls.CallUsage(latency_ms=1, tokens={"input": 3})
        ).total_output_tokens()
        is None
    )


def _record_with_model_call_usages(
    *usages: model_calls.CallUsage | None,
) -> run_record.RunRecord:
    steps = [
        run_record.RunStepRecord(
            name=f"call_{index}",
            status="success",
            timing=_closed_span(),
            model_call=run_record.ModelCallRecord(
                proposal_schema=model_calls.ProposalSchema(
                    name="Proposal",
                    json_schema={"type": "object"},
                ),
                model_name="test/fake",
                payloads=run_record.ModelCallPayloads(
                    request=run_record.CapturedValue(
                        value={},
                        value_type="dict",
                    )
                ),
                usage=usage,
            ),
        )
        for index, usage in enumerate(usages)
    ]
    return run_record.RunRecord(
        run_id=identifiers.new_id("run"),
        model_name="test/fake",
        timing=_closed_span(),
        steps=steps,
        outcome=run_record.RunOutcome(status="success"),
    )
