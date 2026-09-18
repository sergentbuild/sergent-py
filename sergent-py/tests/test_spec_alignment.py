"""Keep specification execution vocabulary aligned with the Python implementation."""

from __future__ import annotations

import pathlib
import re
import typing

import sergent_py_core.run_record as core_run_record
import sergent_py_runtime.lifecycle.observe as runtime_observe

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_execution_stages_and_terminal_statuses_match_the_specification() -> None:
    """Require the implementation to use the specification's ordered execution vocabulary."""
    text = (REPO_ROOT / "sergent/docs/execution-model.md").read_text(encoding="utf-8")
    flags = re.MULTILINE | re.DOTALL
    section = re.search(r"^## Stages and Status\s*\n(.*?)(?=^## |\Z)", text, flags)
    assert section is not None, "missing Stages and Status specification section"

    block = re.search(r"```[^\n]*\n(.*?)\n```", section.group(1), flags)
    assert block is not None, "missing execution stage chain"
    spec_stages = tuple(token.strip() for token in block.group(1).split("->") if token.strip())
    assert spec_stages == tuple(stage.value for stage in runtime_observe.Stage)

    status_line = re.search(r"Terminal status[^\n.]*", section.group(1))
    assert status_line is not None, "missing terminal status vocabulary"
    spec_statuses = set(re.findall(r"`([^`]+)`", status_line.group(0)))
    assert spec_statuses == set(typing.get_args(core_run_record.RunStatus))
