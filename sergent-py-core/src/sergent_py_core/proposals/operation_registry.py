"""Derive model-facing artifacts from a closed Operation set. @sergent/docs/framework.md
@sergent-py-core/docs/core-class-design-pattern.md"""

from __future__ import annotations

import collections.abc as cabc
import copy
import inspect
import typing

import pydantic

import sergent_py_core.model_calls as model_calls
import sergent_py_core.operation as operation
import sergent_py_core.plan as plan
import sergent_py_core.proposals.schema as proposal_schema


class OperationRegistry:
    """Own one closed Operation vocabulary and its derived artifacts. @sergent/docs/framework.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    def __init__(self, operation_types: cabc.Iterable[type[operation.Operation]]) -> None:
        """Register a non-empty exact Operation set. @sergent/docs/trust-boundaries.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        operation_types_tuple = tuple(operation_types)
        if not operation_types_tuple:
            raise ValueError("operation registry requires at least one Operation type")
        operation_by_call: dict[str, type[operation.Operation]] = {}
        operation_schemas: list[model_calls.ProposalSchema] = []
        for operation_type in operation_types_tuple:
            try:
                call = self._register_operation_type(operation_by_call, operation_type)
            except ValueError as exc:
                known_call = self._known_call(operation_type)
                context = "" if known_call is None else f" (call={known_call!r})"
                raise ValueError(f"{operation_type.__name__}{context}: {exc}") from exc
            try:
                branch = proposal_schema.derive_proposal_schema(operation_type)
                self._validate_call_schema(operation_type, call, branch)
            except TypeError as exc:
                raise TypeError(f"{operation_type.__name__} (call={call!r}): {exc}") from exc
            except ValueError as exc:
                raise ValueError(f"{operation_type.__name__} (call={call!r}): {exc}") from exc
            operation_schemas.append(branch)
        self._operation_by_call = operation_by_call
        self._plan_definitions, self._branch_names = self._plan_components(operation_schemas)

    def plan_proposal_schema(self, max_operations: int | None, /) -> model_calls.ProposalSchema:
        """Compose the bounded Plan envelope from cached canonical branches. @sergent/docs/framework.md
        @sergent-py-core/docs/KNOWLEDGE.md"""
        _validate_max_operations(max_operations)
        definitions = copy.deepcopy(self._plan_definitions)
        branches = [{"$ref": self._definition_ref(name)} for name in self._branch_names]

        items: dict[str, typing.Any]
        if len(branches) == 1:
            items = branches[0]
        else:
            items = {"anyOf": branches}
        operations_schema: dict[str, typing.Any] = {
            "type": "array",
            "items": items,
            "minItems": 1,
        }
        if max_operations is not None:
            operations_schema["maxItems"] = max_operations
        schema: dict[str, typing.Any] = {
            "$defs": definitions,
            "type": "object",
            "properties": {"operations": operations_schema},
            "required": ["operations"],
            "additionalProperties": False,
        }
        return proposal_schema._canonical_proposal_schema(plan.PlanProposal.__name__, schema)

    def _plan_components(
        self, operation_schemas: cabc.Iterable[model_calls.ProposalSchema]
    ) -> tuple[dict[str, typing.Any], tuple[str, ...]]:
        """Lift cached branches and validate deterministic definition collisions."""
        collected: dict[str, tuple[dict[str, typing.Any], type[operation.Operation], str]] = {}
        branch_names: list[str] = []
        for branch in operation_schemas:
            branch_schema = copy.deepcopy(branch.json_schema)
            nested_definitions = branch_schema.pop("$defs", {})
            call = branch_schema["properties"]["call"]["enum"][0]
            operation_type = self._operation_by_call[call]
            name_map = {name: name for name in (*nested_definitions, branch.name)}
            for name, body in nested_definitions.items():
                rewritten = self._rewrite_local_refs(body, name_map)
                self._collect_definition(collected, name, rewritten, operation_type, call)
            rewritten_branch = self._rewrite_local_refs(branch_schema, name_map)
            self._collect_definition(collected, branch.name, rewritten_branch, operation_type, call)
            branch_names.append(branch.name)
        definitions = {name: collected[name][0] for name in sorted(collected)}
        return definitions, tuple(branch_names)

    def decode_plan_proposal(
        self,
        payload: dict[str, typing.Any],
        /,
        *,
        max_operations: int | None = None,
    ) -> plan.PlanProposal:
        """Decode one raw Plan envelope through this registry. @sergent/docs/framework.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        _validate_max_operations(max_operations)
        expected_keys = {"operations"}
        payload_keys = set(payload)
        if payload_keys != expected_keys:
            unknown_keys = sorted(payload_keys - expected_keys)
            if unknown_keys:
                raise ValueError(f"plan proposal has unknown top-level keys: {unknown_keys!r}")
            raise ValueError("plan proposal requires exactly the 'operations' key")

        operation_payloads = payload["operations"]
        if not isinstance(operation_payloads, list):
            raise ValueError("operations must be a list")
        if max_operations is not None and len(operation_payloads) > max_operations:
            raise ValueError(f"operations exceed configured maximum of {max_operations}")

        decoded_operations: list[operation.Operation] = []
        for index, item in enumerate(operation_payloads):
            call = item.get("call") if isinstance(item, dict) else None
            try:
                if not isinstance(item, dict):
                    raise ValueError("operation must be an object")
                decoded_operations.append(self._decode_operation(item))
            except ValueError as exc:
                msg = f"operation {index} (call={call!r}): {exc}"
                raise ValueError(msg) from exc

        try:
            return plan.PlanProposal(operations=decoded_operations)
        except pydantic.ValidationError as exc:
            raise ValueError(f"invalid Plan proposal: {exc}") from exc

    def _decode_operation(self, payload: dict[str, typing.Any], /) -> operation.Operation:
        """Decode one raw object as its exact registered type. @sergent/docs/framework.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        call = payload.get("call")
        if not isinstance(call, str):
            raise ValueError("operation call must be a string")
        operation_type = self._operation_by_call.get(call)
        if operation_type is None:
            raise ValueError(f"unknown operation call: {call!r}")
        return operation_type.model_validate(payload)

    @staticmethod
    def _register_operation_type(
        operation_by_call: dict[str, type[operation.Operation]],
        operation_type: type[operation.Operation],
    ) -> str:
        """Register one concrete Operation type under its declared call."""
        if not isinstance(operation_type, type) or not issubclass(
            operation_type, operation.Operation
        ):
            raise TypeError("operation type must be an Operation subclass")
        if inspect.isabstract(operation_type):
            raise TypeError(
                f"{operation_type.__name__}: operation type must be an exact concrete Operation class"
            )
        call = _declared_call(operation_type)
        if call in operation_by_call:
            first = operation_by_call[call]
            msg = (
                f"duplicate operation call {call!r}: "
                + f"{first.__name__} and {operation_type.__name__}"
            )
            raise ValueError(msg)
        operation_by_call[call] = operation_type
        return call

    @staticmethod
    def _validate_call_schema(
        operation_type: type[operation.Operation],
        call: str,
        branch: model_calls.ProposalSchema,
    ) -> None:
        """Require the exact provider-visible fixed call discriminator."""
        properties = branch.json_schema["properties"]
        call_schema = properties.get("call")
        required = branch.json_schema["required"]
        if (
            call_schema is None
            or call_schema.get("type") != "string"
            or call_schema.get("enum") != [call]
            or "call" not in required
        ):
            msg = f"{operation_type.__name__} schema at /properties/call: invalid discriminator"
            raise ValueError(msg)

    @staticmethod
    def _known_call(operation_type: type[operation.Operation]) -> str | None:
        """Return a usable default discriminator for construction diagnostics."""
        field = operation_type.model_fields.get("call")
        if field is None or not isinstance(field.default, str) or not field.default:
            return None
        return field.default

    @classmethod
    def _rewrite_local_refs(cls, value: typing.Any, name_map: dict[str, str]) -> typing.Any:
        """Rewrite branch-local definition references for proposal-root lifting."""
        if isinstance(value, dict):
            rewritten: dict[str, typing.Any] = {}
            for key, child in value.items():
                if key == "$ref":
                    local_name = cls._definition_name(child)
                    rewritten[key] = cls._definition_ref(name_map[local_name])
                else:
                    rewritten[key] = cls._rewrite_local_refs(child, name_map)
            return rewritten
        if isinstance(value, list):
            return [cls._rewrite_local_refs(child, name_map) for child in value]
        return copy.deepcopy(value)

    @staticmethod
    def _definition_name(reference: str, /) -> str:
        """Decode one already-validated local definition reference."""
        encoded = reference.removeprefix("#/$defs/")
        return encoded.replace("~1", "/").replace("~0", "~")

    @staticmethod
    def _definition_ref(name: str, /) -> str:
        """Encode one local definition name as an exact JSON Pointer reference."""
        encoded = name.replace("~", "~0").replace("/", "~1")
        return f"#/$defs/{encoded}"

    @staticmethod
    def _collect_definition(
        collected: dict[str, tuple[dict[str, typing.Any], type[operation.Operation], str]],
        name: str,
        body: dict[str, typing.Any],
        source: type[operation.Operation],
        call: str,
    ) -> None:
        """Share equal definitions and reject same-name structural collisions."""
        existing = collected.get(name)
        if existing is not None and not _json_values_equal(existing[0], body):
            first_source = existing[1]
            first_call = existing[2]
            pointer_name = name.replace("~", "~0").replace("/", "~1")
            msg = (
                f"schema at /$defs/{pointer_name}: conflicting definition {name!r} from "
                + f"{first_source.__name__} (call={first_call!r}) and "
                + f"{source.__name__} (call={call!r})"
            )
            raise ValueError(msg)
        if existing is None:
            collected[name] = (body, source, call)


def _declared_call(operation_type: type[operation.Operation]) -> str:
    """Return one Operation type's fixed single-value call literal."""
    field = operation_type.model_fields["call"]
    values = typing.get_args(field.annotation)
    if (
        typing.get_origin(field.annotation) is not typing.Literal
        or len(values) != 1
        or not isinstance(values[0], str)
        or not values[0]
    ):
        msg = "schema at /properties/call: call must be a single-value string Literal"
        raise ValueError(msg)
    if field.default != values[0]:
        msg = f"schema at /properties/call: call must default to {values[0]!r}"
        raise ValueError(msg)
    if (
        field.alias is not None
        or field.validation_alias is not None
        or field.serialization_alias is not None
    ):
        msg = "schema at /properties/call: call aliases are not allowed"
        raise ValueError(msg)
    return values[0]


def _validate_max_operations(max_operations: int | None) -> None:
    """Require an optional positive non-boolean Plan bound."""
    if max_operations is None:
        return
    if not isinstance(max_operations, int) or isinstance(max_operations, bool):
        raise TypeError("max_operations must be a positive integer or None")
    if max_operations <= 0:
        raise ValueError("max_operations must be positive")


def _json_values_equal(left: typing.Any, right: typing.Any, /) -> bool:
    """Compare JSON data with numeric equality and distinct booleans."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _json_values_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_values_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return type(left) is type(right) and left == right
