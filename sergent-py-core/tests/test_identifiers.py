from __future__ import annotations

import pytest

import sergent_py_core.identifiers as identifiers


def test_new_id_format() -> None:
    run_id = identifiers.new_id("run")
    assert run_id.startswith("run_")
    assert identifiers.checked_id(run_id, "run") == run_id
    paragraph_id = identifiers.new_id("para")
    assert identifiers.checked_id(paragraph_id, "para") == paragraph_id


def test_new_id_rejects_bad_prefix() -> None:
    with pytest.raises(ValueError):
        identifiers.new_id("Bad_Prefix")


def test_checked_id_enforces_prefix_and_format() -> None:
    with pytest.raises(ValueError):
        identifiers.checked_id("notanid")
    good = identifiers.new_id("op")
    with pytest.raises(ValueError):
        identifiers.checked_id(good, "step")
