"""Define the Operation vocabulary and its bookkeeping identity. @sergent/docs/framework.md
@sergent-py-core/docs/core-class-design-pattern.md"""

from __future__ import annotations

import abc
import typing

import pydantic

import sergent_py_core.identifiers as identifiers
import sergent_py_core.strict_model as strict_model
import sergent_py_core.target as target_values


class OperationTrace(strict_model.StrictModel):
    """Match one Patch Operation to its immutable bookkeeping identity. @sergent/docs/framework.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    op_id: str

    @pydantic.field_validator("op_id")
    @classmethod
    def _op_id_is_op(cls, value: str) -> str:
        """Admit only Operation identifiers."""
        return identifiers.checked_id(value, "op")


class Operation(pydantic.BaseModel, abc.ABC, frozen=True, extra="forbid"):
    """Define an immutable script step with deterministic application hooks. @sergent/docs/framework.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    _op_id: str = pydantic.PrivateAttr(default_factory=lambda: identifiers.new_id("op"))
    call: str

    def __setattr__(self, name: str, value: object) -> None:
        """Preserve the private Operation identity after construction."""
        if name == "_op_id":
            raise TypeError("operation ID is immutable")
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        """Reject deletion of the private Operation identity."""
        if name == "_op_id":
            raise TypeError("operation ID is immutable")
        super().__delattr__(name)

    @property
    def op_id(self) -> str:
        """Expose the immutable Operation bookkeeping identity. @sergent/docs/framework.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        return self._op_id

    def validate_for(
        self,
        scene: typing.Any,
        intent: typing.Any,
        target: target_values.Target,
        /,
    ) -> None:
        """Reject this Operation when inadmissible for the bounded context. @sergent/docs/framework.md
        @sergent-py-core/docs/core-class-design-pattern.md"""

    @abc.abstractmethod
    def apply(
        self,
        scene: typing.Any,
        target: target_values.Target,
        /,
    ) -> typing.Any:
        """Apply this Operation through deterministic Scene behavior. @sergent/docs/framework.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        raise NotImplementedError
