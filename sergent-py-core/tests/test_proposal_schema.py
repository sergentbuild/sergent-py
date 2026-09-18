from __future__ import annotations

import datetime
import typing

import pydantic
import pydantic.dataclasses
import pydantic_core
import pytest
import typing_extensions

import sergent_py_core.proposals.schema as proposal_schema
import sergent_py_core.strict_model as strict_model


class NestedValue(strict_model.StrictModel):
    label: str = pydantic.Field(pattern=r"^[a-z]+$", description="Lowercase label.")


class RepresentativeProposal(strict_model.StrictModel):
    kind: typing.Literal["representative"] = "representative"
    child: NestedValue = pydantic.Field(description="Nested value.")
    optional: str | None = None
    values: list[int] = pydantic.Field(default_factory=list, min_length=1, max_length=3)
    amount: int = pydantic.Field(ge=1, le=5, multiple_of=1)
    created: datetime.date


class AliasProposal(strict_model.StrictModel):
    internal_name: str = pydantic.Field(validation_alias="provider_name")
    stable_name: str = pydantic.Field(serialization_alias="serialized_name")


class EmptyAliasProposal(strict_model.StrictModel):
    value: str = pydantic.Field(validation_alias="")


class AliasDisabledProposal(strict_model.StrictModel):
    model_config = pydantic.ConfigDict(
        extra="forbid", validate_assignment=True, validate_by_alias=False, validate_by_name=True
    )
    value: str = pydantic.Field(validation_alias="provider_value")


class AliasPathProposal(strict_model.StrictModel):
    value: str = pydantic.Field(validation_alias=pydantic.AliasPath("payload", "value"))


class AliasChoicesProposal(strict_model.StrictModel):
    value: str = pydantic.Field(validation_alias=pydantic.AliasChoices("value", "legacy"))


class DuplicateAliasProposal(strict_model.StrictModel):
    first: str = pydantic.Field(validation_alias="shared")
    second: str = pydantic.Field(validation_alias="shared")


def _identity(value: str) -> str:
    return value


class ValidatorProposal(strict_model.StrictModel):
    value: typing.Annotated[str, pydantic.AfterValidator(_identity)]

    @pydantic.field_validator("value")
    @classmethod
    def _validate_value(cls, value: str) -> str:
        return value

    @pydantic.model_validator(mode="after")
    def _validate_model(self) -> typing.Self:
        return self


class CoreSchemaText(str):
    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: type[typing.Any],
        handler: pydantic.GetCoreSchemaHandler,
        /,
    ) -> pydantic_core.CoreSchema:
        return pydantic_core.core_schema.no_info_after_validator_function(cls, handler(str))


class CoreSchemaValidatorProposal(strict_model.StrictModel):
    value: CoreSchemaText


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class ClosedDataClass:
    label: str


@pydantic.with_config(pydantic.ConfigDict(extra="forbid"))
class ClosedTypedDict(typing_extensions.TypedDict):
    label: str


class StructuredProposal(strict_model.StrictModel):
    data: ClosedDataClass
    mapping: ClosedTypedDict


class OpenProposal(pydantic.BaseModel):
    value: str


class DynamicMapProposal(strict_model.StrictModel):
    values: dict[str, int]


class AnyProposal(strict_model.StrictModel):
    value: typing.Any


class TupleProposal(strict_model.StrictModel):
    values: tuple[str, int]


class UnknownKeywordProposal(strict_model.StrictModel):
    value: str = pydantic.Field(examples=["example"])


class RootUnionProposal(pydantic.RootModel[str | int]):
    pass


class RecursiveValue(strict_model.StrictModel):
    children: list[RecursiveValue] = pydantic.Field(default_factory=list)


class RecursiveProposal(strict_model.StrictModel):
    value: RecursiveValue


def _walk_schema(value: object) -> typing.Iterator[dict[str, typing.Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_schema(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_schema(child)


def test_derivation_normalizes_only_the_approved_schema_differences() -> None:
    derived = proposal_schema.derive_proposal_schema(RepresentativeProposal)
    schema = derived.json_schema

    assert derived.name == "RepresentativeProposal"
    assert schema["required"] == ["kind", "child", "optional", "values", "amount", "created"]
    assert schema["properties"]["kind"] == {
        "enum": ["representative"],
        "type": "string",
    }
    child = schema["properties"]["child"]
    assert child == {
        "description": "Nested value.",
        "anyOf": [{"$ref": "#/$defs/NestedValue"}],
    }
    assert schema["properties"]["amount"] == {
        "maximum": 5,
        "minimum": 1,
        "type": "integer",
    }
    assert schema["properties"]["created"] == {"type": "string"}
    assert schema["properties"]["values"]["minItems"] == 1
    assert schema["properties"]["values"]["maxItems"] == 3
    assert schema["$defs"]["NestedValue"]["required"] == ["label"]
    forbidden = {
        "default",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "format",
        "maxLength",
        "maxProperties",
        "minLength",
        "minProperties",
        "multipleOf",
        "pattern",
        "title",
        "uniqueItems",
    }
    assert all(not forbidden.intersection(node) for node in _walk_schema(schema))


def test_derivation_is_deterministic_and_does_not_mutate_model_validation() -> None:
    first = proposal_schema.derive_proposal_schema(RepresentativeProposal)
    second = proposal_schema.derive_proposal_schema(RepresentativeProposal)

    assert first == second
    accepted = RepresentativeProposal.model_validate(
        {
            "child": {"label": "valid"},
            "amount": 2,
            "created": "2026-07-20",
        }
    )
    assert accepted.optional is None
    assert accepted.values == []


def test_validation_alias_is_provider_key_and_serialization_alias_is_ignored() -> None:
    derived = proposal_schema.derive_proposal_schema(AliasProposal)

    assert list(derived.json_schema["properties"]) == ["provider_name", "stable_name"]
    assert derived.json_schema["required"] == ["provider_name", "stable_name"]
    assert (
        AliasProposal.model_validate(
            {"provider_name": "provider", "stable_name": "stable"}
        ).internal_name
        == "provider"
    )


def test_empty_string_validation_alias_is_preserved() -> None:
    derived = proposal_schema.derive_proposal_schema(EmptyAliasProposal)
    assert list(derived.json_schema["properties"]) == [""]
    assert EmptyAliasProposal.model_validate({"": "accepted"}).value == "accepted"


@pytest.mark.parametrize(
    ("proposal_type", "message"),
    (
        (AliasDisabledProposal, "not accepted by model_validate"),
        (AliasPathProposal, "alias path or choices"),
        (AliasChoicesProposal, "alias path or choices"),
        (DuplicateAliasProposal, "duplicates field 'first'"),
    ),
)
def test_invalid_alias_shapes_fail_at_the_provider_key(
    proposal_type: type[pydantic.BaseModel], message: str
) -> None:
    with pytest.raises(ValueError) as error:
        proposal_schema.derive_proposal_schema(proposal_type)

    assert "/properties/" in str(error.value)
    assert message in str(error.value)


@pytest.mark.parametrize(
    ("proposal_type", "pointer", "message"),
    (
        (OpenProposal, "/additionalProperties", "additionalProperties"),
        (DynamicMapProposal, "/properties/values/additionalProperties", "additionalProperties"),
        (AnyProposal, "/properties/value", "no canonical structural form"),
        (TupleProposal, "/properties/values", "prefixItems"),
        (UnknownKeywordProposal, "/properties/value", "examples"),
        (RootUnionProposal, "/anyOf", "top-level anyOf is not supported"),
        (RecursiveProposal, "/$ref", "recursive reference"),
    ),
)
def test_closed_dialect_rejects_unsupported_shapes(
    proposal_type: type[pydantic.BaseModel], pointer: str, message: str
) -> None:
    with pytest.raises(ValueError) as error:
        proposal_schema.derive_proposal_schema(proposal_type)

    rendered = str(error.value)
    assert proposal_type.__name__ in rendered
    assert pointer in rendered
    assert message in rendered


def test_validation_metadata_and_model_validators_are_permitted() -> None:
    derived = proposal_schema.derive_proposal_schema(ValidatorProposal)

    assert derived.json_schema["properties"]["value"] == {"type": "string"}
    assert ValidatorProposal.model_validate({"value": "accepted"}).value == "accepted"


def test_application_core_schema_validator_is_permitted() -> None:
    derived = proposal_schema.derive_proposal_schema(CoreSchemaValidatorProposal)

    assert derived.json_schema["properties"]["value"] == {"type": "string"}
    accepted = CoreSchemaValidatorProposal.model_validate({"value": "accepted"})
    assert isinstance(accepted.value, CoreSchemaText)


def test_closed_dataclass_and_typed_dictionary_are_traversed_and_permitted() -> None:
    derived = proposal_schema.derive_proposal_schema(StructuredProposal)

    assert derived.json_schema["$defs"]["ClosedDataClass"]["additionalProperties"] is False
    assert derived.json_schema["$defs"]["ClosedTypedDict"]["additionalProperties"] is False


def test_factory_requires_a_pydantic_model_class() -> None:
    with pytest.raises(TypeError, match="Pydantic model class"):
        proposal_schema.derive_proposal_schema(str)  # pyright: ignore[reportArgumentType]
