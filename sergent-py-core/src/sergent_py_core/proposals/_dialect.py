"""Validate the closed canonical proposal-schema dialect. @sergent/docs/framework.md
@sergent-py-core/docs/KNOWLEDGE.md"""

from __future__ import annotations

import math
import typing

_ALLOWED_KEYWORDS = frozenset(
    {
        "$defs",
        "$ref",
        "additionalProperties",
        "anyOf",
        "description",
        "enum",
        "items",
        "maximum",
        "maxItems",
        "minimum",
        "minItems",
        "properties",
        "required",
        "type",
    }
)
_SCALAR_TYPES = frozenset({"string", "integer", "number", "boolean", "null"})


def _validate_canonical_schema(proposal_name: str, schema: dict[str, typing.Any], /) -> None:
    """Require one schema to conform to the closed canonical dialect."""
    _DialectValidator(proposal_name).validate(schema)


class _DialectValidator:
    """Own reference and keyword state for one canonical-dialect check."""

    def __init__(self, proposal_name: str) -> None:
        self._proposal_name = proposal_name
        self._definitions: set[str] = set()
        self._references: list[tuple[str, str]] = []
        self._edges: dict[str, list[tuple[str, str]]] = {}

    def validate(self, schema: dict[str, typing.Any]) -> None:
        """Validate the root and every reachable schema node."""
        self._validate_schema(schema, "", None, root=True)
        self._validate_references()

    def _validate_schema(
        self,
        schema: dict[str, typing.Any],
        pointer: str,
        owner_definition: str | None,
        *,
        root: bool = False,
    ) -> None:
        """Validate one schema node against the closed canonical dialect."""
        if any(not isinstance(keyword, str) for keyword in schema):
            self._fail(pointer, "schema keywords must be text")
        unknown = sorted(set(schema) - _ALLOWED_KEYWORDS)
        if unknown:
            self._fail(pointer, f"unsupported keyword {unknown[0]!r}")
        if root and "$ref" in schema:
            self._fail(pointer, "top-level schema must be an object")
        if "$ref" in schema:
            self._validate_ref(schema, pointer, owner_definition)
            return
        if not any(key in schema for key in ("anyOf", "enum", "type")):
            self._fail(pointer, "schema node has no canonical structural form")
        schema_type = schema.get("type")
        if root and "anyOf" in schema:
            self._fail(self._child(pointer, "anyOf"), "top-level anyOf is not supported")
        if root and schema_type != "object":
            self._fail(pointer, "top-level schema must be an object")
        if "type" in schema and (
            not isinstance(schema_type, str)
            or schema_type not in _SCALAR_TYPES | {"object", "array"}
        ):
            self._fail(self._child(pointer, "type"), f"unsupported type {schema_type!r}")
        self._validate_description_and_enum(schema, pointer)
        self._validate_definitions(schema, pointer, root)
        if schema_type == "object":
            self._validate_object(schema, pointer, owner_definition)
        elif any(key in schema for key in ("properties", "required", "additionalProperties")):
            self._fail(pointer, "object keywords require type 'object'")
        if schema_type == "array":
            self._validate_array(schema, pointer, owner_definition)
        elif any(key in schema for key in ("items", "minItems", "maxItems")):
            self._fail(pointer, "array keywords require type 'array'")
        self._validate_numeric_bounds(schema, pointer, schema_type)
        if "anyOf" in schema:
            any_of = schema["anyOf"]
            if not isinstance(any_of, list) or not any_of:
                self._fail(self._child(pointer, "anyOf"), "anyOf must be a non-empty array")
            for index, child in enumerate(any_of):
                child_pointer = self._child(self._child(pointer, "anyOf"), str(index))
                if not isinstance(child, dict):
                    self._fail(child_pointer, "schema node must be an object")
                self._validate_schema(child, child_pointer, owner_definition)

    def _validate_ref(
        self,
        schema: dict[str, typing.Any],
        pointer: str,
        owner_definition: str | None,
    ) -> None:
        """Record one ref-only local definition edge for resolution checks."""
        if set(schema) != {"$ref"}:
            self._fail(pointer, "$ref nodes cannot have sibling keywords")
        reference = schema["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
            self._fail(self._child(pointer, "$ref"), "reference must use #/$defs/...")
        encoded_target = reference.removeprefix("#/$defs/")
        if not encoded_target or "/" in encoded_target:
            self._fail(self._child(pointer, "$ref"), "reference must name one local definition")
        target = self._decode_pointer_token(encoded_target, self._child(pointer, "$ref"))
        ref_pointer = self._child(pointer, "$ref")
        self._references.append((target, ref_pointer))
        if owner_definition is not None:
            self._edges.setdefault(owner_definition, []).append((target, ref_pointer))

    def _validate_definitions(
        self, schema: dict[str, typing.Any], pointer: str, root: bool
    ) -> None:
        """Validate root-owned local definitions and remember their names."""
        if "$defs" not in schema:
            return
        definitions = schema["$defs"]
        definitions_pointer = self._child(pointer, "$defs")
        if not root:
            self._fail(definitions_pointer, "$defs is allowed only at the root")
        if not isinstance(definitions, dict):
            self._fail(definitions_pointer, "$defs must be an object")
        for name, child in definitions.items():
            if not isinstance(name, str) or not name:
                self._fail(definitions_pointer, "definition names must be non-empty text")
            def_pointer = self._child(definitions_pointer, name)
            if not isinstance(child, dict):
                self._fail(def_pointer, "schema node must be an object")
            self._definitions.add(name)
            self._validate_schema(child, def_pointer, name)

    def _validate_object(
        self,
        schema: dict[str, typing.Any],
        pointer: str,
        owner_definition: str | None,
    ) -> None:
        """Require one closed object with every property exactly once in required."""
        properties = schema.get("properties")
        required = schema.get("required")
        if schema.get("additionalProperties") is not False:
            self._fail(
                self._child(pointer, "additionalProperties"),
                "object must set additionalProperties to false",
            )
        properties_pointer = self._child(pointer, "properties")
        if not isinstance(properties, dict):
            self._fail(properties_pointer, "object properties must be an object")
        if required != list(properties):
            self._fail(self._child(pointer, "required"), "required must list every property once")
        for name, child in properties.items():
            if not isinstance(name, str):
                self._fail(properties_pointer, "property names must be text")
            child_pointer = self._child(properties_pointer, name)
            if not isinstance(child, dict):
                self._fail(child_pointer, "property schema must be an object")
            self._validate_schema(child, child_pointer, owner_definition)

    def _validate_array(
        self,
        schema: dict[str, typing.Any],
        pointer: str,
        owner_definition: str | None,
    ) -> None:
        """Require typed items and valid inclusive item-count bounds."""
        items = schema.get("items")
        if not isinstance(items, dict):
            self._fail(self._child(pointer, "items"), "array items must be a schema object")
        self._validate_schema(items, self._child(pointer, "items"), owner_definition)
        bounds: dict[str, int] = {}
        for keyword in ("minItems", "maxItems"):
            if keyword in schema:
                value = schema[keyword]
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    self._fail(self._child(pointer, keyword), f"{keyword} must be non-negative")
                bounds[keyword] = value
        if bounds.get("minItems", 0) > bounds.get("maxItems", math.inf):
            self._fail(pointer, "minItems cannot exceed maxItems")

    def _validate_numeric_bounds(
        self, schema: dict[str, typing.Any], pointer: str, schema_type: object
    ) -> None:
        """Require finite inclusive bounds only on numeric schema nodes."""
        bounds: dict[str, int | float] = {}
        for keyword in ("minimum", "maximum"):
            if keyword in schema:
                value = schema[keyword]
                if (
                    schema_type not in ("integer", "number")
                    or not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or isinstance(value, float)
                    and not math.isfinite(value)
                ):
                    self._fail(self._child(pointer, keyword), f"{keyword} must be numeric")
                bounds[keyword] = value
        if bounds.get("minimum", -math.inf) > bounds.get("maximum", math.inf):
            self._fail(pointer, "minimum cannot exceed maximum")

    def _validate_description_and_enum(self, schema: dict[str, typing.Any], pointer: str) -> None:
        """Require descriptions and enum members to be JSON scalar values."""
        if "description" in schema and not isinstance(schema["description"], str):
            self._fail(self._child(pointer, "description"), "description must be text")
        if "enum" not in schema:
            return
        values = schema["enum"]
        if not isinstance(values, list) or not values:
            self._fail(self._child(pointer, "enum"), "enum must be a non-empty array")
        seen: set[tuple[str, object]] = set()
        schema_type = schema.get("type")
        for index, value in enumerate(values):
            scalar = value is None or isinstance(value, (str, int, float, bool))
            if not scalar or isinstance(value, float) and not math.isfinite(value):
                enum_pointer = self._child(self._child(pointer, "enum"), str(index))
                self._fail(enum_pointer, "enum values must be JSON scalars")
            identity = self._enum_identity(value)
            if identity in seen:
                self._fail(self._child(pointer, "enum"), "enum values must be unique")
            seen.add(identity)
            if schema_type in _SCALAR_TYPES and not self._enum_matches_type(value, schema_type):
                self._fail(self._child(pointer, "enum"), "enum value does not match its type")
        if schema_type in ("object", "array"):
            self._fail(self._child(pointer, "enum"), "object and array enums are not supported")

    def _validate_references(self) -> None:
        """Reject dangling and cyclic definition references."""
        for target, pointer in self._references:
            if target not in self._definitions:
                self._fail(pointer, f"reference target {target!r} does not exist")
        visited: set[str] = set()
        visiting: set[str] = set()
        for name in sorted(self._definitions):
            self._walk_definition(name, visited, visiting)

    def _walk_definition(self, name: str, visited: set[str], visiting: set[str]) -> None:
        """Walk definition edges once and fail at the edge that closes a cycle."""
        if name in visited:
            return
        visiting.add(name)
        for target, pointer in self._edges.get(name, []):
            if target in visiting:
                self._fail(pointer, f"recursive reference to {target!r} is not supported")
            self._walk_definition(target, visited, visiting)
        visiting.remove(name)
        visited.add(name)

    def _fail(self, pointer: str, message: str) -> typing.NoReturn:
        """Raise one proposal-named JSON-pointer diagnostic."""
        location = pointer or "/"
        raise ValueError(f"{self._proposal_name} schema at {location}: {message}")

    def _decode_pointer_token(self, encoded: str, pointer: str) -> str:
        """Decode one exact JSON Pointer token or reject malformed escaping."""
        index = 0
        while index < len(encoded):
            if encoded[index] == "~":
                if index + 1 == len(encoded) or encoded[index + 1] not in "01":
                    self._fail(pointer, "reference contains invalid JSON Pointer escaping")
                index += 2
            else:
                index += 1
        return encoded.replace("~1", "/").replace("~0", "~")

    @staticmethod
    def _enum_matches_type(value: object, schema_type: object) -> bool:
        """Return whether one enum scalar matches an explicit scalar type."""
        if schema_type == "string":
            return isinstance(value, str)
        if schema_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if schema_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if schema_type == "boolean":
            return isinstance(value, bool)
        return value is None

    @staticmethod
    def _enum_identity(value: object) -> tuple[str, object]:
        """Return one JSON-aware scalar identity for enum uniqueness."""
        if value is None:
            return "null", value
        if isinstance(value, bool):
            return "boolean", value
        if isinstance(value, (int, float)):
            return "number", value
        return "string", value

    @staticmethod
    def _child(pointer: str, token: str) -> str:
        """Append one escaped token to a JSON pointer."""
        escaped = token.replace("~", "~0").replace("/", "~1")
        return f"{pointer}/{escaped}" if pointer else f"/{escaped}"
