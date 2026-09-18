from __future__ import annotations

import pytest

import sergent_py_core.scene as core_scene
import sergent_py_core.identifiers as identifiers


def test_identity_transition_issues_accepts_stable_id_and_default_revision_step() -> None:
    scene_id = identifiers.new_id("scene")
    before = core_scene.SceneIdentity(scene_id=scene_id, revision=2)
    after = core_scene.SceneIdentity(scene_id=scene_id, revision=3)

    assert core_scene.identity_transition_issues(before, after) == []


def test_identity_transition_issues_reports_scene_id_drift() -> None:
    before = core_scene.SceneIdentity(scene_id=identifiers.new_id("scene"), revision=2)
    after = core_scene.SceneIdentity(scene_id=identifiers.new_id("scene"), revision=3)

    assert core_scene.identity_transition_issues(before, after) == ["scene identity changed"]


@pytest.mark.parametrize("after_revision", [2, 4])
def test_identity_transition_issues_reports_revision_delta_mismatch(after_revision: int) -> None:
    scene_id = identifiers.new_id("scene")
    before = core_scene.SceneIdentity(scene_id=scene_id, revision=2)
    after = core_scene.SceneIdentity(scene_id=scene_id, revision=after_revision)

    assert core_scene.identity_transition_issues(before, after) == ["scene revision mismatch"]
