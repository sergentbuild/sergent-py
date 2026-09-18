"""Capture reachable proposal configuration for one runtime. @sergent/docs/execution-model.md
@sergent-py-runtime/docs/KNOWLEDGE.md"""

from __future__ import annotations

import dataclasses
import typing

import sergent_py_core.model_calls as core_model_calls
import sergent_py_core.proposals.operation_registry as core_operation_registry
import sergent_py_core.proposals.schema as core_proposal_schema
import sergent_py_core.recipe as core_recipe
import sergent_py_runtime.proposals.intent_proposals as runtime_intent_proposals


@dataclasses.dataclass(frozen=True)
class _ProposalContract:
    """Retain the exact proposal types, bounds, and schemas for one runtime.
    @sergent/docs/execution-model.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    intent_proposal_type: type[typing.Any]
    operation_registry: core_operation_registry.OperationRegistry | None
    max_operations: int | None
    intent_schema: core_model_calls.ProposalSchema | None
    plan_schema: core_model_calls.ProposalSchema | None


def _capture(
    recipe: core_recipe.SergentRecipe[typing.Any, typing.Any, typing.Any], /
) -> _ProposalContract:
    """Capture and validate every proposal phase reachable from one recipe.
    @sergent/docs/execution-model.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    intent_proposal_type = recipe.intent_proposal_type
    operation_registry = recipe.operation_registry
    max_operations = recipe.max_operations

    if operation_registry is None:
        if max_operations is not None:
            raise ValueError("max_operations requires operation_registry")
        plan_schema = None
    else:
        plan_schema = operation_registry.plan_proposal_schema(max_operations)

    if intent_proposal_type is runtime_intent_proposals.IntentProposal_PassThrough:
        intent_schema = None
    else:
        context = f"{type(recipe).__name__} Intent proposal " + f"{intent_proposal_type.__name__}"
        try:
            intent_schema = core_proposal_schema.derive_proposal_schema(intent_proposal_type)
        except TypeError as exc:
            raise TypeError(f"{context}: {exc}") from exc
        except ValueError as exc:
            raise ValueError(f"{context}: {exc}") from exc

    return _ProposalContract(
        intent_proposal_type=intent_proposal_type,
        operation_registry=operation_registry,
        max_operations=max_operations,
        intent_schema=intent_schema,
        plan_schema=plan_schema,
    )
