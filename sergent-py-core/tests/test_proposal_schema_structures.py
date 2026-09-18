from __future__ import annotations

import typing

import pydantic
import pydantic.dataclasses
import pytest
import typing_extensions

import sergent_py_core.proposals.schema as proposal_schema
import sergent_py_core.strict_model as strict_model

_T = typing.TypeVar("_T")


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class GenericDataClass(typing.Generic[_T]):
    value: _T


@pydantic.with_config(pydantic.ConfigDict(extra="forbid"))
class GenericTypedDict(typing_extensions.TypedDict, typing.Generic[_T]):
    value: _T


class GenericStructuresProposal(strict_model.StrictModel):
    data: GenericDataClass[str]
    mapping: GenericTypedDict[int]


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid", title="Authored"))
class TitledGenericDataClass(typing.Generic[_T]):
    value: _T


class TitledGenericDataClassProposal(strict_model.StrictModel):
    value: TitledGenericDataClass[str]


@pydantic.with_config(pydantic.ConfigDict(extra="forbid", json_schema_extra={}))
class ExtraGenericTypedDict(typing_extensions.TypedDict, typing.Generic[_T]):
    value: _T


class ExtraGenericTypedDictProposal(strict_model.StrictModel):
    value: ExtraGenericTypedDict[str]


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid", title="Authored"))
class TitledDataClassBase:
    base: str


@pydantic.dataclasses.dataclass
class InheritedTitledDataClass(TitledDataClassBase):
    child: str


class InheritedTitledDataClassProposal(strict_model.StrictModel):
    value: InheritedTitledDataClass


@pydantic.with_config(pydantic.ConfigDict(extra="forbid", json_schema_extra={}))
class ExtraTypedDictBase(typing_extensions.TypedDict):
    base: str


class InheritedExtraTypedDict(ExtraTypedDictBase):
    child: str


class InheritedExtraTypedDictProposal(strict_model.StrictModel):
    value: InheritedExtraTypedDict


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class TitledFieldDataClass:
    value: str = pydantic.Field(title="Authored")


class TitledFieldDataClassProposal(strict_model.StrictModel):
    value: TitledFieldDataClass


@pydantic.with_config(pydantic.ConfigDict(extra="forbid"))
class ExtraFieldTypedDict(typing_extensions.TypedDict):
    value: typing.Annotated[str, pydantic.Field(json_schema_extra={})]


class ExtraFieldTypedDictProposal(strict_model.StrictModel):
    value: ExtraFieldTypedDict


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
class DuplicateAliasDataClass:
    first: str = pydantic.Field(validation_alias="shared")
    second: str = pydantic.Field(validation_alias="shared")


class DuplicateAliasDataClassProposal(strict_model.StrictModel):
    value: DuplicateAliasDataClass


@pydantic.with_config(pydantic.ConfigDict(extra="forbid"))
class AliasPathTypedDict(typing_extensions.TypedDict):
    value: typing.Annotated[
        str,
        pydantic.Field(validation_alias=pydantic.AliasPath("payload", "value")),
    ]


class AliasPathTypedDictProposal(strict_model.StrictModel):
    value: AliasPathTypedDict


def _provider_alias(field_name: str) -> str:
    return f"provider_{field_name}"


@pydantic.with_config(pydantic.ConfigDict(extra="forbid", alias_generator=_provider_alias))
class GeneratedAliasTypedDict(typing_extensions.TypedDict):
    value: str


class GeneratedAliasTypedDictProposal(strict_model.StrictModel):
    mapping: GeneratedAliasTypedDict


@pydantic.with_config(pydantic.ConfigDict(extra="forbid"))
class AliasedTypedDictBase(typing_extensions.TypedDict):
    internal: typing.Annotated[str, pydantic.Field(validation_alias="provider_name")]


class InheritedAliasTypedDict(AliasedTypedDictBase):
    other: str


class InheritedAliasTypedDictProposal(strict_model.StrictModel):
    mapping: InheritedAliasTypedDict


def test_generic_dataclass_and_typed_dictionary_are_traversed() -> None:
    derived = proposal_schema.derive_proposal_schema(GenericStructuresProposal)

    assert derived.json_schema["$defs"]["GenericDataClass_str_"]["additionalProperties"] is False
    assert derived.json_schema["$defs"]["GenericTypedDict_int_"]["additionalProperties"] is False


@pytest.mark.parametrize(
    ("proposal_type", "message"),
    (
        (TitledGenericDataClassProposal, "authored model title"),
        (ExtraGenericTypedDictProposal, "model json_schema_extra"),
        (InheritedTitledDataClassProposal, "authored model title"),
        (InheritedExtraTypedDictProposal, "model json_schema_extra"),
        (TitledFieldDataClassProposal, "authored field title"),
        (ExtraFieldTypedDictProposal, "field json_schema_extra"),
    ),
)
def test_structured_type_schema_authorship_is_rejected(
    proposal_type: type[pydantic.BaseModel], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        proposal_schema.derive_proposal_schema(proposal_type)


@pytest.mark.parametrize(
    ("proposal_type", "message"),
    (
        (DuplicateAliasDataClassProposal, "duplicates field"),
        (AliasPathTypedDictProposal, "alias path or choices"),
    ),
)
def test_structured_type_alias_failures_are_rejected(
    proposal_type: type[pydantic.BaseModel], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        proposal_schema.derive_proposal_schema(proposal_type)


def test_typed_dictionary_alias_generator_matches_validation_key() -> None:
    derived = proposal_schema.derive_proposal_schema(GeneratedAliasTypedDictProposal)

    definition = derived.json_schema["$defs"]["GeneratedAliasTypedDict"]
    assert list(definition["properties"]) == ["provider_value"]
    accepted = GeneratedAliasTypedDictProposal.model_validate(
        {"mapping": {"provider_value": "accepted"}}
    )
    assert accepted.mapping["value"] == "accepted"


def test_inherited_typed_dictionary_alias_matches_validation_key() -> None:
    derived = proposal_schema.derive_proposal_schema(InheritedAliasTypedDictProposal)

    definition = derived.json_schema["$defs"]["InheritedAliasTypedDict"]
    assert list(definition["properties"]) == ["provider_name", "other"]
    accepted = InheritedAliasTypedDictProposal.model_validate(
        {"mapping": {"provider_name": "accepted", "other": "value"}}
    )
    assert accepted.mapping["internal"] == "accepted"
