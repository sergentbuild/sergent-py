# sergent-py

`sergent-py` is the batteries-included application API of the Sergent Python reference
implementation: the one package an application imports to configure and run a
[Sergent Instance](../sergent/docs/terminology.md#sergent-instance).

## How developers use it

Import this package and nothing else. The three packages beneath it are deliberately
wiring-free: `sergent-py-core` holds the specification values and interfaces,
`sergent-py-runtime` is the engine, and `sergent-py-providers` is model transport. None of
them chooses a default model client, and none re-exports another. This package performs
that assembly once and presents a single curated surface, so an application never reaches
into a framework package directly.

An application brings two things of its own: the deterministic
[Scene Actions](../sergent/docs/terminology.md#scene-actions) over its domain data, and the
[Recipe](../sergent/docs/terminology.md#recipe) that makes agentic decisions followed by
concrete actions on the app's behalf. The convenience
constructor here binds those two into a configured **Sergent Instance**. It builds the real
model client by default, so an application that wants ordinary transport supplies nothing
extra. A test supplies its own test-only model client instead, and nothing else about the
assembled instance changes.

This package chooses no default model. It carries no default model catalog, no default model name, and no session-wide model tuning. The application names the provider and the model on every
[Run](../sergent/docs/terminology.md#run), and the sizing (i.e., output token size and thinking
effort) for that call travels with it. Selection belongs to the Run because one application may
reasonably spend a strong model on one kind of work and a cheaper one on another.

Watching a Run and keeping its evidence are separate opt-in choices. Observers follow a
Run without controlling it, and the
[Run Record harness](../sergent/docs/terminology.md#run-record-harness) writes
[Run Record files](../sergent/docs/terminology.md#run-record-file) only when the
application registers it. Those files are
[sensitive](../sergent/docs/observability.md#sensitivity): the application owns the
directory, the retention, the redaction, and the access.

## Where to read next

[docs/KNOWLEDGE.md](docs/KNOWLEDGE.md) is the knowledge file for this public API package.
It explains the pattern an application follows to build and drive a Sergent Instance, names the exact
public symbol that materializes each specification concept, and states what this package
deliberately leaves out.

The [Sergent Specification](../sergent/docs/KNOWLEDGE.md) teaches the concepts themselves.
Start with its overview when the vocabulary above is new, then return here for the Python
shape of it.
