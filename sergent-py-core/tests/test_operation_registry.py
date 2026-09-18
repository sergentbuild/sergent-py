from __future__ import annotations

import copy
import typing

import pytest

import sergent_py_core.operation as core_operation
import sergent_py_core.proposals.operation_registry as operation_registry
import sergent_py_core.target as core_target


class RegistryOperation(core_operation.Operation, frozen=True):
    call: typing.Literal["registry"] = "registry"
    value: str

    def apply(self, scene: object, _target: core_target.Target) -> object:
        return scene


class DuplicateRegistryOperation(core_operation.Operation, frozen=True):
    call: typing.Literal["registry"] = "registry"
    label: str

    def apply(self, scene: object, _target: core_target.Target) -> object:
        return scene


class AlternateRegistryOperation(core_operation.Operation, frozen=True):
    call: typing.Literal["alternate"] = "alternate"
    count: int

    def apply(self, scene: object, _target: core_target.Target) -> object:
        return scene


class PlainCallOperation(core_operation.Operation, frozen=True):
    call: str = "plain"

    def apply(self, scene: object, _target: core_target.Target) -> object:
        return scene


class MismatchedDefaultOperation(core_operation.Operation, frozen=True):
    call: typing.Literal["mismatched"] = "typo"  # pyright: ignore[reportAssignmentType] - deliberate mismatch

    def apply(self, scene: object, _target: core_target.Target) -> object:
        return scene


def test_duplicate_call_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate operation call 'registry'"):
        operation_registry.OperationRegistry((RegistryOperation, DuplicateRegistryOperation))


def test_empty_registry_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="registry requires at least one Operation type"):
        operation_registry.OperationRegistry(())


def test_non_literal_call_is_rejected() -> None:
    with pytest.raises(ValueError, match="PlainCallOperation.*single-value string Literal"):
        operation_registry.OperationRegistry((PlainCallOperation,))


def test_mismatched_call_default_is_rejected() -> None:
    with pytest.raises(ValueError, match="MismatchedDefaultOperation.*call must default"):
        operation_registry.OperationRegistry((MismatchedDefaultOperation,))


def test_decode_requires_exact_top_level_keys_and_names_unknowns() -> None:
    registry = operation_registry.OperationRegistry((RegistryOperation,))

    with pytest.raises(ValueError, match="requires exactly the 'operations' key"):
        registry.decode_plan_proposal({})

    with pytest.raises(ValueError) as error:
        registry.decode_plan_proposal(
            {
                "operations": [{"call": "registry", "value": "ok"}],
                "commentary": "not part of the envelope",
            }
        )

    assert "unknown top-level keys" in str(error.value)
    assert "'commentary'" in str(error.value)


def test_decode_requires_an_operations_list() -> None:
    registry = operation_registry.OperationRegistry((RegistryOperation,))

    with pytest.raises(ValueError, match="operations must be a list"):
        registry.decode_plan_proposal({"operations": {"call": "registry", "value": "ok"}})


def test_decode_rejects_an_empty_operations_list_through_the_static_envelope() -> None:
    registry = operation_registry.OperationRegistry((RegistryOperation,))

    with pytest.raises(ValueError) as error:
        registry.decode_plan_proposal({"operations": []})

    assert "invalid Plan proposal" in str(error.value)
    assert "at least 1 item" in str(error.value)


def test_decode_enforces_the_configured_maximum() -> None:
    registry = operation_registry.OperationRegistry((RegistryOperation,))

    with pytest.raises(ValueError, match="operations exceed configured maximum of 1"):
        registry.decode_plan_proposal(
            {
                "operations": [
                    {"call": "registry", "value": "first"},
                    {"call": "registry", "value": "second"},
                ]
            },
            max_operations=1,
        )


def test_decode_rejects_a_non_object_operation_item() -> None:
    registry = operation_registry.OperationRegistry((RegistryOperation,))

    with pytest.raises(ValueError) as error:
        registry.decode_plan_proposal(
            {
                "operations": [
                    {"call": "registry", "value": "first"},
                    "registry",
                ]
            }
        )

    assert "operation 1 (call=None): operation must be an object" in str(error.value)


def test_decode_requires_registered_string_calls() -> None:
    registry = operation_registry.OperationRegistry((RegistryOperation,))

    with pytest.raises(ValueError) as non_string_error:
        registry.decode_plan_proposal({"operations": [{"call": 3, "value": "ok"}]})
    with pytest.raises(ValueError) as unknown_error:
        registry.decode_plan_proposal({"operations": [{"call": "missing", "value": "ok"}]})

    assert "operation 0 (call=3): operation call must be a string" in str(non_string_error.value)
    assert "operation 0 (call='missing'): unknown operation call: 'missing'" in str(
        unknown_error.value
    )


@pytest.mark.parametrize(
    ("extra_name", "extra_value"),
    (("op_id", "op-from-model"), ("internal", {"trusted": False})),
)
def test_decode_wraps_strict_concrete_validation_with_item_context(
    extra_name: str, extra_value: object
) -> None:
    registry = operation_registry.OperationRegistry((RegistryOperation,))
    invalid_item = {"call": "registry", "value": "second", extra_name: extra_value}

    with pytest.raises(ValueError) as error:
        registry.decode_plan_proposal(
            {
                "operations": [
                    {"call": "registry", "value": "first"},
                    invalid_item,
                ]
            }
        )

    message = str(error.value)
    assert "operation 1 (call='registry')" in message
    assert extra_name in message
    assert "extra_forbidden" in message


def test_plan_schema_and_decode_share_ordered_exact_registered_types() -> None:
    registry = operation_registry.OperationRegistry((RegistryOperation, AlternateRegistryOperation))
    schema = registry.plan_proposal_schema(None).json_schema

    proposal = registry.decode_plan_proposal(
        {
            "operations": [
                {"call": "alternate", "count": 2},
                {"call": "registry", "value": "ok"},
            ]
        }
    )

    assert schema["properties"]["operations"]["items"] == {
        "anyOf": [
            {"$ref": "#/$defs/RegistryOperation"},
            {"$ref": "#/$defs/AlternateRegistryOperation"},
        ]
    }
    assert [type(item) for item in proposal.operations] == [
        AlternateRegistryOperation,
        RegistryOperation,
    ]


def test_decode_is_stateless_and_leaves_payload_and_registry_unchanged() -> None:
    registry = operation_registry.OperationRegistry((RegistryOperation,))
    payload: dict[str, typing.Any] = {"operations": [{"call": "registry", "value": "ok"}]}
    original_payload = copy.deepcopy(payload)
    original_schema = registry.plan_proposal_schema(None)

    first = registry.decode_plan_proposal(payload)
    second = registry.decode_plan_proposal(payload)

    assert payload == original_payload
    assert registry.plan_proposal_schema(None) == original_schema
    assert first.model_dump(mode="json", serialize_as_any=True) == second.model_dump(
        mode="json", serialize_as_any=True
    )
    assert first is not second
    assert first.operations[0] is not second.operations[0]
