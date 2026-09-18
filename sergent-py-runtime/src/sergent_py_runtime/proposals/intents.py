"""Define runtime-provided Intent variants. @sergent/docs/framework.md
@sergent-py-runtime/docs/KNOWLEDGE.md"""

from __future__ import annotations

import typing

import sergent_py_core.strict_model as core_strict_model


class Intent_Continue(core_strict_model.StrictModel):
    """Carry an Intent whose flow is fixed to continue. @sergent/docs/framework.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    flow: typing.Literal["continue"] = "continue"
