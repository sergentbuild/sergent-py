from __future__ import annotations

import dataclasses
import typing

import pydantic
import pydantic.dataclasses
import pydantic_core
import pytest
import typing_extensions

import sergent_py_core.proposals.schema as proposal_schema
import sergent_py_core.strict_model as strict_model


class AuthoredModelSchema(strict_model.StrictModel):
    value: str

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool = True,
        ref_template: str = pydantic.json_schema.DEFAULT_REF_TEMPLATE,
        schema_generator: type[pydantic.json_schema.GenerateJsonSchema] = (
            pydantic.json_schema.GenerateJsonSchema
        ),
        mode: pydantic.json_schema.JsonSchemaMode = "validation",
        *,
        union_format: typing.Literal["any_of", "primitive_type_array"] = "any_of",
    ) -> dict[str, typing.Any]:
        return super().model_json_schema(
            by_alias,
            ref_template,
            schema_generator,
            mode,
            union_format=union_format,
        )


class InheritedAuthoredModelSchema(AuthoredModelSchema):
    other: str


class AuthoredType:
    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: pydantic_core.CoreSchema,
        handler: pydantic.GetJsonSchemaHandler,
        /,
    ) -> pydantic.json_schema.JsonSchemaValue:
        return handler(core_schema)


class AuthoredTypeProposal(strict_model.StrictModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    value: AuthoredType


class PydanticPrefixAuthoredType:
    __module__ = "pydantic_helpers"

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: pydantic_core.CoreSchema,
        handler: pydantic.GetJsonSchemaHandler,
        /,
    ) -> pydantic.json_schema.JsonSchemaValue:
        return handler(core_schema)


class PydanticPrefixAuthoredTypeProposal(strict_model.StrictModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    value: PydanticPrefixAuthoredType


_T = typing.TypeVar("_T")


class AuthoredGeneric(typing.Generic[_T]):
    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: pydantic_core.CoreSchema,
        handler: pydantic.GetJsonSchemaHandler,
        /,
    ) -> pydantic.json_schema.JsonSchemaValue:
        return handler(core_schema)


class AuthoredGenericProposal(strict_model.StrictModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    value: AuthoredGeneric[int]


class AuthoredMetadata:
    def __get_pydantic_json_schema__(
        self,
        core_schema: pydantic_core.CoreSchema,
        handler: pydantic.GetJsonSchemaHandler,
        /,
    ) -> pydantic.json_schema.JsonSchemaValue:
        return handler(core_schema)


class AuthoredMetadataProposal(strict_model.StrictModel):
    value: typing.Annotated[str, AuthoredMetadata()]


class WithSchemaProposal(strict_model.StrictModel):
    value: typing.Annotated[str, pydantic.WithJsonSchema({"type": "string"})]


class NestedWithSchemaProposal(strict_model.StrictModel):
    values: list[typing.Annotated[str, pydantic.WithJsonSchema({"type": "string"})]]


class UnionWithSchemaProposal(strict_model.StrictModel):
    value: int | typing.Annotated[str, pydantic.WithJsonSchema({"type": "string"})]


class SkipSchemaProposal(strict_model.StrictModel):
    value: pydantic.json_schema.SkipJsonSchema[str]


class NestedSkipSchemaProposal(strict_model.StrictModel):
    values: list[pydantic.json_schema.SkipJsonSchema[str]]


class UnionSkipSchemaProposal(strict_model.StrictModel):
    value: int | pydantic.json_schema.SkipJsonSchema[str]


class ModelExtraProposal(strict_model.StrictModel):
    model_config = pydantic.ConfigDict(extra="forbid", json_schema_extra={})
    value: str


class FieldExtraProposal(strict_model.StrictModel):
    value: str = pydantic.Field(json_schema_extra={})


class ModelTitleProposal(strict_model.StrictModel):
    model_config = pydantic.ConfigDict(extra="forbid", title="Authored")
    value: str


class FieldTitleProposal(strict_model.StrictModel):
    value: str = pydantic.Field(title="Authored")


class NestedFieldTitleProposal(strict_model.StrictModel):
    values: list[typing.Annotated[str, pydantic.Field(title="Authored")]]


class NestedFieldExtraProposal(strict_model.StrictModel):
    values: list[typing.Annotated[str, pydantic.Field(json_schema_extra={})]]


def _model_title_generator(model: type[object]) -> str:
    return model.__name__


def _field_title_generator(
    name: str,
    _field: pydantic.fields.FieldInfo | pydantic.fields.ComputedFieldInfo,
) -> str:
    return name


class ModelTitleGeneratorProposal(strict_model.StrictModel):
    model_config = pydantic.ConfigDict(extra="forbid", model_title_generator=_model_title_generator)
    value: str


class ModelFieldTitleGeneratorProposal(strict_model.StrictModel):
    model_config = pydantic.ConfigDict(extra="forbid", field_title_generator=_field_title_generator)
    value: str


class FieldTitleGeneratorProposal(strict_model.StrictModel):
    value: str = pydantic.Field(field_title_generator=_field_title_generator)


@pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid", title="Authored"))
class AuthoredDataClass:
    label: str


class AuthoredDataClassProposal(strict_model.StrictModel):
    value: AuthoredDataClass


@pydantic.with_config(pydantic.ConfigDict(extra="forbid", json_schema_extra={}))
class AuthoredTypedDict(typing_extensions.TypedDict):
    label: str


class AuthoredTypedDictProposal(strict_model.StrictModel):
    value: AuthoredTypedDict


@dataclasses.dataclass
class PlainDataClass:
    label: str


class PlainDataClassProposal(strict_model.StrictModel):
    value: PlainDataClass


class NestedPlainDataClassProposal(strict_model.StrictModel):
    values: list[PlainDataClass]


WrappedStr = typing.NewType("WrappedStr", str)


class NewTypeProposal(strict_model.StrictModel):
    value: WrappedStr


AliasedStr = typing_extensions.TypeAliasType("AliasedStr", str)


class TypeAliasProposal(strict_model.StrictModel):
    value: AliasedStr


@pytest.mark.parametrize(
    ("proposal_type", "message"),
    (
        (PlainDataClassProposal, "standard-library dataclass 'PlainDataClass'"),
        (NestedPlainDataClassProposal, "standard-library dataclass 'PlainDataClass'"),
        (NewTypeProposal, "NewType 'WrappedStr'"),
        (TypeAliasProposal, "TypeAliasType 'AliasedStr'"),
    ),
)
def test_out_of_dialect_annotation_forms_fail_construction(
    proposal_type: type[pydantic.BaseModel], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        proposal_schema.derive_proposal_schema(proposal_type)


@pytest.mark.parametrize(
    ("proposal_type", "message"),
    (
        (AuthoredModelSchema, "model_json_schema"),
        (InheritedAuthoredModelSchema, "model_json_schema"),
        (AuthoredTypeProposal, "__get_pydantic_json_schema__"),
        (AuthoredGenericProposal, "__get_pydantic_json_schema__"),
        (AuthoredMetadataProposal, "__get_pydantic_json_schema__"),
        (WithSchemaProposal, "WithJsonSchema"),
        (NestedWithSchemaProposal, "WithJsonSchema"),
        (UnionWithSchemaProposal, "WithJsonSchema"),
        (SkipSchemaProposal, "SkipJsonSchema"),
        (NestedSkipSchemaProposal, "SkipJsonSchema"),
        (UnionSkipSchemaProposal, "SkipJsonSchema"),
        (ModelExtraProposal, "model json_schema_extra"),
        (FieldExtraProposal, "field json_schema_extra"),
        (ModelTitleProposal, "authored model title"),
        (FieldTitleProposal, "authored field title"),
        (NestedFieldTitleProposal, "authored field title"),
        (NestedFieldExtraProposal, "field json_schema_extra"),
        (ModelTitleGeneratorProposal, "model_title_generator"),
        (ModelFieldTitleGeneratorProposal, "field_title_generator"),
        (FieldTitleGeneratorProposal, "field title"),
        (AuthoredDataClassProposal, "authored model title"),
        (AuthoredTypedDictProposal, "model json_schema_extra"),
    ),
)
def test_authored_schema_overrides_fail_before_derivation(
    proposal_type: type[pydantic.BaseModel], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        proposal_schema.derive_proposal_schema(proposal_type)


def test_application_module_with_pydantic_prefix_is_not_trusted() -> None:
    assert PydanticPrefixAuthoredType.__module__ == "pydantic_helpers"

    with pytest.raises(ValueError, match="PydanticPrefixAuthoredType.__get_pydantic_json_schema__"):
        proposal_schema.derive_proposal_schema(PydanticPrefixAuthoredTypeProposal)
