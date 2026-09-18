"""Derive the canonical schema for one typed proposal. @sergent/docs/framework.md
@sergent-py-core/docs/KNOWLEDGE.md"""

from __future__ import annotations

import collections.abc as cabc
import copy
import dataclasses
import typing

import pydantic
import pydantic.dataclasses
import pydantic.fields
import pydantic.json_schema
import typing_extensions

import sergent_py_core.model_calls as model_calls
import sergent_py_core.proposals._dialect as proposal_schema_dialect

_REMOVED_KEYWORDS = frozenset(
    {
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
)


def derive_proposal_schema(
    proposal_type: type[pydantic.BaseModel], /
) -> model_calls.ProposalSchema:
    """Derive one closed canonical schema from an exact proposal class. @sergent/docs/framework.md
    @sergent-py-core/docs/KNOWLEDGE.md"""
    if not isinstance(proposal_type, type) or not issubclass(proposal_type, pydantic.BaseModel):
        raise TypeError("proposal type must be a Pydantic model class")
    return _SchemaDeriver(proposal_type.__name__).derive(proposal_type)


def _canonical_proposal_schema(
    name: str, json_schema: dict[str, typing.Any], /
) -> model_calls.ProposalSchema:
    """Validate and construct one framework-composed canonical schema."""
    return _SchemaDeriver(name).canonical(json_schema)


class _SchemaDeriver:
    """Own annotation checks, exact normalization, and dialect conformance."""

    def __init__(self, proposal_name: str) -> None:
        self._proposal_name = proposal_name
        self._seen_models: set[type[pydantic.BaseModel]] = set()
        self._seen_structures: set[type[object]] = set()

    def derive(self, proposal_type: type[pydantic.BaseModel]) -> model_calls.ProposalSchema:
        """Build and validate the schema after rejecting authored overrides."""
        self._visit_model(proposal_type, "")
        try:
            source = proposal_type.model_json_schema(mode="validation", by_alias=True)
        except Exception as exc:  # noqa: BLE001 - application schema hooks fail construction.
            self._fail("", f"validation schema derivation raised {type(exc).__name__}: {exc}")
        normalized = self._normalize_schema(source, "")
        return self.canonical(normalized)

    def canonical(self, schema: dict[str, typing.Any]) -> model_calls.ProposalSchema:
        """Validate one already-normalized schema and construct its strict value."""
        proposal_schema_dialect._validate_canonical_schema(self._proposal_name, schema)
        return model_calls.ProposalSchema(
            name=self._proposal_name,
            json_schema=schema,
        )

    def _visit_model(self, model_type: type[pydantic.BaseModel], pointer: str) -> None:
        """Reject unsupported annotations and model or field schema authorship."""
        if model_type in self._seen_models:
            return
        self._seen_models.add(model_type)
        self._reject_type_overrides(model_type, pointer)
        self._visit_config(model_type.model_config, pointer)
        self._visit_fields(model_type.model_fields, model_type.model_config, pointer)

    def _visit_config(self, config: cabc.Mapping[str, object], pointer: str) -> None:
        """Reject schema authorship in one reachable model configuration."""
        for setting in ("title", "model_title_generator", "field_title_generator"):
            if config.get(setting) is not None:
                self._fail(pointer, f"authored model {setting} is not supported")
        if config.get("json_schema_extra") is not None:
            self._fail(pointer, "model json_schema_extra is not supported")

    def _visit_fields(
        self,
        fields: cabc.Mapping[str, pydantic.fields.FieldInfo],
        config: cabc.Mapping[str, object],
        pointer: str,
    ) -> None:
        """Validate provider keys and authorship across one structured field map."""
        provider_keys: dict[str, str] = {}
        for field_name, field in fields.items():
            validation_alias = self._validation_alias(field_name, field, config, pointer)
            if validation_alias is not None and not isinstance(validation_alias, str):
                invalid_pointer = self._child(self._child(pointer, "properties"), field_name)
                self._fail(invalid_pointer, "field uses an alias path or choices")
            provider_key = field_name if validation_alias is None else validation_alias
            field_pointer = self._child(self._child(pointer, "properties"), provider_key)
            prior = provider_keys.get(provider_key)
            if prior is not None:
                self._fail(field_pointer, f"provider key duplicates field {prior!r}")
            provider_keys[provider_key] = field_name
            if validation_alias is not None and config.get("validate_by_alias") is False:
                self._fail(field_pointer, "validation alias is not accepted by model_validate")
            if field.title is not None or field.field_title_generator is not None:
                self._fail(field_pointer, "authored field title is not supported")
            if field.json_schema_extra is not None:
                self._fail(field_pointer, "field json_schema_extra is not supported")
            self._visit_annotation(field.annotation, field_pointer)
            for metadata in field.metadata:
                self._visit_annotation(metadata, field_pointer)

    def _validation_alias(
        self,
        field_name: str,
        field: pydantic.fields.FieldInfo,
        config: cabc.Mapping[str, object],
        pointer: str,
    ) -> str | pydantic.AliasPath | pydantic.AliasChoices | None:
        """Resolve the validation key Pydantic emits for one structured field."""
        if field.validation_alias is not None:
            return field.validation_alias
        if field.alias is not None:
            return field.alias
        generator = config.get("alias_generator")
        if generator is None:
            return None
        if isinstance(generator, pydantic.AliasGenerator):
            alias, validation_alias, _serialization_alias = generator.generate_aliases(field_name)
            return validation_alias if validation_alias is not None else alias
        if callable(generator):
            generated = generator(field_name)
            if not isinstance(generated, str):
                self._fail(pointer, "alias_generator must return text")
            return generated
        self._fail(pointer, "alias_generator must be callable")

    def _visit_structure(self, structure_type: type[object], pointer: str) -> None:
        """Traverse one reachable Pydantic dataclass or typed dictionary."""
        if structure_type in self._seen_structures:
            return
        self._seen_structures.add(structure_type)
        self._visit_structure_bases(structure_type)
        config_value = getattr(structure_type, "__pydantic_config__", {})
        if not isinstance(config_value, cabc.Mapping):
            self._fail(pointer, "model configuration must be a mapping")
        self._visit_config(config_value, pointer)
        if pydantic.dataclasses.is_pydantic_dataclass(structure_type):
            fields = getattr(structure_type, "__pydantic_fields__", None)
            if not isinstance(fields, cabc.Mapping):
                self._fail(pointer, "Pydantic dataclass fields are unavailable")
            self._visit_fields(fields, config_value, pointer)
            return
        try:
            annotations = typing.get_type_hints(structure_type, include_extras=True)
        except Exception as exc:  # noqa: BLE001 - unresolved application annotations fail wiring.
            self._fail(pointer, f"field annotation resolution raised {type(exc).__name__}: {exc}")
        fields = {
            name: pydantic.fields.FieldInfo.from_annotation(annotation)
            for name, annotation in annotations.items()
        }
        self._visit_fields(fields, config_value, pointer)

    def _visit_structure_bases(self, structure_type: type[object]) -> None:
        """Traverse inherited structured types hidden by TypedDict metaclasses."""
        direct_bases = structure_type.__bases__
        original_bases = vars(structure_type).get("__orig_bases__", ())
        for base in (*direct_bases, *original_bases):
            origin = typing.get_origin(base)
            base_type = origin if isinstance(origin, type) else base
            if not isinstance(base_type, type) or base_type is structure_type:
                continue
            if pydantic.dataclasses.is_pydantic_dataclass(
                base_type
            ) or typing_extensions.is_typeddict(base_type):
                self._visit_structure(base_type, self._child("/$defs", base_type.__name__))

    def _visit_annotation(self, annotation: object, pointer: str) -> None:
        """Traverse every type, generic argument, and Annotated metadata item."""
        if isinstance(annotation, pydantic.json_schema.WithJsonSchema):
            self._fail(pointer, f"{type(annotation).__name__} is not supported")
        annotation_type = type(annotation)
        if (
            annotation_type.__module__ == "pydantic.json_schema"
            and annotation_type.__name__ == "SkipJsonSchema"
        ):
            self._fail(pointer, "SkipJsonSchema is not supported")
        wrapper_message = self._out_of_dialect_wrapper(annotation)
        if wrapper_message is not None:
            self._fail(pointer, wrapper_message)
        self._reject_type_overrides(annotation_type, pointer)
        if isinstance(annotation, pydantic.fields.FieldInfo):
            if annotation.title is not None or annotation.field_title_generator is not None:
                self._fail(pointer, "authored field title is not supported")
            if annotation.json_schema_extra is not None:
                self._fail(pointer, "field json_schema_extra is not supported")
        if isinstance(annotation, type):
            self._reject_type_overrides(annotation, pointer)
            if issubclass(annotation, pydantic.BaseModel):
                self._visit_model(annotation, self._child("/$defs", annotation.__name__))
            elif pydantic.dataclasses.is_pydantic_dataclass(
                annotation
            ) or typing_extensions.is_typeddict(annotation):
                self._visit_structure(annotation, self._child("/$defs", annotation.__name__))
            elif dataclasses.is_dataclass(annotation):
                self._fail(
                    pointer,
                    f"standard-library dataclass {annotation.__name__!r}"
                    + " is outside the canonical dialect",
                )
            return
        origin = typing.get_origin(annotation)
        if isinstance(origin, type):
            self._reject_type_overrides(origin, pointer)
            if issubclass(origin, pydantic.BaseModel):
                self._visit_model(origin, self._child("/$defs", origin.__name__))
            elif pydantic.dataclasses.is_pydantic_dataclass(
                origin
            ) or typing_extensions.is_typeddict(origin):
                self._visit_structure(origin, self._child("/$defs", origin.__name__))
            elif dataclasses.is_dataclass(origin):
                self._fail(
                    pointer,
                    f"standard-library dataclass {origin.__name__!r}"
                    + " is outside the canonical dialect",
                )
        if isinstance(annotation, typing.TypeVar):
            if annotation.__bound__ is not None:
                self._visit_annotation(annotation.__bound__, pointer)
            for constraint in annotation.__constraints__:
                self._visit_annotation(constraint, pointer)
        for argument in typing.get_args(annotation):
            self._visit_annotation(argument, pointer)

    def _reject_type_overrides(self, annotation_type: type[object], pointer: str) -> None:
        """Reject only authored JSON-schema methods on reachable application types."""
        for owner in annotation_type.__mro__:
            if owner.__module__ == "pydantic" or owner.__module__.startswith("pydantic."):
                continue
            namespace = vars(owner)
            for method_name in ("__get_pydantic_json_schema__", "model_json_schema"):
                if method_name in namespace:
                    self._fail(pointer, f"{owner.__name__}.{method_name} is not supported")

    @staticmethod
    def _out_of_dialect_wrapper(annotation: object) -> str | None:
        """Name one typing wrapper whose target the traversal cannot inspect."""
        wrapper_type = type(annotation)
        if wrapper_type.__module__ not in ("typing", "typing_extensions"):
            return None
        if wrapper_type.__name__ not in ("NewType", "TypeAliasType"):
            return None
        name = getattr(annotation, "__name__", wrapper_type.__name__)
        return f"{wrapper_type.__name__} {str(name)!r} is outside the canonical dialect"

    def _normalize_schema(
        self, schema: dict[str, typing.Any], pointer: str
    ) -> dict[str, typing.Any]:
        """Apply only the closed normalization whitelist to one schema node."""
        if "$ref" in schema:
            siblings = set(schema) - {"$ref", "title", "default"}
            if not siblings:
                return {"$ref": copy.deepcopy(schema["$ref"])}
            if siblings == {"description"}:
                return {
                    "description": copy.deepcopy(schema["description"]),
                    "anyOf": [{"$ref": copy.deepcopy(schema["$ref"])}],
                }
            self._fail(pointer, "$ref nodes cannot have sibling keywords")
        if "const" in schema and "enum" in schema:
            self._fail(pointer, "const and enum cannot appear together")
        normalized: dict[str, typing.Any] = {}
        for keyword, value in schema.items():
            if keyword in _REMOVED_KEYWORDS:
                continue
            if keyword == "const":
                normalized["enum"] = [copy.deepcopy(value)]
            elif keyword in ("properties", "$defs") and isinstance(value, dict):
                container_pointer = self._child(pointer, keyword)
                normalized[keyword] = {
                    name: self._normalize_schema(child, self._child(container_pointer, name))
                    if isinstance(child, dict)
                    else copy.deepcopy(child)
                    for name, child in value.items()
                }
            elif keyword == "items" and isinstance(value, dict):
                normalized[keyword] = self._normalize_schema(value, self._child(pointer, keyword))
            elif keyword == "anyOf" and isinstance(value, list):
                any_of_pointer = self._child(pointer, keyword)
                normalized[keyword] = [
                    self._normalize_schema(child, self._child(any_of_pointer, str(index)))
                    if isinstance(child, dict)
                    else copy.deepcopy(child)
                    for index, child in enumerate(value)
                ]
            else:
                normalized[keyword] = copy.deepcopy(value)
        if normalized.get("type") == "object" and isinstance(normalized.get("properties"), dict):
            properties = normalized["properties"]
            required = normalized.get("required")
            if required is not None:
                valid_required = (
                    isinstance(required, list)
                    and all(isinstance(item, str) for item in required)
                    and len(required) == len(set(required))
                    and set(required).issubset(properties)
                )
                if not valid_required:
                    self._fail(
                        self._child(pointer, "required"),
                        "source required must contain unique declared properties",
                    )
            normalized["required"] = list(properties)
        return normalized

    def _fail(self, pointer: str, message: str) -> typing.NoReturn:
        """Raise one proposal-named JSON-pointer diagnostic."""
        location = pointer or "/"
        raise ValueError(f"{self._proposal_name} schema at {location}: {message}")

    @staticmethod
    def _child(pointer: str, token: str) -> str:
        """Append one escaped token to a JSON pointer."""
        escaped = token.replace("~", "~0").replace("/", "~1")
        return f"{pointer}/{escaped}" if pointer else f"/{escaped}"
