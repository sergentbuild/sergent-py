"""Define the Plan Proposal envelope and validated Execution Plan. @sergent/docs/framework.md
@sergent-py-core/docs/core-class-design-pattern.md"""

from __future__ import annotations

import pydantic

import sergent_py_core.operation as operation
import sergent_py_core.scene as scene
import sergent_py_core.strict_model as strict_model


class PlanProposal(strict_model.StrictModel):
    """Carry a non-empty model-proposed Operation script. @sergent/docs/framework.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    operations: list[operation.Operation] = pydantic.Field(min_length=1)


class ExecutionPlan(strict_model.StrictModel):
    """Bind a validated Operation script to its base Scene identity. @sergent/docs/framework.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    base: scene.SceneIdentity
    steps: list[operation.Operation]
