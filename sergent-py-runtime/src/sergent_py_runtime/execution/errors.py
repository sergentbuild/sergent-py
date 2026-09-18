"""Define structured runtime execution failures. @sergent/docs/execution-model.md
@sergent-py-runtime/docs/KNOWLEDGE.md"""

from __future__ import annotations


class _ProposalSchemaError(ValueError):
    """Report a failed typed proposal crossing. @sergent/docs/trust-boundaries.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""


class _OperationAdmissibilityError(ValueError):
    """Report an Operation rejected for its bounded context. @sergent/docs/execution-model.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    def __init__(self, message: str, metadata: dict[str, object]) -> None:
        super().__init__(message)
        self.metadata = dict(metadata)


class PatchValidationError(ValueError):
    """Reject a compiled Patch with an unsafe envelope. @sergent/docs/framework.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    def __init__(
        self,
        message: str,
        *,
        metadata: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.metadata = dict(metadata or {})


class StalePatchError(PatchValidationError):
    """Reject a Patch whose base revision is stale. @sergent/docs/framework.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    def __init__(
        self,
        message: str,
        *,
        base_revision: int,
        current_revision: int,
    ) -> None:
        super().__init__(message)
        self.base_revision = base_revision
        self.current_revision = current_revision


class DryRunError(ValueError):
    """Reject a Patch rehearsal that fails Scene verification. @sergent/docs/execution-model.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    def __init__(
        self,
        message: str,
        *,
        metadata: dict[str, object],
    ) -> None:
        super().__init__(message)
        self.metadata = dict(metadata)


class MergeConflictError(PatchValidationError):
    """Report a deterministic Scene-owned rebase rejection. @sergent/docs/framework.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
