"""Define runtime-provided Intent proposal variants. @sergent/docs/framework.md
@sergent-py-runtime/docs/KNOWLEDGE.md"""

from __future__ import annotations

import sergent_py_core.strict_model as core_strict_model


class IntentProposal_PassThrough(core_strict_model.StrictModel):
    """Represent local Intent derivation that skips its model call. @sergent/docs/framework.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
