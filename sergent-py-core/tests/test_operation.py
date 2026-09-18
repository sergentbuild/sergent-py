from __future__ import annotations

import typing

import pydantic
import pytest

import sergent_py_core.operation as core_operation
import sergent_py_core.target as core_target
import sergent_py_core.identifiers as identifiers


class SampleOperation(core_operation.Operation, frozen=True):
    call: typing.Literal["sample"] = "sample"
    body: str = "hello"
    values: list[str] = pydantic.Field(default_factory=list)

    def apply(self, scene: object, _target: core_target.Target) -> object:
        return scene


def test_operation_rejects_bookkeeping_input() -> None:
    for bookkeeping_key in ("internal", "op_id"):
        with pytest.raises(pydantic.ValidationError) as exc_info:
            SampleOperation.model_validate(
                {
                    "call": "sample",
                    "body": "ok",
                    bookkeeping_key: "model-authored",
                }
            )

        errors = exc_info.value.errors()
        assert [(error["type"], error["loc"]) for error in errors] == [
            ("extra_forbidden", (bookkeeping_key,))
        ]


def test_operation_mints_identity_and_deep_copy_preserves_it() -> None:
    operation = SampleOperation(values=["original"])
    copied = operation.model_copy(deep=True)
    copied.values.append("copied")

    assert identifiers.checked_id(operation.op_id, "op") == operation.op_id
    assert copied.op_id == operation.op_id
    assert operation.values == ["original"]
    assert copied.values == ["original", "copied"]


def test_operation_instances_are_frozen() -> None:
    operation = SampleOperation()
    original_op_id = operation.op_id

    with pytest.raises(pydantic.ValidationError, match="frozen"):
        setattr(operation, "body", "changed")
    with pytest.raises(TypeError, match="operation ID is immutable"):
        setattr(operation, "_op_id", "replacement")
    with pytest.raises(TypeError, match="operation ID is immutable"):
        delattr(operation, "_op_id")

    assert operation.op_id == original_op_id


def test_operation_default_admissibility_accepts_exact_target_context() -> None:
    operation = SampleOperation()
    target = core_target.Target(target_id="sample-target")

    assert operation.validate_for(object(), object(), target) is None


def test_operation_schema_and_dump_exclude_identity() -> None:
    operation = SampleOperation()

    for mode in ("validation", "serialization"):
        properties = SampleOperation.model_json_schema(mode=mode)["properties"]
        assert set(properties) == {"call", "body", "values"}
    assert operation.model_dump(mode="json") == {
        "call": "sample",
        "body": "hello",
        "values": [],
    }


def test_operation_trace_rejects_wrong_id_prefix() -> None:
    with pytest.raises(ValueError):
        core_operation.OperationTrace(op_id=identifiers.new_id("plan"))


def test_operation_base_requires_apply_hook() -> None:
    with pytest.raises(TypeError):
        core_operation.Operation(call="sample")  # pyright: ignore[reportAbstractUsage] - deliberate
