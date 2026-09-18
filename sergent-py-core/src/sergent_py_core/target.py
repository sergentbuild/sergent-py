"""Define the bounded Target selected for one Run. @sergent/docs/framework.md
@sergent-py-core/docs/core-class-design-pattern.md"""

from __future__ import annotations

import sergent_py_core.strict_model as strict_model


class Target(strict_model.StrictModel):
    """Own read-only, ephemeral Target identity and execution context. @sergent/docs/framework.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    target_id: str
