"""Define the structured failure value shared across a Run. @sergent/docs/execution-model.md"""

from __future__ import annotations

import pydantic

import sergent_py_core.strict_model as strict_model


class RunError(strict_model.StrictModel):
    """Carry a bounded structured failure without raising across the runtime. @sergent/docs/execution-model.md"""

    kind: str
    message: str
    metadata: dict[str, object] = pydantic.Field(default_factory=dict)
