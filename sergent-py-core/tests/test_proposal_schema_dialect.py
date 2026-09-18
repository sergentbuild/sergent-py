from __future__ import annotations

import typing

import pytest

import sergent_py_core.proposals.schema as proposal_schema


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        (
            {"$ref": "#/$defs/NestedValue", "title": "Generated", "default": {}},
            {"$ref": "#/$defs/NestedValue"},
        ),
        (
            {
                "$ref": "#/$defs/NestedValue",
                "description": "Nested value.",
                "title": "Generated",
                "default": {},
            },
            {
                "description": "Nested value.",
                "anyOf": [{"$ref": "#/$defs/NestedValue"}],
            },
        ),
    ),
)
def test_ref_normalization_removes_only_title_and_default_siblings(
    source: dict[str, typing.Any], expected: dict[str, typing.Any]
) -> None:
    deriver = proposal_schema._SchemaDeriver("RefSource")
    assert deriver._normalize_schema(source, "/properties/value") == expected


@pytest.mark.parametrize(
    "source",
    (
        {"$ref": "#/$defs/NestedValue", "pattern": "^[a-z]+$"},
        {
            "$ref": "#/$defs/NestedValue",
            "description": "Nested value.",
            "minLength": 1,
        },
    ),
)
def test_ref_normalization_rejects_nonportable_refinement_siblings(
    source: dict[str, typing.Any],
) -> None:
    deriver = proposal_schema._SchemaDeriver("RefSource")
    with pytest.raises(ValueError) as error:
        deriver._normalize_schema(source, "/properties/value")

    assert "/properties/value" in str(error.value)
    assert "sibling keywords" in str(error.value)


def test_private_canonical_check_accepts_acyclic_and_escaped_local_refs() -> None:
    schema: dict[str, typing.Any] = {
        "$defs": {
            "Leaf/Value~": {"type": "string"},
            "Node": {
                "type": "object",
                "properties": {"leaf": {"$ref": "#/$defs/Leaf~1Value~0"}},
                "required": ["leaf"],
                "additionalProperties": False,
            },
        },
        "type": "object",
        "properties": {"node": {"$ref": "#/$defs/Node"}},
        "required": ["node"],
        "additionalProperties": False,
    }

    canonical = proposal_schema._canonical_proposal_schema("Acyclic", schema)
    assert canonical.json_schema == schema


@pytest.mark.parametrize(
    ("value_schema", "pointer", "message"),
    (
        ({"$ref": "https://example.test/schema"}, "/properties/value/$ref", "#/$defs"),
        ({"$ref": "#/$defs/Missing"}, "/properties/value/$ref", "does not exist"),
        (
            {"$ref": "#/$defs/Leaf", "description": "sibling"},
            "/properties/value",
            "sibling keywords",
        ),
        ({"$ref": "#/$defs/Bad~2Name"}, "/properties/value/$ref", "escaping"),
    ),
)
def test_private_canonical_check_rejects_invalid_references(
    value_schema: dict[str, typing.Any], pointer: str, message: str
) -> None:
    schema: dict[str, typing.Any] = {
        "$defs": {"Leaf": {"type": "string"}},
        "type": "object",
        "properties": {"value": value_schema},
        "required": ["value"],
        "additionalProperties": False,
    }

    with pytest.raises(ValueError) as error:
        proposal_schema._canonical_proposal_schema("InvalidRef", schema)

    rendered = str(error.value)
    assert pointer in rendered
    assert message in rendered


def test_private_canonical_check_rejects_a_root_ref() -> None:
    with pytest.raises(ValueError, match="top-level schema must be an object"):
        proposal_schema._canonical_proposal_schema(
            "RootRef",
            {"$defs": {"Value": {"type": "string"}}, "$ref": "#/$defs/Value"},
        )


def test_private_canonical_check_rejects_duplicate_enum_values() -> None:
    schema: dict[str, typing.Any] = {
        "type": "object",
        "properties": {"value": {"type": "string", "enum": ["same", "same"]}},
        "required": ["value"],
        "additionalProperties": False,
    }

    with pytest.raises(ValueError, match="enum values must be unique"):
        proposal_schema._canonical_proposal_schema("DuplicateEnum", schema)


def test_private_canonical_check_treats_equal_json_numbers_as_duplicate_enum_values() -> None:
    schema: dict[str, typing.Any] = {
        "type": "object",
        "properties": {"value": {"enum": [1, 1.0]}},
        "required": ["value"],
        "additionalProperties": False,
    }

    with pytest.raises(ValueError, match="enum values must be unique"):
        proposal_schema._canonical_proposal_schema("DuplicateNumberEnum", schema)


def test_private_canonical_check_keeps_booleans_distinct_from_json_numbers() -> None:
    schema: dict[str, typing.Any] = {
        "type": "object",
        "properties": {"value": {"enum": [True, 1]}},
        "required": ["value"],
        "additionalProperties": False,
    }

    canonical = proposal_schema._canonical_proposal_schema("BooleanNumberEnum", schema)
    assert canonical.json_schema == schema


def test_private_canonical_check_rejects_non_text_type_with_pointer() -> None:
    schema: dict[str, typing.Any] = {
        "type": "object",
        "properties": {"value": {"type": []}},
        "required": ["value"],
        "additionalProperties": False,
    }

    with pytest.raises(ValueError) as error:
        proposal_schema._canonical_proposal_schema("MalformedType", schema)

    assert "MalformedType schema at /properties/value/type" in str(error.value)
    assert "unsupported type []" in str(error.value)


def test_private_canonical_check_accepts_arbitrarily_large_integer_bounds() -> None:
    huge_bound = 10**1000
    schema: dict[str, typing.Any] = {
        "type": "object",
        "properties": {"value": {"type": "integer", "minimum": huge_bound}},
        "required": ["value"],
        "additionalProperties": False,
    }

    canonical = proposal_schema._canonical_proposal_schema("HugeBound", schema)
    assert canonical.json_schema == schema


@pytest.mark.parametrize(
    ("value_schema", "pointer", "message"),
    (
        ({"type": None}, "/properties/value/type", "unsupported type"),
        ({"description": None, "type": "string"}, "/properties/value/description", "text"),
        ({"enum": None}, "/properties/value/enum", "non-empty array"),
        ({"anyOf": None}, "/properties/value/anyOf", "non-empty array"),
        (
            {"type": "array", "items": {"type": "string"}, "minItems": None},
            "/properties/value/minItems",
            "non-negative",
        ),
        ({"type": "number", "minimum": None}, "/properties/value/minimum", "numeric"),
    ),
)
def test_private_canonical_check_rejects_null_keyword_values(
    value_schema: dict[str, typing.Any], pointer: str, message: str
) -> None:
    schema: dict[str, typing.Any] = {
        "type": "object",
        "properties": {"value": value_schema},
        "required": ["value"],
        "additionalProperties": False,
    }

    with pytest.raises(ValueError) as error:
        proposal_schema._canonical_proposal_schema("NullKeyword", schema)

    rendered = str(error.value)
    assert pointer in rendered
    assert message in rendered


def test_private_canonical_check_rejects_null_definitions() -> None:
    schema: dict[str, typing.Any] = {
        "$defs": None,
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }

    with pytest.raises(ValueError, match=r"/\$defs.*must be an object"):
        proposal_schema._canonical_proposal_schema("NullDefinitions", schema)
