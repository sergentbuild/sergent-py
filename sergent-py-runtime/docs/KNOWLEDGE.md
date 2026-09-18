# sergent-py-runtime Knowledge

The specification's [execution model](../../sergent/docs/execution-model.md) teaches what a Run
is. This file teaches how that Run materializes in Python, for anyone who must reason about the
engine without reading it.

Two rules frame everything below. The two model calls are the pipeline's only suspension points,
so every step that decides, checks, rehearses, or mutates is a plain synchronous function. Runtime
input is admitted only at the specification's [five
boundaries](../../sergent/docs/trust-boundaries.md#the-five-boundaries), and after a crossing the
typed value is trusted inward. The package holds four areas: execution (the engine, the
deterministic core, live Scene authority, rebase, failures), lifecycle (progress, observers,
cancellation, handles), Run Record (the builder, capture, the file harness), and proposals
(captured configuration and the runtime-provided variants).

## The end-to-end walkthrough

### Before the first Run: construction-time capture

[Construction-time capture](../../sergent/docs/execution-model.md#construction-time-capture)
happens once, in the `SergentRuntime` constructor. The runtime reads the Recipe's proposal type,
its optional Operation Registry, and its optional maximum, derives every schema the Recipe can
reach, and freezes them in one private immutable value. Nothing rereads Recipe configuration
during a Run. Capture is a wiring check rather than a trust boundary, so a dialect error raised
while deriving the Intent schema is re-raised with the Recipe and proposal class names attached.

That capture fixes the Run Kind before any Run starts. A Recipe whose proposal type is
`IntentProposal_PassThrough` gets no Intent schema and skips the first model call. A Recipe with
a registry gets one cached Plan Proposal schema. A Recipe without a registry gets neither a Plan
Proposal schema nor a request, the Intent-Only shape of the
[registry rule](../../sergent/docs/framework.md#operation-registry-and-the-plan-proposal-envelope);
if it later derives a continuing Intent, the runtime fails the Run before any model call rather
than inventing a request.

### Starting a Run

`SergentRuntime.run` is the asynchronous entry point and `start` schedules the same pipeline on
an asyncio task, returning a `RunHandle`. Both first create one `Run` object, the per-Run builder
that owns the Run identity, the sanitized progress state, the `RunRecord` under construction, and
the closers that produce the Sergent Result. Everything a Run remembers lives there, which is why
the engine keeps no per-Run fields and one instance can drive many concurrent Runs. Before the
pipeline starts, the engine delivers the `queued` progress that
[observer delivery](../../sergent/docs/observability.md#observer-delivery) requires. The engine
body is then a sequence of small private stage helpers, one per step of the flow, called in order
by one driver. They are plain methods rather than stage objects on purpose: the flow is fixed by
the specification, so a configurable stage machine would add vocabulary without adding capability.

### Observation, snapshot, and Target

The first step opens the `process_input` Step Record and exports the `MindBuf` exactly once,
recording that text as the observation. The same `MindBuf` object then reaches every request
builder the Run reaches, so the Recipe renders it for the model rather than the runtime guessing
a projection. The Scene channel is handled separately, as
[observation assembly](../../sergent/docs/execution-model.md#observation-assembly) requires: a
plain Scene is cloned through the Scene Actions, a `SceneState` is snapshotted under its lock.
Either way the Run binds one base Scene and one identity, and from that moment a failure can
become a contained result.

Target selection then asks the Scene Actions for the Target, from the Scene alone. When they
return none, the Run closes as a failure at the `started` stage with the Recipe's declared
no-target error, deep-copied first so Run Record evidence never aliases an object the Recipe
still owns. The selected Target is stored once and passed unchanged to every later step, which is
what [Target ownership](../../sergent/docs/framework.md#target-ownership) demands.

### The Intent phase

With a Target in hand the runtime reads the cancellation token, opens the `intent` step, and
resolves the Intent Proposal. A model-backed Recipe gets its request built and recorded, the call
awaited, and the returned JSON object validated against the declared proposal class. A
pass-through Recipe instead receives a runtime-constructed `IntentProposal_PassThrough`, the typed
sentinel the specification calls
[pass-through](../../sergent/docs/terminology.md#pass-through), with no request, no schema, and no
recorded call. It is neither model output nor the derived Intent.

The Recipe then derives the Intent, validates it, and the runtime reads the resulting flow through
a core reader. A stop flow closes the Run as success with no mutation, recording the revision
unchanged; a continue flow closes the Intent step and opens the Execution Plan step.
`Intent_Continue` is the runtime's minimal continuing Intent, used directly when the decision
carries no data and subclassed when it does. Runtime-provided Intent Proposal classes live
together in one module and runtime-provided Intent classes in a sibling module, so each family
stays visible as a family.

### The Execution Plan phase

The Plan Proposal request is built under the captured registry and schema, awaited, and decoded by
that same registry under the captured maximum. This is the second and last crossing of the
[model-output boundary](../../sergent/docs/trust-boundaries.md#first-the-model-output). Both
crossings belong to this package, and both follow one rule: when a crossing fails, the runtime
first closes the model call record with the evidence the call did return, then fails the step as a
schema validation failure. The call record therefore stays complete even though no typed proposal
came out of it.

The Recipe derives the Execution Plan from the decoded proposal. The runtime then performs the
admissibility pass described in
[Operation Admissibility flow](../../sergent/docs/execution-model.md#operation-admissibility-flow):
one ordered traversal that hands each Operation a fresh clone of the base Scene, the validated
Intent, and the exact selected Target, stopping at the first rejection. That rejection is recorded
with the Operation's position, call name, and framework identity, and no Patch step begins. After
the pass, the Recipe validates the plan as a whole.

### Patch, rehearsal, and commit

Patch compilation belongs to the Recipe, not the engine; the core package supplies the mechanical
default that isolates the Operations and preserves their identities. The runtime asks the Recipe
to compile, summarizes the Patch as evidence, and then runs the three public synchronous functions
that carry the safety promise
of [dry-run and commit](../../sergent/docs/execution-model.md#verification-dry-run-and-commit):

- `validate_patch` rejects a Patch that does not belong to the observed Scene: a different Scene,
  a stale base revision, an empty Patch, a missing Target, an Operation outside the core Operation
  type, or a trace that does not line up one-to-one with the Operations by unique identity. A
  stale base revision raises `StalePatchError`, every other defect `PatchValidationError`.
- `dry_run` is the rehearsal. It clones the snapshot, applies the Operations with the selected
  Target, asks the Scene Actions to verify the result, and confirms the Scene identity did not
  drift. A verification report with issues raises `DryRunError` carrying them.
- `commit` applies the Patch to the isolated plain snapshot. Live authority commits through
  `SceneState` instead, which compares revisions before it mutates.

### Closing the Run

Every path ends at one of the `Run` object's closers: a committed success, a stop success without
a Patch, a failure, a cancellation, or a no-Target failure. The closer stamps timing, records the
outcome and any terminal facts, advances the recorded revision only when a commit happened, and
returns the Sergent Result whose shape
[the result structure](../../sergent/docs/run-record-spec.md#the-sergent-result-structure) fixes.
An open Step Record inherits the Run's terminal status, so a failure is attributed to the step
where it happened.

Progress rides along the whole walk: each stage advance updates the sanitized snapshot and
delivers it to every observer slot. `Stage` enumerates the nine stages in specification order.

## How this package works with core and providers

### What it consumes from core

The runtime implements behavior and defines almost no data. Scene identity, Target, MindBuf, the
proposal and Execution Plan values, Patch and its rebase values, the model call values, the whole
Run Record family, and the Sergent Result are core-owned; this package fills those structures and
is the only component that does, which keeps the record shapes stable while the engine evolves.
Three core interfaces carry the application into the engine: the Scene Actions provide identity,
cloning, Target selection and presence, apply, and verify; the Recipe provides the policy hooks
and the declared no-target error; the model client provides transport. The constructor takes all
three, which is also the whole test seam.

### The model client seam and the unchanged-schema check

The model client is a single asynchronous method that takes a request and returns call evidence
beside one parsed JSON object. Everything provider-specific stays behind it: credentials,
adapters, retries, and the strict parse belong to the
[external systems boundary](../../sergent/docs/trust-boundaries.md#fifth-external-systems). The
full `provider/model` selection is caller-supplied data, carried unchanged into each request and
into the Run Record; the runtime never resolves a provider itself.

The specification also requires the Recipe's request builder to return the captured schema
unchanged. In Python that check is object identity: the runtime compares the request's schema with
the one it passed in using `is`, before the request is recorded. There is no deep copy, no
structural comparison, and no later defense against mutation, because the check reports a
developer wiring mistake rather than admitting runtime input.

### Why the runtime never imports providers

The dependency points one way: providers depend on core, the runtime depends on core, and nothing
here names the providers package. A concrete client arrives through the interface, from the caller
or from the battery package's wiring. That keeps the engine's tests free of network and
credentials, keeps provider SDK churn out of the safety path, and preserves the acyclic layering.
Applications reach the runtime's public classes through the battery package's curated exports
rather than importing this package directly.

## Side effects and reliability

### Failure containment and classification

The engine contains ordinary exceptions raised anywhere in the pipeline and turns them into a
failed Sergent Result with the unchanged Scene, as
[the containment rule](../../sergent/docs/execution-model.md#cancellation-and-the-sergent-result)
requires. The exception class alone decides the
[Run error kind](../../sergent/docs/run-record-spec.md#run-errors); no message text is ever parsed.

A transport error keeps its own kind and message, carries its retryable flag as metadata, and
closes the open call record from the error's identity, attempts, and any partial response. An
admissibility rejection, a dry-run failure, and any other invalid value become validation errors,
the first two carrying their structured facts. A failed proposal crossing becomes a schema
validation failure. The Patch family is matched from the most specific class outward, because
`MergeConflictError` and `StalePatchError` both subclass `PatchValidationError` and a looser order
would swallow them. Anything else becomes an internal error with the exception type, a traceback,
the cause chain, and the name of the open step. Recipe hook failures follow the same mapping, so
an application mistake is reported in the application's own vocabulary.

Three things deliberately escape containment. Process-control exceptions such as keyboard
interruption and system exit are never caught, in the pipeline or in observer delivery. Task
cancellation that Sergent did not request is re-raised rather than disguised as a cancelled Run.
And a failure raised before the base Scene identity is bound propagates out of the entry point,
because a result needs Scene facts that do not exist yet.

### Cancellation

Cancellation has two mechanisms that meet in one outcome. `CancelToken` is the cooperative half:
the runtime reads it at four checkpoints, before the Intent step opens, after Intent validation,
before the dry-run, and before commit, and the recorded checkpoint names where the Run stopped.
The token stamps its request time once, on the first cancel, so repeated calls cannot rewrite
history. `RunHandle.cancel` adds the second half. It trips the token and cancels the asyncio task
through its loop, which interrupts an awaited provider call instead of waiting for it. The engine
accepts that task cancellation as its own only when the token was tripped and the base Scene
identity is already bound; otherwise it re-raises. An interrupted call keeps only its recorded
request, with no invented attempt row, matching the rule in [model call
records](../../sergent/docs/run-record-spec.md#model-call-records). A cancelled Run closes with
the original Scene, unchanged. Because the tail after the Plan Proposal call never suspends,
cancellation can never land between Patch validation and commit on one event loop: the commit
critical section is atomic by construction rather than by a lock.

### Observer isolation

`RunObserver` is a protocol with two synchronous callbacks. The runtime calls every configured
slot in order and contains an ordinary failure, including a cancellation-shaped exception raised
by a callback, as an observer error naming the callback, the observer and exception types, and the
stage. One failing observer never blocks a later one and never changes status, stage, mutation, or
commit. Those errors live beside the Run Record on the result, never inside it, because a terminal
observer can only fail after the record has closed. Progress is sanitized by structure rather than
by filtering: the snapshot type carries only the fields that
[progress snapshots](../../sergent/docs/observability.md#progress-snapshots) fixes, so prompts,
Scene content, and model output have nowhere to leak into.

### Live Scene authority, revisions, and the two locks

`SceneState` is the shared live authority that the
[writer model](../../sergent/docs/framework.md#writer-model-and-revision-policy) prescribes for
concurrent writers over the same data, and `SergentRuntime.live_state` builds one from the Scene
Actions' identity and clone functions. It holds the current Scene and its identity behind a lock,
hands out isolated snapshots, and mutates only while the observed revision is still current. It
offers two commit entry points over that rule: `try_commit_patch` for the runtime's Patch
commit, and `try_commit` for the application's own user edits, so human writes share the
revision sequence instead of bypassing it. When the revision has advanced and no rebase path
exists, it raises `StalePatchError` and nothing changes. `CommitResult` reports whether the commit was exact or rebased and carries the
Scene-supplied rebase mapping unchanged.

Revision representation is a separate switch. By default the state advances the revision beside
the Scene data and asks only that the committed Scene keep its Scene id. Turning on embedded
identity selects the
[embedded representation](../../sergent/docs/execution-model.md#revision-representation): the
committed Scene must then report the same Scene id and exactly one revision beyond the base
actually committed, and a mismatch is rejected with the identity facts attached. The switch
changes neither snapshotting nor the stale comparison. A serialized application may still hold its
Scene in `SceneState`; its own control flow, not the stale check, then provides writer exclusion.

The package holds two locks, both ordinary thread locks, and neither schedules anything in
asyncio. The `SceneState` lock defends shared live authority in thread-based hosts and is never
held across a suspension point. The Run Record file lock keeps one file's write, its durability
step, its start acknowledgement, and its permanent-failure state atomic when concurrent Runs share
it. Asyncio concurrency needs no lock here, because the deterministic tail does not suspend.

### Rebase, the one sanctioned re-validation

Rebase is the framework's single sanctioned re-validation, which the trust specification places at
the [commit boundary](../../sergent/docs/trust-boundaries.md#fourth-shared-live-state-at-commit).
The runtime detects the capability structurally, with no registration step: Scene Actions that
define a Patch rebase method are rebase-capable. That method receives the base and current Scenes
with the current identity, the original Target, and the original Patch. When it returns a
replacement Patch, the runtime repeats envelope validation, the admissibility pass, and the
dry-run against the current Scene, keeping the Run's original Intent and Target, exactly as the
[rebase sequence](../../sergent/docs/execution-model.md#patch-rebase-on-shared-live-state)
requires. A declared conflict, or a replacement that fails any of those three checks, raises
`MergeConflictError`, the one failure class the battery re-exports, whose metadata separates the
revisions, the rejected Patch summary, the Scene-supplied facts, and the failing check. The
runtime never resolves a domain conflict and never asks the model to.

### Run Record files and durability

`JsonlRunRecordWriter` is the opt-in [Run Record
harness](../../sergent/docs/terminology.md#run-record-harness) and this package's only
persistence, the documented exception to the no-storage boundary. It is an observer: its progress
callback writes the run-start boundary once per Run identity and drops repeats, and its terminal
callback writes the run end with the complete Run Record serialized whole under the payload. It is
also a context manager and the owner of the direct application and user event hooks. Durability
follows [file discipline](../../sergent/docs/run-record-file-format.md#file-discipline). The file
is created exclusively with owner-only permissions and is never truncated or appended to. A start
is acknowledged after its line is written and flushed; an end is synchronized to storage first.
The first persistence failure permanently disables the writer, and every later write reports
unavailability chained to that first failure, so a damaged file never silently accepts more lines.
Closing synchronizes a healthy file, is safe to repeat, and reports only failures from the close
itself.

Event payloads are converted outbound, never parsed back. A value that cannot be encoded fails
before any byte reaches the file, so the file stays readable; an exception payload becomes its type
and message, and any other unconvertible value its type and a bounded rendering. The standard
library encoder produces the sorted-key ASCII lines that
[exact line encoding](../../sergent/docs/run-record-file-format.md#exact-line-encoding) prescribes.
A direct event call raises its failure to the application, while the same failure on the observer
path becomes an observer error, because the two have different owners. The application still owns
the directory, the identity, retention, redaction, and access, and a persisted Run end is sensitive
forensic data, as [sensitivity](../../sergent/docs/observability.md#sensitivity) warns.

### Capture that never fails a Run

Evidence capture is best effort by design, following the
[captured value rules](../../sergent/docs/run-record-spec.md#captured-values). Typed models are
dumped so that subclass fields survive, falling back to the plain dump when the richer one raises.
Dataclasses become field mappings, mappings and sequences recurse, sets are ordered by their
rendering so a capture is stable, and any other value degrades to its type name and a rendering. A
conversion failure is recorded in place inside its own envelope and never changes the outcome,
which is the whole point: forensics must not be able to break execution. Capture trusts
applications for one thing, that an exception type renders as text; an exception whose rendering
itself raises cannot be recorded.

### Testing seams and doubles

The seams are the constructor and the entry points, designed together with the implementation. The
runtime takes its model client, Scene Actions, Recipe, and observer slots by construction, so a
test drives the real pipeline with scripted doubles. A cancellation token is passed into a Run or
owned by the handle from `start`. `live_state` is the factory for shared authority with its
embedded identity switch. The file harness takes a directory, so tests point it at a temporary
path, and its internal writer accepts a stream plus a durability callable, the in-memory seam for
proving durability order without touching a disk.

The package's own tests carry three shared support modules rather than implicit fixtures: a
self-contained demo domain covering every interface, with scripted model clients for static
responses, transport errors, cancellation timing, and a parked call gate for concurrency; a flow
module with stop, unsupported-flow, and rebase variants including a deliberately invalid rebase;
and a support module holding the runtime builder and small readers over Run Record evidence. Tests
never contact a live provider and never read real credentials, and the scripted clients are test
implementations rather than a user fallback: an application constructs a real client and supplies
an explicit `provider/model` selection for each Run.
