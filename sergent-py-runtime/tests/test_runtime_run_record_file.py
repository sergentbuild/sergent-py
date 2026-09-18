from __future__ import annotations

import asyncio
import dataclasses
import datetime
import enum
import json
import os
import pathlib
import stat
import typing
import unittest.mock

import pytest

import demo_domain as domain
import sergent_py_core.model_calls as model_calls
import sergent_py_core.mindbuf as core_mindbuf
import sergent_py_core.model_calls as core_model_calls
import sergent_py_core.result as core_result
import sergent_py_core.timing as core_timing
import sergent_py_runtime.execution.engine as engine
import sergent_py_runtime.run_record.run_record_file as run_record_file
import sergent_py_runtime.lifecycle.observe as observe


class _FaultStream:
    def __init__(
        self,
        *,
        write_error: BaseException | None = None,
        flush_error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.write_error = write_error
        self.flush_error = flush_error
        self.close_error = close_error
        self.text = ""
        self.write_calls = 0
        self.flush_calls = 0
        self.close_calls = 0

    def write(self, value: str) -> int:
        self.write_calls += 1
        if self.write_error is not None:
            raise self.write_error
        self.text += value
        return len(value)

    def flush(self) -> None:
        self.flush_calls += 1
        if self.flush_error is not None:
            raise self.flush_error

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class _Synchronizer:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


class _InterruptingRepr:
    def __repr__(self) -> str:
        raise KeyboardInterrupt


class _InterruptingError(Exception):
    def __str__(self) -> str:
        raise SystemExit


class _LongRepr:
    def __repr__(self) -> str:
        return "x" * 4096


class _Color(enum.Enum):
    BLUE = "blue"


@dataclasses.dataclass
class _Payload:
    path: pathlib.Path
    color: _Color


def _writer(
    stream: _FaultStream,
    *,
    synchronize: _Synchronizer,
) -> run_record_file._RunRecordFileWriter:
    # Stand-in cast: the fake covers only the stream surface the writer touches.
    return run_record_file._RunRecordFileWriter(
        typing.cast(typing.TextIO, stream),
        synchronize=synchronize,
    )


class _AttemptClient(domain.StaticClient):
    async def invoke(
        self, request: model_calls.ModelRequest
    ) -> tuple[model_calls.ModelResponse, dict[str, typing.Any]]:
        response, payload = await super().invoke(request)
        attempt = core_model_calls.ModelAttemptRecord(
            timing=core_timing.TimeSpan(
                started_at="2026-01-01T00:00:00.000000Z",
                finished_at="2026-01-01T00:00:00.001000Z",
                duration_ms=1,
            ),
            status="success",
        )
        return response.model_copy(update={"attempts": [attempt]}), payload


def _run(
    *observers: observe.RunObserver,
    client: model_calls.ModelClient | None = None,
) -> core_result.SergentResult[typing.Any]:
    runtime = engine.SergentRuntime(
        domain.StaticClient(["alpha"]) if client is None else client,
        domain.DemoActions(),
        domain.DemoRecipe(),
        observers=observers,
    )
    return asyncio.run(
        runtime.run(domain.make_scene(), core_mindbuf.MindBuf(), model_name="test/fake")
    )


def _entries(path: pathlib.Path) -> list[dict[str, typing.Any]]:
    return [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]


def _run_record_file(
    writer: run_record_file._RunRecordFileWriter,
) -> run_record_file.JsonlRunRecordWriter:
    log = object.__new__(run_record_file.JsonlRunRecordWriter)
    log.path = pathlib.Path("memory.jsonl")
    log._writer = writer
    log._seen_starts = set()
    return log


def test_filename_components_do_not_collide_at_the_same_timestamp(tmp_path: pathlib.Path) -> None:
    fixed_time = datetime.datetime(2026, 9, 13, tzinfo=datetime.timezone.utc)
    pairs = [("demo-one", "session"), ("demo", "one-session")]
    filenames: list[str] = []
    with unittest.mock.patch.object(datetime, "datetime") as clock:
        clock.now.return_value = fixed_time
        for app_name, log_id in pairs:
            with run_record_file.JsonlRunRecordWriter(tmp_path, app_name, log_id=log_id) as log:
                filenames.append(log.path.name)

    assert filenames == [
        "demo-one+session+20260913T000000000000Z.jsonl",
        "demo+one-session+20260913T000000000000Z.jsonl",
    ]


def test_ordered_boundaries_deduplicate_and_keep_complete_run_record(
    tmp_path: pathlib.Path,
) -> None:
    log = run_record_file.JsonlRunRecordWriter(tmp_path, "demo", log_id="session")
    assert log.path.parent == tmp_path

    result = _run(log, client=_AttemptClient(["alpha"]))
    transition = result.run_record.scene
    assert transition is not None
    duplicate_start = observe.ProgressSnapshot(
        run_id=result.run_record.run_id,
        scene_id=transition.scene_id,
        stage=observe.Stage.STARTED,
        status="running",
        revision=transition.revision_before,
    )
    log.progress(duplicate_start)
    log.close()

    entries = _entries(log.path)
    assert [entry["event"] for entry in entries] == ["run.start", "run.end"]
    assert all(entry["schema_version"] == "sergent.run_record.v1" for entry in entries)
    assert entries[0]["activity"] == "sergent_activity"
    assert entries[0]["payload"] == {"snapshot": duplicate_start.model_dump(mode="json")}
    assert "run_record" not in entries[0]["payload"]
    assert "run_record" in entries[1]["payload"]
    steps = entries[1]["payload"]["run_record"]["steps"]
    execution_plan_step = next(step for step in steps if step["name"] == "execution_plan")
    execution_plan = execution_plan_step["output"]["value"]["derived_execution_plan"]
    assert set(execution_plan) == {"base", "steps"}
    assert execution_plan["base"] == {
        "scene_id": result.identity.scene_id,
        "revision": 0,
    }
    intent_step = next(step for step in steps if step["name"] == "intent")
    request = intent_step["model_call"]["payloads"]["request"]["value"]
    assert set(request) == {"model_name", "messages", "model_settings"}
    model_call = intent_step["model_call"]
    assert model_call["proposal_schema"]["name"] == "DemoIntentProposal"
    assert "schema_name" not in model_call
    assert model_call["usage"] == {
        "latency_ms": 7,
        "tokens": {"input": 3, "output": 5},
        "request_id": "req-intent",
    }
    assert len(model_call["attempts"]) == 1
    attempt = model_call["attempts"][0]
    assert set(attempt) == {"timing", "status", "retryable", "error"}
    assert attempt["timing"]["duration_ms"] == 1
    assert entries[1]["scene_id"] == result.identity.scene_id
    assert entries[1]["revision"] == result.identity.revision
    datetime.datetime.strptime(entries[0]["timestamp_utc"], "%Y-%m-%dT%H:%M:%S.%fZ")


def test_finished_rejects_a_record_without_scene_transition(tmp_path: pathlib.Path) -> None:
    result = _run()
    result.run_record.scene = None
    log = run_record_file.JsonlRunRecordWriter(tmp_path, "demo")

    with pytest.raises(ValueError, match="scene transition"):
        log.finished(result)
    log.close()

    assert _entries(log.path) == []


def test_app_and_user_events_validate_context_and_encode_supported_values(
    tmp_path: pathlib.Path,
) -> None:
    run_id = "run_" + "1" * 32
    scene_id = "scene_" + "2" * 32
    nested: object = "leaf"
    for _ in range(30):
        nested = [nested]
    log = run_record_file.JsonlRunRecordWriter(tmp_path, "demo")

    log.app(
        " app.saved ",
        _Payload(path=tmp_path / "scene.txt", color=_Color.BLUE),
        run_id=run_id,
        scene_id=scene_id,
        revision=3,
    )
    log.user(
        "input.sent",
        {
            "date": datetime.date(2026, 7, 12),
            "error": ValueError("bad input"),
            "bytes": b"abc",
            "unknown": _LongRepr(),
            "many": list(range(1200)),
            "nested": nested,
        },
    )
    log.close()

    app, user = _entries(log.path)
    assert app["activity"] == "app_activity"
    assert app["event"] == " app.saved "
    assert app["payload"] == {"color": "blue", "path": str(tmp_path / "scene.txt")}
    assert (app["run_id"], app["scene_id"], app["revision"]) == (run_id, scene_id, 3)
    assert user["activity"] == "user_activity"
    assert user["payload"]["date"] == "2026-07-12"
    assert user["payload"]["bytes"] == "abc"
    assert user["payload"]["error"] == {
        "type": "builtins.ValueError",
        "message": "bad input",
    }
    assert user["payload"]["unknown"] == {
        "type": f"{__name__}._LongRepr",
        "repr": "x" * 2048,
    }
    assert user["payload"]["many"] == list(range(1200))
    cursor = user["payload"]["nested"]
    for _ in range(30):
        cursor = cursor[0]
    assert cursor == "leaf"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"run_id": ""}, "run_id"),
        ({"run_id": 1}, "run_id"),
        ({"scene_id": ""}, "scene_id"),
        ({"revision": -1}, "revision"),
        ({"revision": True}, "revision"),
    ],
)
def test_direct_event_validation_does_not_fail_the_writer(
    tmp_path: pathlib.Path, kwargs: dict[str, typing.Any], message: str
) -> None:
    log = run_record_file.JsonlRunRecordWriter(tmp_path, "demo")

    with pytest.raises(ValueError, match=message):
        log.app("event", **kwargs)
    with pytest.raises(ValueError, match="event"):
        log.app("  ")
    log.app("valid", run_id=" ")
    log.close()

    assert [entry["event"] for entry in _entries(log.path)] == ["valid"]
    assert _entries(log.path)[0]["payload"] == {}
    assert _entries(log.path)[0]["run_id"] == " "


def test_output_is_ascii_and_invalid_json_values_are_rejected_before_io(
    tmp_path: pathlib.Path,
) -> None:
    log = run_record_file.JsonlRunRecordWriter(tmp_path, "demo")

    log.user("unicode", {"value": chr(0x2603)})
    size_before = log.path.stat().st_size
    bad_payloads = ({"value": float("nan")}, {float("-inf")})
    for payload in bad_payloads:
        with pytest.raises(ValueError, match="Out of range float"):
            log.user("bad", payload)
        assert log.path.stat().st_size == size_before

    cycle: list[object] = []
    cycle.append(cycle)
    with pytest.raises(ValueError, match="Circular reference"):
        log.user("bad", cycle)
    assert log.path.stat().st_size == size_before

    log.app("still.healthy")
    log.close()

    raw = log.path.read_text(encoding="ascii")
    assert "\\u2603" in raw
    assert [entry["event"] for entry in _entries(log.path)] == ["unicode", "still.healthy"]


@pytest.mark.parametrize(
    ("payload", "control"),
    [(_InterruptingRepr(), KeyboardInterrupt), (_InterruptingError(), SystemExit)],
)
def test_payload_fallback_does_not_swallow_process_control(
    tmp_path: pathlib.Path,
    payload: object,
    control: type[BaseException],
) -> None:
    log = run_record_file.JsonlRunRecordWriter(tmp_path, "demo")

    with pytest.raises(control):
        log.app("bad", payload)
    assert log.path.stat().st_size == 0
    log.close()


@pytest.mark.parametrize(
    ("app_name", "log_id"),
    [
        ("", None),
        ("bad/name", None),
        ("demo+one", "session"),
        ("x" * 65, None),
        ("demo", ""),
        ("demo", "one+session"),
        ("demo", "x" * 65),
    ],
)
def test_file_parts_are_validated(
    tmp_path: pathlib.Path, app_name: str, log_id: str | None
) -> None:
    with pytest.raises(ValueError, match="must match"):
        run_record_file.JsonlRunRecordWriter(tmp_path, app_name, log_id=log_id)


def test_files_use_exclusive_owner_only_creation_and_never_truncate(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "fixed.jsonl"
    first = run_record_file._RunRecordFileWriter.create(path)

    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    first.write("first\n")
    with pytest.raises(FileExistsError):
        run_record_file._RunRecordFileWriter.create(path)
    first.close()

    assert path.read_text(encoding="ascii") == "first\n"


def test_writer_applies_required_durability() -> None:
    stream = _FaultStream()
    synchronize = _Synchronizer()
    writer = _writer(stream, synchronize=synchronize)
    seen: set[str] = set()

    writer.write("start\n", acknowledgement=(seen, "run_1"))
    assert seen == {"run_1"}
    writer.write("ignored\n", acknowledgement=(seen, "run_1"))
    assert synchronize.calls == 0
    writer.write("end\n", synchronize=True)
    assert synchronize.calls == 1
    writer.close()

    assert stream.text == "start\nend\n"
    assert stream.flush_calls == 2
    assert synchronize.calls == 2


@pytest.mark.parametrize("failure_kind", ["write", "flush", "synchronize"])
def test_writer_failure_is_permanent_and_never_retried(failure_kind: str) -> None:
    first_error = OSError(f"{failure_kind} failed")
    stream = _FaultStream(
        write_error=first_error if failure_kind == "write" else None,
        flush_error=first_error if failure_kind == "flush" else None,
    )
    synchronize = _Synchronizer(first_error if failure_kind == "synchronize" else None)
    writer = _writer(stream, synchronize=synchronize)
    synchronize_write = failure_kind == "synchronize"
    seen: set[str] = set()

    with pytest.raises(OSError):
        writer.write(
            "line\n",
            synchronize=synchronize_write,
            acknowledgement=(seen, "run_1"),
        )
    assert seen == set()
    counts = (stream.write_calls, stream.flush_calls, synchronize.calls)
    with pytest.raises(run_record_file._RunRecordFileUnavailable) as unavailable:
        writer.write(
            "line\n",
            synchronize=synchronize_write,
            acknowledgement=(seen, "run_1"),
        )
    assert str(unavailable.value) == run_record_file._UNAVAILABLE_MESSAGE
    assert unavailable.value.__cause__ is writer._first_failure
    assert (stream.write_calls, stream.flush_calls, synchronize.calls) == counts
    writer.close()
    assert stream.close_calls == 1


def test_close_is_idempotent_and_attempts_descriptor_after_sync_failure() -> None:
    sync_error = OSError("sync failed")
    close_error = OSError("close failed")
    stream = _FaultStream(close_error=close_error)
    synchronize = _Synchronizer(sync_error)
    writer = _writer(stream, synchronize=synchronize)

    with pytest.raises(OSError) as raised:
        writer.close()
    assert raised.value is sync_error
    assert synchronize.calls == 1
    assert stream.close_calls == 1
    writer.close()
    assert (synchronize.calls, stream.close_calls) == (1, 1)


def test_close_reports_new_descriptor_failure_and_skips_sync_after_prior_failure() -> None:
    write_error = OSError("write failed")
    close_error = OSError("close failed")
    stream = _FaultStream(write_error=write_error, close_error=close_error)
    synchronize = _Synchronizer()
    writer = _writer(stream, synchronize=synchronize)

    with pytest.raises(OSError):
        writer.write("line\n")
    with pytest.raises(OSError) as raised:
        writer.close()
    assert raised.value is close_error
    assert synchronize.calls == 0
    assert stream.close_calls == 1


def test_context_manager_preserves_body_exception_over_close_error() -> None:
    body_error = LookupError("body failed")
    close_error = OSError("sync failed")
    writer = _writer(_FaultStream(), synchronize=_Synchronizer(close_error))
    log = _run_record_file(writer)

    with pytest.raises(LookupError) as raised:
        with log:
            raise body_error
    assert raised.value is body_error


def test_context_manager_without_body_error_reports_close_error() -> None:
    close_error = OSError("sync failed")
    writer = _writer(_FaultStream(), synchronize=_Synchronizer(close_error))
    log = _run_record_file(writer)

    with pytest.raises(OSError) as raised:
        with log:
            pass
    assert raised.value is close_error
