"""Define Scene identity, revision policy, and verification values. @sergent/docs/framework.md
@sergent-py-core/docs/core-class-design-pattern.md"""

from __future__ import annotations

import pydantic

import sergent_py_core.identifiers as identifiers
import sergent_py_core.strict_model as strict_model


class SceneIdentity(strict_model.StrictModel):
    """Bind a stable Scene identifier to one non-negative revision. @sergent/docs/framework.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    scene_id: str
    revision: int = pydantic.Field(ge=0)

    @pydantic.field_validator("scene_id")
    @classmethod
    def _scene_id_is_id(cls, value: str) -> str:
        """Admit only framework-shaped Scene identifiers."""
        return identifiers.checked_id(value)


def identity_transition_issues(
    before: SceneIdentity,
    after: SceneIdentity,
) -> list[str]:
    """Report Scene identity drift or a revision advance other than one. @sergent/docs/framework.md"""
    issues: list[str] = []
    if after.scene_id != before.scene_id:
        issues.append("scene identity changed")
    if after.revision - before.revision != 1:
        issues.append("scene revision mismatch")
    return issues


class VerificationReport(strict_model.StrictModel):
    """Carry domain-invariant issues found in the dry-run's resulting Scene. @sergent/docs/terminology.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    issues: list[str] = pydantic.Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return whether Scene verification found no issues. @sergent/docs/terminology.md"""
        return not self.issues
