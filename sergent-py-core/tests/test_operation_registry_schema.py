from __future__ import annotations

import json
import typing

import pydantic
import pytest

import sergent_py_core.operation as operation
import sergent_py_core.proposals.operation_registry as operation_registry
import sergent_py_core.strict_model as strict_model
import sergent_py_core.target as target


class SharedValue(strict_model.StrictModel):
    label: str


class FirstOperation(operation.Operation, frozen=True):
    """Use one shared nested value."""

    call: typing.Literal["first"] = "first"
    child: SharedValue

    def apply(self, scene: object, _target: target.Target) -> object:
        return scene


class SecondOperation(operation.Operation, frozen=True):
    """Use the same shared nested value."""

    call: typing.Literal["second"] = "second"
    child: SharedValue

    def apply(self, scene: object, _target: target.Target) -> object:
        return scene


class _ConflictA:
    class SharedConflict(strict_model.StrictModel):
        label: str


class _ConflictB:
    class SharedConflict(strict_model.StrictModel):
        amount: int


class ConflictFirstOperation(operation.Operation, frozen=True):
    call: typing.Literal["conflict_first"] = "conflict_first"
    child: _ConflictA.SharedConflict

    def apply(self, scene: object, _target: target.Target) -> object:
        return scene


class ConflictSecondOperation(operation.Operation, frozen=True):
    call: typing.Literal["conflict_second"] = "conflict_second"
    child: _ConflictB.SharedConflict

    def apply(self, scene: object, _target: target.Target) -> object:
        return scene


class _NestedName:
    class NameCollision(strict_model.StrictModel):
        label: str


class NameCollision(operation.Operation, frozen=True):
    call: typing.Literal["name_collision"] = "name_collision"
    child: _NestedName.NameCollision

    def apply(self, scene: object, _target: target.Target) -> object:
        return scene


class _JsonConflictA:
    class SharedJsonConflict(strict_model.StrictModel):
        value: typing.Literal[True, "shared"]


class _JsonConflictB:
    class SharedJsonConflict(strict_model.StrictModel):
        value: typing.Literal[1, "shared"]


class JsonConflictFirstOperation(operation.Operation, frozen=True):
    call: typing.Literal["json_conflict_first"] = "json_conflict_first"
    child: _JsonConflictA.SharedJsonConflict

    def apply(self, scene: object, _target: target.Target) -> object:
        return scene


class JsonConflictSecondOperation(operation.Operation, frozen=True):
    call: typing.Literal["json_conflict_second"] = "json_conflict_second"
    child: _JsonConflictB.SharedJsonConflict

    def apply(self, scene: object, _target: target.Target) -> object:
        return scene


class DynamicMapOperation(operation.Operation, frozen=True):
    call: typing.Literal["dynamic"] = "dynamic"
    values: dict[str, int]

    def apply(self, scene: object, _target: target.Target) -> object:
        return scene


class AliasedCallOperation(operation.Operation, frozen=True):
    call: typing.Literal["aliased"] = pydantic.Field(default="aliased", validation_alias="renamed")

    def apply(self, scene: object, _target: target.Target) -> object:
        return scene


class SerializedCallOperation(operation.Operation, frozen=True):
    call: typing.Literal["serialized"] = pydantic.Field(
        default="serialized", serialization_alias="renamed"
    )

    def apply(self, scene: object, _target: target.Target) -> object:
        return scene


class AbstractOperation(operation.Operation, frozen=True):
    call: typing.Literal["abstract"] = "abstract"


def test_single_operation_plan_schema_has_exact_closed_envelope() -> None:
    registry = operation_registry.OperationRegistry((FirstOperation,))
    schema = registry.plan_proposal_schema(2)

    assert schema.name == "PlanProposal"
    assert list(schema.json_schema["$defs"]) == ["FirstOperation", "SharedValue"]
    assert schema.json_schema["properties"] == {
        "operations": {
            "type": "array",
            "items": {"$ref": "#/$defs/FirstOperation"},
            "minItems": 1,
            "maxItems": 2,
        }
    }
    assert schema.json_schema["required"] == ["operations"]
    assert schema.json_schema["additionalProperties"] is False
    operation_schema = schema.json_schema["$defs"]["FirstOperation"]
    assert operation_schema["properties"]["call"] == {
        "enum": ["first"],
        "type": "string",
    }
    assert operation_schema["required"] == ["call", "child"]
    assert "op_id" not in json.dumps(schema.json_schema)
    assert "_op_id" not in json.dumps(schema.json_schema)


def test_multiple_operation_branches_keep_registry_order_and_share_equal_defs() -> None:
    registry = operation_registry.OperationRegistry((SecondOperation, FirstOperation))

    unbounded = registry.plan_proposal_schema(None)
    items = unbounded.json_schema["properties"]["operations"]["items"]
    assert items == {
        "anyOf": [
            {"$ref": "#/$defs/SecondOperation"},
            {"$ref": "#/$defs/FirstOperation"},
        ]
    }
    assert "maxItems" not in unbounded.json_schema["properties"]["operations"]
    assert list(unbounded.json_schema["$defs"]) == [
        "FirstOperation",
        "SecondOperation",
        "SharedValue",
    ]
    assert registry.plan_proposal_schema(None) == unbounded


def test_mutating_a_returned_plan_schema_does_not_corrupt_cached_branches() -> None:
    registry = operation_registry.OperationRegistry((FirstOperation, SecondOperation))
    first = registry.plan_proposal_schema(2)

    first.json_schema["$defs"]["FirstOperation"]["properties"]["call"]["enum"][0] = "corrupted"
    first.json_schema["properties"]["operations"]["maxItems"] = 99

    second = registry.plan_proposal_schema(2)
    assert second.json_schema["$defs"]["FirstOperation"]["properties"]["call"]["enum"] == ["first"]
    assert second.json_schema["properties"]["operations"]["maxItems"] == 2


def test_definition_collision_fails_eagerly_with_both_operation_sources() -> None:
    with pytest.raises(ValueError) as error:
        operation_registry.OperationRegistry((ConflictFirstOperation, ConflictSecondOperation))

    message = str(error.value)
    assert "/$defs/SharedConflict" in message
    assert "ConflictFirstOperation (call='conflict_first')" in message
    assert "ConflictSecondOperation (call='conflict_second')" in message


def test_operation_name_collision_with_nested_definition_fails_eagerly() -> None:
    with pytest.raises(ValueError, match=r"/\$defs/NameCollision"):
        operation_registry.OperationRegistry((NameCollision,))


def test_definition_collision_comparison_preserves_json_scalar_types() -> None:
    with pytest.raises(ValueError) as error:
        operation_registry.OperationRegistry(
            (JsonConflictFirstOperation, JsonConflictSecondOperation)
        )

    message = str(error.value)
    assert "/$defs/SharedJsonConflict" in message
    assert "JsonConflictFirstOperation (call='json_conflict_first')" in message
    assert "JsonConflictSecondOperation (call='json_conflict_second')" in message


def test_definition_comparison_uses_json_number_and_boolean_identity() -> None:
    assert operation_registry._json_values_equal(
        {"enum": [1], "minimum": 1.0},
        {"minimum": 1, "enum": [1.0]},
    )
    assert not operation_registry._json_values_equal({"enum": [True]}, {"enum": [1]})


def test_plan_lifting_preserves_escaped_local_definition_references() -> None:
    rewritten = operation_registry.OperationRegistry._rewrite_local_refs(
        {"$ref": "#/$defs/Leaf~1Value~0"},
        {"Leaf/Value~": "Leaf/Value~"},
    )
    assert rewritten == {"$ref": "#/$defs/Leaf~1Value~0"}


def test_noncanonical_operation_schema_fails_during_registry_construction() -> None:
    with pytest.raises(ValueError) as error:
        operation_registry.OperationRegistry((DynamicMapOperation,))

    message = str(error.value)
    assert "DynamicMapOperation (call='dynamic')" in message
    assert "/properties/values/additionalProperties" in message


@pytest.mark.parametrize("operation_type", (AliasedCallOperation, SerializedCallOperation))
def test_call_aliases_fail_at_the_discriminator(
    operation_type: type[operation.Operation],
) -> None:
    with pytest.raises(ValueError) as error:
        operation_registry.OperationRegistry((operation_type,))

    assert operation_type.__name__ in str(error.value)
    assert "/properties/call" in str(error.value)
    assert "aliases" in str(error.value)


def test_registry_requires_an_exact_concrete_operation_class() -> None:
    with pytest.raises(TypeError, match="exact concrete"):
        operation_registry.OperationRegistry((AbstractOperation,))
    with pytest.raises(TypeError, match="exact concrete"):
        operation_registry.OperationRegistry((operation.Operation,))


@pytest.mark.parametrize("bound", (0, -1))
def test_plan_schema_rejects_nonpositive_bounds(bound: int) -> None:
    registry = operation_registry.OperationRegistry((FirstOperation,))
    with pytest.raises(ValueError, match="must be positive"):
        registry.plan_proposal_schema(bound)


def test_plan_schema_rejects_boolean_and_noninteger_bounds() -> None:
    registry = operation_registry.OperationRegistry((FirstOperation,))
    with pytest.raises(TypeError, match="positive integer"):
        registry.plan_proposal_schema(False)
    with pytest.raises(TypeError, match="positive integer"):
        registry.plan_proposal_schema("1")  # pyright: ignore[reportArgumentType]
