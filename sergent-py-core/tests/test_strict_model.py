from __future__ import annotations

import pytest

import sergent_py_core.strict_model as strict_model


class SampleModel(strict_model.StrictModel):
    value: int


def test_strict_model_forbids_extra() -> None:
    with pytest.raises(ValueError):
        SampleModel(
            value=1,
            extra_field=1,  # pyright: ignore[reportCallIssue] - deliberate extra field
        )


def test_strip_non_empty() -> None:
    assert strict_model.strip_non_empty("  hi  ") == "hi"
    with pytest.raises(ValueError):
        strict_model.strip_non_empty("   ")
