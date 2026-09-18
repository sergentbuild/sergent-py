# sergent-py-runtime

This package is the execution engine of the Sergent Python reference implementation. It is
the only package in the stack that may change application data. The specification's rule that
[the model only proposes](../sergent/docs/framework.md#the-model-only-proposes) is kept here
or nowhere: every decode, every check, the rehearsal, and the single commit happen inside this
package.

## Why this package carries the weight

Three properties give the runtime its architectural position.

**It holds mutation authority alone.** The core package holds values and interfaces, the
providers package holds transport, and the battery package holds wiring. None of them touches
a Scene. An application therefore reasons about data safety by reasoning about one engine.

**It knows nothing about providers.** Concrete model transport reaches the runtime only
through a core interface, so this package never imports the providers package. That one
restriction keeps provider changes out of the safety path and lets the whole engine run under
test with scripted clients and no network. It is the layering the specification recommends
in [for implementers](../sergent/docs/for-implementers.md).

**It owns the asynchronous shape of a Run.** Model calls are the Run's only suspension points,
exactly as [async execution](../sergent/docs/execution-model.md#async-execution) expects. The
deterministic tail never suspends, so the stretch from Patch validation to commit cannot
interleave with another Run on the same event loop.

What the runtime does not decide is just as fixed: Scene shape, Target meaning, Intent
semantics, the Operation vocabulary, prompt text, and evidence retention all belong to the
application. The engine contributes order, isolation, and evidence.

## A Run in Python

`SergentRuntime` is the [Sergent Runtime](../sergent/docs/terminology.md#sergent-runtime).
One instance is built from a model client, the Scene Actions, and the Recipe, and it may drive
many Runs concurrently.

A caller starts a Run in one of two ways. `run()` is the asynchronous entry point and returns
the terminal result. `start()` schedules the same pipeline on an asyncio task and returns a
`RunHandle` that reports progress, requests cancellation, and awaits the result. There is no
synchronous execution twin.

The caller also chooses the Scene authority, and that choice is the application's
[writer model](../sergent/docs/framework.md#writer-model-and-revision-policy) rather than a
detail of its user interface. A plain Scene is a snapshot input: the runtime clones it once and
commits to the isolated clone. A `SceneState` is shared live authority: many Runs may hold the
same one, and commit compares the observed revision against the current revision before it
mutates anything.

Between those two ends the Run follows the specification's
[flow](../sergent/docs/execution-model.md#the-sergent-run-flow) with at most two awaited model
calls. The first may propose the Intent; recipes that skip it receive the runtime-provided
[pass-through](../sergent/docs/terminology.md#pass-through) proposal instead. The second
proposes the Execution Plan. Every remaining step, including the admissibility pass, Patch
validation, the dry-run, and commit, is a plain synchronous function.

The Run ends with a [Sergent Result](../sergent/docs/terminology.md#sergent-result), not with
an exception. The result carries the terminal Scene, the closed Run Record, the last reached
stage, the terminal facts, and any contained observer failures. Ordinary failures inside the
pipeline become that structured value, and the Scene stays untouched unless commit succeeded.

Persisting the evidence stays optional. When an application opts in, the runtime's Run Record
harness writes [Run Record files](../sergent/docs/run-record-file-format.md) and the
application keeps the surrounding policy that
[observability ownership](../sergent/docs/observability.md#ownership) assigns to it.

## Where to read next

[docs/KNOWLEDGE.md](docs/KNOWLEDGE.md) walks the whole engine: which Python owner performs each
step of the Run flow, how this package meets the core and providers packages, and how it
handles side effects, failure, cancellation, concurrency, and durability.
