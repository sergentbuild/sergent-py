from __future__ import annotations

import sergent_py_core.errors as errors
import sergent_py_core.identifiers as identifiers
import sergent_py_core.result as result_values
import sergent_py_core.run_record as run_record
import sergent_py_core.scene as scene
import sergent_py_core.timing as timing


def test_sergent_result_does_not_compare_terminal_convenience_facts() -> None:
    identity = scene.SceneIdentity(scene_id=identifiers.new_id("doc"), revision=0)
    capture_error = errors.RunError(
        kind="capture_error",
        message="terminal metadata capture failed",
    )
    terminal = run_record.RunTerminalRecord(
        message=run_record.CapturedValue(
            value="terminal message",
            value_type="str",
        ),
        metadata=run_record.CapturedValue(
            value_type="dict",
            error=capture_error,
        ),
    )
    record = run_record.RunRecord(
        run_id=identifiers.new_id("run"),
        model_name="test/fake",
        timing=timing.TimeSpan(
            started_at="2026-04-26T00:00:00Z",
            finished_at="2026-04-26T00:00:01Z",
            duration_ms=1000,
        ),
        scene=run_record.SceneTransition.from_identity(identity),
        outcome=run_record.RunOutcome(status="success", terminal=terminal),
    )

    run_result = result_values.SergentResult(
        stage="intent",
        scene=identity,
        run_record=record,
        terminal_message="terminal message",
        terminal_metadata={"decision": "done"},
    )

    assert terminal.message.value == "terminal message"
    assert terminal.metadata.error is capture_error
    assert run_result.terminal_message == "terminal message"
    assert run_result.terminal_metadata == {"decision": "done"}
