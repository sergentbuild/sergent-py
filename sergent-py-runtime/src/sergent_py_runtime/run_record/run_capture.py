"""Capture best-effort Run Record evidence. @sergent/docs/run-record-spec.md
@sergent-py-runtime/docs/KNOWLEDGE.md"""

from __future__ import annotations

import dataclasses
import traceback

import pydantic

import sergent_py_core.errors as core_errors
import sergent_py_core.patch as core_patch
import sergent_py_core.run_record as core_run_record
import sergent_py_core.model_calls as core_model_calls
import sergent_py_runtime.execution.errors as runtime_errors


def _format_exception(exc: BaseException) -> str:
    """Render an exception with its concrete type name."""
    text = str(exc)
    if text:
        return f"{type(exc).__name__}: {text}"
    return type(exc).__name__


def capture_value(value: object) -> core_run_record.CapturedValue:
    """Capture one value for the Run Record. @sergent/docs/run-record-spec.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    value_type = type(value).__name__
    try:
        return core_run_record.CapturedValue(value=jsonish(value), value_type=value_type)
    except Exception as exc:
        error = core_errors.RunError(
            kind="capture_error",
            message=_format_exception(exc),
            metadata={"value_type": value_type},
        )
        return core_run_record.CapturedValue(
            value=None,
            value_type=value_type,
            error=error,
        )


def error_record(
    error: BaseException,
    *,
    current_step: str | None,
) -> core_errors.RunError:
    """Convert a contained exception into a RunError. @sergent/docs/execution-model.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    if isinstance(error, core_model_calls.ModelError):
        return core_errors.RunError(
            kind=error.kind,
            message=error.message,
            metadata={"retryable": error.retryable},
        )
    if isinstance(error, runtime_errors._OperationAdmissibilityError):
        return core_errors.RunError(
            kind="validation_error",
            message=str(error),
            metadata=dict(error.metadata),
        )
    if isinstance(error, runtime_errors._ProposalSchemaError):
        return core_errors.RunError(kind="schema_validation_failed", message=str(error))
    if isinstance(error, runtime_errors.MergeConflictError):
        return core_errors.RunError(
            kind="merge_conflict",
            message=str(error),
            metadata=dict(error.metadata),
        )
    if isinstance(error, runtime_errors.StalePatchError):
        return core_errors.RunError(
            kind="stale_patch",
            message=str(error),
            metadata={
                "base_revision": error.base_revision,
                "current_revision": error.current_revision,
            },
        )
    if isinstance(error, runtime_errors.DryRunError):
        return core_errors.RunError(
            kind="validation_error",
            message=str(error),
            metadata=dict(error.metadata),
        )
    if isinstance(error, runtime_errors.PatchValidationError):
        return core_errors.RunError(
            kind="patch_validation",
            message=str(error),
            metadata=dict(error.metadata),
        )
    if isinstance(error, ValueError):
        return core_errors.RunError(kind="validation_error", message=str(error))
    return core_errors.RunError(
        kind="internal_error",
        message=_format_exception(error),
        metadata={
            "exception_type": type(error).__name__,
            "traceback": bounded_traceback(error),
            "cause_chain": cause_chain(error),
            "current_step": current_step,
        },
    )


def patch_summary(
    patch: core_patch.Patch,
) -> dict[str, object]:
    """Build Patch evidence for the Run Record. @sergent/docs/run-record-spec.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    operations = patch.operations
    trace = patch.operation_trace
    return {
        "base": jsonish(patch.base),
        "operation_count": len(operations),
        "operation_ids": [operation.op_id for operation in operations],
        "operation_call_names": [operation.call for operation in operations],
        "operation_trace_ids": [item.op_id for item in trace],
        "operations": [
            capture_value(operation).model_dump(mode="json") for operation in operations
        ],
    }


def jsonish(value: object) -> object:
    """Project trusted data into Run Record JSON. @sergent/docs/run-record-spec.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, core_model_calls.ImagePart):
        return {"media_type": value.media_type, "bytes": value.decoded_byte_count()}
    if isinstance(value, core_model_calls.ModelMessage):
        captured = {"role": jsonish(value.role), "content": jsonish(value.content)}
        if value.images:
            captured["images"] = jsonish(value.images)
        return captured
    if isinstance(value, core_model_calls.ModelRequest):
        return {
            "model_name": jsonish(value.model_name),
            "messages": jsonish(value.messages),
            "model_settings": jsonish(value.model_settings),
        }
    if isinstance(value, pydantic.BaseModel):
        # serialize_as_any keeps runtime subclass fields (e.g. an Operation
        # subclass row/col under a base-typed list) for faithful forensics.
        # A nested class left unrebuilt by an unresolved forward reference
        # still carries pydantic's mock serializer, which makes the
        # richer dump raise TypeError; retry with the static-schema dump.
        try:
            return jsonish(value.model_dump(mode="json", serialize_as_any=True))
        except TypeError:
            return jsonish(value.model_dump(mode="json"))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: jsonish(getattr(value, field.name)) for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(key): jsonish(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonish(item) for item in value]
    if isinstance(value, set):
        return [jsonish(item) for item in sorted(value, key=repr)]
    return {"type": type(value).__name__, "repr": safe_repr(value)}


def safe_repr(value: object) -> str:
    """Render fallback text without propagating ordinary failures."""
    try:
        return repr(value)
    except Exception as exc:
        return f"<repr failed: {_format_exception(exc)}>"


def bounded_traceback(error: BaseException) -> str:
    """Capture the bounded tail of an exception traceback."""
    text = "".join(traceback.format_exception(type(error), error, error.__traceback__, limit=20))
    return text[-8000:]


def cause_chain(error: BaseException) -> list[dict[str, str]]:
    """Capture a finite causal chain without revisiting cycles."""
    chain: list[dict[str, str]] = []
    seen: set[int] = set()
    current = error.__cause__ or error.__context__
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(
            {
                "exception_type": type(current).__name__,
                "message": str(current),
            }
        )
        current = current.__cause__ or current.__context__
    return chain
