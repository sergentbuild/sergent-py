"""Provide fail-closed validation for trust-boundary crossings. @sergent/docs/trust-boundaries.md
@sergent-py-core/docs/core-class-design-pattern.md"""

from __future__ import annotations

import pydantic


class StrictModel(pydantic.BaseModel):
    """Reject unknown data and revalidate assignment at trust boundaries. @sergent/docs/trust-boundaries.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    model_config = pydantic.ConfigDict(extra="forbid", validate_assignment=True)


def strip_non_empty(value: str) -> str:
    """Return stripped text or reject an empty boundary value. @sergent/docs/trust-boundaries.md"""
    stripped = value.strip()
    if not stripped:
        msg = "value must be non-empty"
        raise ValueError(msg)
    return stripped
