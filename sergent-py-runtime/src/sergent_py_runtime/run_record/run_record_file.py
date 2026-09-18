"""Write Run Record files. @sergent/docs/run-record-file-format.md
@sergent-py-runtime/docs/KNOWLEDGE.md"""

from __future__ import annotations

import dataclasses
import datetime
import json
import os
import pathlib
import re
import threading
import typing

import pydantic_core
import sergent_py_core.identifiers as core_identifiers
import sergent_py_core.result as core_result
import sergent_py_runtime.lifecycle.observe as runtime_observe

_SCHEMA_VERSION = "sergent.run_record.v1"
_FILE_PART_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_UNAVAILABLE_MESSAGE = "Run Record file is unavailable after a persistence failure"
_MAX_FALLBACK_TEXT = 2048

_Activity = typing.Literal["user_activity", "app_activity", "sergent_activity"]


class _RunRecordFileUnavailable(RuntimeError):
    """Report permanent writer unavailability after an ambiguous failure.
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    pass


class _RunRecordFileWriter:
    """Keep shared ASCII JSONL writes atomic and durable.
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    def __init__(
        self,
        stream: typing.TextIO,
        *,
        synchronize: typing.Callable[[], None] | None = None,
    ) -> None:
        self._stream = stream
        self._synchronize_override = synchronize
        self._lock = threading.Lock()
        self._state = "open"
        self._first_failure: BaseException | None = None

    @classmethod
    def create(cls, path: pathlib.Path) -> _RunRecordFileWriter:
        """Create an owner-only log without overwriting an existing file.
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(path, flags, 0o600)
        try:
            stream = os.fdopen(descriptor, "w", encoding="ascii", newline="\n")
        except BaseException:
            os.close(descriptor)
            raise
        return cls(stream)

    def write(
        self,
        line: str,
        *,
        synchronize: bool = False,
        acknowledgement: tuple[set[str], str] | None = None,
    ) -> None:
        """Persist one line and acknowledge it only after required durability.
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        with self._lock:
            self._ensure_writable()
            if acknowledgement is not None and acknowledgement[1] in acknowledgement[0]:
                return
            try:
                self._stream.write(line)
                self._stream.flush()
                if synchronize:
                    self._synchronize()
            except BaseException as exc:
                self._remember_failure(exc)
                raise
            if acknowledgement is not None:
                acknowledgement[0].add(acknowledgement[1])

    def close(self) -> None:
        """Close the writer and report only failures from this close.
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        with self._lock:
            if self._state == "closed":
                return
            close_failure: BaseException | None = None
            try:
                if self._state == "open":
                    try:
                        self._synchronize()
                    except BaseException as exc:
                        self._remember_failure(exc)
                        close_failure = exc
            finally:
                try:
                    self._stream.close()
                except BaseException as exc:
                    self._remember_failure(exc)
                    close_failure = close_failure or exc
                self._state = "closed"
            if close_failure is not None:
                raise close_failure

    def _ensure_writable(self) -> None:
        """Reject writes after closure or the first persistence failure.
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        if self._first_failure is not None:
            raise _RunRecordFileUnavailable(_UNAVAILABLE_MESSAGE) from self._first_failure
        if self._state == "closed":
            msg = "Run Record file is closed"
            raise ValueError(msg)

    def _synchronize(self) -> None:
        """Force prior writes through the configured durability boundary.
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        if self._synchronize_override is not None:
            self._synchronize_override()
            return
        os.fsync(self._stream.fileno())

    def _remember_failure(self, exc: BaseException) -> None:
        """Permanently disable the writer after its first persistence failure.
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        if self._first_failure is None:
            self._first_failure = exc
        self._state = "failed"


@dataclasses.dataclass(frozen=True)
class _EventContext:
    """Carry optional run and Scene correlation facts for one event.
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    run_id: str | None = None
    scene_id: str | None = None
    revision: int | None = None


class JsonlRunRecordWriter:
    """Write opt-in Run Record files. @sergent/docs/run-record-file-format.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    def __init__(
        self,
        log_dir: pathlib.Path | str,
        app_name: str,
        *,
        log_id: str | None = None,
    ) -> None:
        app_name = _file_part(app_name, "app_name")
        resolved_log_id = core_identifiers.new_id("log") if log_id is None else log_id
        resolved_log_id = _file_part(resolved_log_id, "log_id")
        directory = pathlib.Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.path = directory / f"{app_name}+{resolved_log_id}+{timestamp}.jsonl"
        self._writer = _RunRecordFileWriter.create(self.path)
        self._seen_starts: set[str] = set()

    def app(
        self,
        event: str,
        payload: object = None,
        *,
        run_id: str | None = None,
        scene_id: str | None = None,
        revision: int | None = None,
    ) -> None:
        """Write an app-defined event without assigning meaning to its payload.
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        context = _event_context(run_id, scene_id, revision)
        self._opaque_event("app_activity", event, payload, context)

    def user(
        self,
        event: str,
        payload: object = None,
        *,
        run_id: str | None = None,
        scene_id: str | None = None,
        revision: int | None = None,
    ) -> None:
        """Write a user-defined event without assigning meaning to its payload.
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        context = _event_context(run_id, scene_id, revision)
        self._opaque_event("user_activity", event, payload, context)

    def progress(self, snapshot: runtime_observe.ProgressSnapshot) -> None:
        """Persist and deduplicate only the acknowledged run-start boundary.
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        if snapshot.stage != runtime_observe.Stage.STARTED:
            return
        self._write_start(snapshot)

    def finished(self, result: core_result.SergentResult[object]) -> None:
        """Persist a Run Record at run end. @sergent/docs/run-record-file-format.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        record = result.run_record
        if record.scene is None:
            msg = "Run Record file requires a scene transition for framework boundaries"
            raise ValueError(msg)
        context = _event_context(
            record.run_id,
            result.identity.scene_id,
            result.identity.revision,
        )
        payload = {
            "run_record": record.model_dump(mode="json", serialize_as_any=True),
        }
        line = _event_line("sergent_activity", "run.end", payload, context)
        self._writer.write(line, synchronize=True)

    def close(self) -> None:
        """Synchronize and close this log's exclusive writer.
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        self._writer.close()

    def __enter__(self) -> JsonlRunRecordWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: object,
    ) -> None:
        if exc_type is None:
            self.close()
            return
        try:
            self.close()
        except BaseException:
            pass

    def _write_start(self, snapshot: runtime_observe.ProgressSnapshot) -> None:
        """Write one deduplicated boundary after the run starts.
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        context = _event_context(snapshot.run_id, snapshot.scene_id, snapshot.revision)
        payload = {"snapshot": snapshot.model_dump(mode="json")}
        line = _event_line("sergent_activity", "run.start", payload, context)
        self._writer.write(line, acknowledgement=(self._seen_starts, snapshot.run_id))

    def _opaque_event(
        self,
        activity: typing.Literal["app_activity", "user_activity"],
        event: str,
        payload: object,
        context: _EventContext,
    ) -> None:
        """Write one opaque app or user event after outbound validation.
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        event = _event_name(event)
        encoded = {} if payload is None else _app_payload(payload)
        line = _event_line(activity, event, encoded, context)
        self._writer.write(line)


def _app_payload(value: object) -> object:
    """Convert an opaque event payload with native JSON semantics.
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    return pydantic_core.to_jsonable_python(
        value,
        serialize_as_any=True,
        fallback=_app_payload_fallback,
    )


def _app_payload_fallback(value: object) -> dict[str, str]:
    """Represent exceptions or unknown payload values for JSON encoding.
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    if isinstance(value, BaseException):
        return {"type": _type_name(value), "message": str(value)}
    return {"type": _type_name(value), "repr": repr(value)[:_MAX_FALLBACK_TEXT]}


def _event_line(
    activity: _Activity,
    event: str,
    payload: object,
    context: _EventContext,
) -> str:
    """Encode one event as a deterministic ASCII JSONL record.
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    entry: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "timestamp_utc": _timestamp_utc(),
        "activity": activity,
        "event": event,
        "payload": payload,
    }
    if context.run_id is not None:
        entry["run_id"] = context.run_id
    if context.scene_id is not None:
        entry["scene_id"] = context.scene_id
    if context.revision is not None:
        entry["revision"] = context.revision
    text = json.dumps(
        entry,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return text + "\n"


def _event_context(
    run_id: str | None,
    scene_id: str | None,
    revision: int | None,
) -> _EventContext:
    """Validate optional correlation facts and bind them to an event.
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    return _EventContext(
        run_id=_optional_context_id(run_id, "run_id"),
        scene_id=_optional_context_id(scene_id, "scene_id"),
        revision=_revision(revision),
    )


def _optional_context_id(value: str | None, name: str) -> str | None:
    """Admit an absent or non-empty event correlation identifier.
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    if value is not None and (not isinstance(value, str) or not value):
        msg = f"{name} must be a non-empty string"
        raise ValueError(msg)
    return value


def _revision(value: int | None) -> int | None:
    """Admit an absent or non-negative event revision.
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    if value is not None and (isinstance(value, bool) or value < 0):
        msg = "revision must be a non-negative integer"
        raise ValueError(msg)
    return value


def _file_part(value: str, name: str) -> str:
    """Admit a bounded filesystem-safe log name component.
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    if _FILE_PART_PATTERN.fullmatch(value) is None:
        msg = f"{name} must match [A-Za-z0-9][A-Za-z0-9_.-]{{0,63}}"
        raise ValueError(msg)
    return value


def _event_name(value: str) -> str:
    """Admit a non-empty opaque event name without rewriting it.
    @sergent-py-runtime/docs/KNOWLEDGE.md"""
    if not value.strip():
        msg = "event must be a non-empty string"
        raise ValueError(msg)
    return value


def _timestamp_utc() -> str:
    """Return the current UTC timestamp for a log entry."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _type_name(value: object) -> str:
    """Return the fully qualified concrete type name."""
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"
