# sergent-py package Knowledge

## Introduction and purpose

`sergent-py` is the public API (aka battery) package of the Sergent Python reference implementation: the one public surface an application imports. The three packages beneath it are deliberately
wiring-free. `sergent-py-core` holds the specification values and the three interfaces,
`sergent-py-runtime` is the engine, and `sergent-py-providers` is model transport. None
selects a default model client, and none re-exports another. This package performs that
assembly once and owns little else: two convenience constructors, one generic asynchronous
helper, and helpers for Pydantic Scenes. Every other name on its surface is a re-export that
moves no logic here.

It adds no new trust boundary. The
[trust rule](../../sergent/docs/trust-boundaries.md#the-trust-rule) closes the list of places
where runtime input is admitted, and none sits here. What resembles validation here is
construction checking: the Sergent Instance performs the specification's
[construction-time capture](../../sergent/docs/execution-model.md#construction-time-capture)
in its constructor, so a malformed Recipe fails while the application is assembled rather
than mid-Run, and the Scene Actions helpers reject empty identity field names and empty
Operation sequences for the same reason. Each reports a developer mistake where it was
made.

## The building pattern

### Assemble the Sergent Instance

An application supplies two objects of its own. The first implements
[Scene Actions](../../sergent/docs/terminology.md#scene-actions), the deterministic
capabilities the runtime requires over its data. The second is its
[Recipe](../../sergent/docs/terminology.md#recipe), the policy object that builds model
requests and derives and validates the typed values. `create_sergent` binds the two into a
[Sergent Instance](../../sergent/docs/terminology.md#sergent-instance), materialized here as
`SergentRuntime`. It builds the real model client through `make_llm_client` when the caller
supplies none; that constructor takes no arguments and binds no model, which is what lets
model selection stay per-Run.

The application's own Scene type flows through the Scene Actions argument, the Recipe
argument, and the returned instance. Because one type parameter connects all three, wiring a
Recipe written for one Scene into another application's Scene Actions fails type checking at
that single line, long before a Run starts.

### Start a Run

A configured instance exposes two entry points for one
[Run](../../sergent/docs/terminology.md#run). One awaits the Run and returns its
[Sergent Result](../../sergent/docs/terminology.md#sergent-result). The other schedules it
and returns a `RunHandle`, through which the application reads progress, tests completion,
cancels, and awaits the same result. Both take the Scene source, the
[MindBuf](../../sergent/docs/terminology.md#mindbuf), and the full `provider/model` name for
this Run.

The Scene source is the bounded state the Run may observe and commit to. The MindBuf carries
recent facts the committed Scene cannot hold, and facts only: the
[Run Kind](../../sergent/docs/terminology.md#run-kind) and the Target selection policy are
control that the Recipe and the application fix before the Run. The model name is per-Run
infrastructure, not domain data, and per-call sizing travels beside it in the settings value
each request carries. One assembled instance therefore serves a planning Run on a strong
model and a routine Run on a cheap one.

### Choose plain Scene or shared live state

The Scene source is either a plain Scene object or a `SceneState`, and the choice follows
the application's
[writer model](../../sergent/docs/framework.md#writer-model-and-revision-policy), never the
shape of the user interface.

A plain Scene is a snapshot input. It cannot observe changes made after the Run starts, so
it fits when the application already excludes other writers for the whole Run, as with one
serial writer or strict turn-taking. A `SceneState` retains current commit authority behind
a lock, compares the observed revision before committing, and reports each commit as a
`CommitResult` stating whether it was exact or rebased. Concurrent writers over shared data
need it, and the configured instance builds one from a Scene so the identity and clone rules
of the application's Scene Actions stay in one place. The application commits its own user
edits through the same state's revision-checked commit method, so human writes and Sergent
commits advance one revision sequence under one authority.

Shared live state makes strict revision equality the default. A Run that planned against a
stale revision is rejected unless the application defined a deterministic rebase, and a
rebase that cannot resolve the change surfaces as a merge conflict. No domain conflict is
resolved here, and no model is asked to resolve one.

### Watch a Run and keep its evidence

Observers are registered once, when the instance is assembled, and the supplied order is the
delivery order defined by
[observer delivery](../../sergent/docs/observability.md#observer-delivery). A repeated
object creates a repeated slot, and this package preserves that repetition rather than
collapsing it. Observers watch; they hold no authority over the outcome, and a failing
observer is contained by the runtime as an error carried on the result.

Persisting evidence is a second, separate choice. The
[Run Record harness](../../sergent/docs/terminology.md#run-record-harness) is an observer
like any other, so an application opts in by registering it. It writes the framework Run
boundaries, the application records its own application and user events through it, and
releasing it closes the file. This package re-exports the harness unchanged and adds no
persistence behavior, because the file format and its discipline belong to the runtime and
the specification. Run Record files are
[sensitive](../../sergent/docs/observability.md#sensitivity), and the application chooses
the directory, the log identity, the retention, the redaction, and the access.

### Compose Runs in application control flow

The framework keeps a deliberately small flow vocabulary and expects an application to
express looping, branching, and fan-out with ordinary control structures instead of new
Intent flows ([the first phase](../../sergent/docs/framework.md#the-first-phase)). The unit
an application composes is the validated Run and its result, never the raw model call.

`fan_out` is the piece of that pattern worth sharing: bounded concurrency around
application-owned asynchronous work. It settles every item, keeps results in input order,
returns an item's exception in that item's position instead of cancelling its siblings, and
propagates cancellation of the awaiting task to work still in flight. It knows no framework
object and no transport, so an application may fan out whole Runs or its own model calls
while live handles, progress reporting, and budget policy stay in the application.

An application may also hold several configured Sergent Instances over a single live Scene
state when its domain has distinct phases, for example one Recipe for iterative questioning
and another for composing a final artifact. They differ only in policy; the shared live state
remains the one commit authority, and the application still decides when each Run starts.

### Inject fakes at the same seams

The seams that make this package testable are the two arguments an application already uses.
Passing a model client replaces all transport without touching the engine, and passing
observers lets a test read the delivered sequence directly. A test therefore enters through
the real assembled surface instead of re-wiring the lower packages, which is what makes its
evidence meaningful. This package ships no fake of its own: the deterministic scripted
client lives in the providers package as a test implementation, and a test imports it from
there. It is not a user fallback, and nothing in the assembled surface falls back to it. An
application constructs the real client and names an explicit provider and model for every
Run.

## The structure of this package

### The prelude is the whole surface

The package initializer is the only populated one in the reference implementation; every
other package initializer in the workspace is an empty marker. It is written as one
from-import block per defining submodule, and every exported name repeats itself as
`X as X`.

The redundant alias is the re-export marker, not noise. Ruff reads a plain from-import in an
initializer as an unused import and fails the gate, the alias passes with no configuration
at all, and strict type checkers read the same form as a public re-export declaration. Two
tempting alternatives fail for one reason: an `__all__` list states every name a second time
and drifts from the imports, and a per-file lint exemption stops distinguishing a deliberate
re-export from a forgotten import. Do not simplify the aliases away.

A symbol the specification shapes but no application yet consumes is staged instead as a
private alias with a per-line lint exemption, because only the redundant alias counts as a
re-export marker. Staging keeps one real consumer while hiding the symbol from applications,
which is what stops unused public names accumulating. It becomes public when a real
application consumer appears, and not before; the prelude is the authoritative list of what
is staged.

Applications import from the package root; framework code and tests import defining
submodules directly, which keeps "where does this live?" answerable.

### The surface by specification concept

Every public name below materializes a specification concept, except the last two groups,
which are this package's own contribution. The linked section defines the concept; the name
is what an application imports.

Configuring the instance:

- [Sergent Instance](../../sergent/docs/terminology.md#sergent-instance): `SergentRuntime`.
- [Scene Actions](../../sergent/docs/terminology.md#scene-actions): `SceneActions`, one of
  the three interfaces `sergent-py-core` defines.
- [Recipe](../../sergent/docs/terminology.md#recipe): `SergentRecipe`, specialized with the
  application's Scene, Intent Proposal, and Intent types.
- [Operation Registry](../../sergent/docs/terminology.md#operation-registry):
  `OperationRegistry`. The [Run Kind](../../sergent/docs/terminology.md#run-kind) has no
  class; the Recipe's Intent Proposal type and the presence of a registry choose it.

The [Observation](../../sergent/docs/terminology.md#observation):

- [Scene](../../sergent/docs/terminology.md#scene): the application's own type, so no
  framework class names it. Its identity projection is `SceneIdentity`.
- [MindBuf](../../sergent/docs/terminology.md#mindbuf): `MindBuf`, rendered as context-ready
  text.
- [Target](../../sergent/docs/terminology.md#target): `Target`.
- [Verification Report](../../sergent/docs/terminology.md#verification-report):
  `VerificationReport`.

The two proposal phases:

- [Intent Proposal](../../sergent/docs/terminology.md#intent-proposal): application types
  for model-backed phases, and `IntentProposal_PassThrough` for the runtime-supplied
  [pass-through](../../sergent/docs/terminology.md#pass-through) variant.
- [Intent](../../sergent/docs/terminology.md#intent): application types, with
  `Intent_Continue` as the minimal Continue Intent an application may extend with decision
  data ([intent resolution](../../sergent/docs/execution-model.md#intent-resolution)).
- [Plan Proposal](../../sergent/docs/terminology.md#plan-proposal): `PlanProposal`.
- [Execution Plan](../../sergent/docs/terminology.md#execution-plan): `ExecutionPlan`.
- [Operation](../../sergent/docs/terminology.md#operation): subclasses of `Operation`, with
  `OperationTrace` carrying the executed Operation identity.
- [Proposal Schema](../../sergent/docs/terminology.md#proposal-schema): `ProposalSchema`.

The model-call boundary, where
[the model only proposes](../../sergent/docs/framework.md#the-model-only-proposes):

- the client interface: `ModelClient`, the third core interface, implemented by the
  providers package and replaced by a test.
- one call: `ModelRequest` and `ModelResponse`, with `ModelMessage` and `ImagePart`
  composing the request.
- provider facts: `ModelIdentity`, `CallUsage`, and `ModelError`.
- per-call sizing: `ModelSettings` and `ThinkingEffort`, owned by the providers package and
  re-exported because `ModelSettings` is the supported concrete value a request carries.

[Patch](../../sergent/docs/terminology.md#patch), rehearsal, and commit:

- the compiled change: `Patch`.
- [Patch rebase](../../sergent/docs/execution-model.md#patch-rebase-on-shared-live-state) on
  shared live state: `PatchRebaseRequest`, `RebasedPatch`, and `MergeConflict` as the
  reported conflict; `MergeConflictError` is raised when a Scene-owned rebase rejects it.
- the [writer model](../../sergent/docs/framework.md#writer-model-and-revision-policy)
  choice: `SceneState` for shared live state, reporting each commit as a `CommitResult`.

Run lifecycle:

- [cancellation](../../sergent/docs/execution-model.md#cancellation-and-the-sergent-result)
  and the result: `CancelToken` and `RunHandle`.
- [Sergent Result](../../sergent/docs/run-record-spec.md#the-sergent-result-structure):
  `SergentResult`.
- [Run errors](../../sergent/docs/run-record-spec.md#run-errors): `RunError`.
- [terminal status](../../sergent/docs/execution-model.md#stages-and-status): `RunStatus`.

Observability and evidence:

- [observer delivery](../../sergent/docs/observability.md#observer-delivery): `RunObserver`.
- [progress snapshots](../../sergent/docs/observability.md#progress-snapshots):
  `ProgressSnapshot`.
- [Run Record](../../sergent/docs/terminology.md#run-record): `RunRecord`. Its steps
  sequence is the [Run Record Ledger](../../sergent/docs/terminology.md#run-record-ledger),
  and each element is a [Step Record](../../sergent/docs/terminology.md#step-record),
  materialized as `RunStepRecord`.
- [model call records](../../sergent/docs/run-record-spec.md#model-call-records):
  `ModelCallRecord`, with `ModelAttemptRecord` for one provider attempt inside it.
- [captured values](../../sergent/docs/run-record-spec.md#captured-values): `CapturedValue`.
- the terminal evidence: `RunTerminalRecord`.
- [Run Record harness](../../sergent/docs/terminology.md#run-record-harness):
  `JsonlRunRecordWriter`, which writes
  [Run Record files](../../sergent/docs/terminology.md#run-record-file).

Boundary values and bookkeeping:

- fail-closed typed admission: `StrictModel`, the base that rejects unknown data, and
  `strip_non_empty` for required text.
- [framework identifiers](../../sergent/docs/observability.md#identifiers): `new_id` and
  `checked_id`.

Provider access added for application convenience:

- `CREDENTIAL_ENV_VARS`, the tuple naming the provider environment variables, so a test can
  deny every one and prove no live call was attempted.
- `PerplexityAgentClient`, a plain-text research transport re-exported unchanged, for
  applications that research outside a Run.

Its own wiring: `create_sergent`, `make_llm_client`, `fan_out`, and the Scene helpers below.

### The Scene Actions helpers

The helpers remove repeated Scene Actions code for Pydantic Scenes without introducing any
application concept. `pydantic_clone` produces the isolated copy. `field_identity` builds an
identity projector from an id field and a revision field. `whole_scene_target` and
`whole_scene_has_target` bind one Target to the complete Scene and confirm it.
`apply_operations_in_order` applies a non-empty Operation sequence and hands every Operation
the exact selected Target, as the
[Target rule](../../sergent/docs/execution-model.md#the-target-during-execution) requires.
`basic_identity_verifier` reports Scene identity drift and a revision advance other than one,
the rule that
[embedded revision ownership](../../sergent/docs/execution-model.md#revision-representation)
defines.

They cover whole-Scene Targets and identity checks, and stop there. Latest-item,
item-collection, and mode-bearing Targets stay application code until repeated real
implementations prove a generic helper worth carrying. A helper here encodes no domain
decision.

### What this package deliberately does not export

The omissions are as deliberate as the exports, and each has one reason.

- The deterministic scripted model client stays in the providers package, because it is a
  test implementation and never a user fallback.
- The core factory that derives a Proposal Schema stays private, because the runtime derives
  every reachable schema during construction-time capture. An application annotates the
  schema it receives; it never builds one.
- Neither the Intent Proposal family nor the Intent family is owned here. A new
  runtime-provided variant extends the runtime family first and reaches this surface only
  when an application needs it.
- No model catalog, default model, name translation, or capability list exists here, so an
  application cannot inherit a model choice it did not make.

The rule behind all four: a public name here needs a real external consumer, not completeness.

### The convention suites that live in this package's tests

This package is thin, but its test directory is not: two repository-wide suites live here.

The architecture suite checks structural promises no single package can check alone:
workspace membership, one-directional acyclic imports, the rule that the runtime never
imports the providers package, a core free of input and output and concurrency, no
production source importing a test implementation, the synchronous or asynchronous shape of
the core interfaces, and the framework vocabulary, including the terms banned across the
source and the specification copy.

The specification-alignment suite reads the execution model document and requires the
implementation's ordered stage vocabulary and terminal statuses to match it. It fails when
the two drift apart, in either direction.

The remaining suites pin this package's own assembled surface: a model client built without
model selection, the model name arriving at the Run boundary, ordered observer delivery with
duplicate slots preserved, containment of a failing Run Record writer, the presence of every
curated re-export, the absence of retired helpers, the Scene helpers, and the ordering and
cancellation behavior of `fan_out`.

Run `just fmt`, `just test`, and `just lint` from the repository root after changing anything
here, and treat every failure as a bug in the change rather than in the gate.
