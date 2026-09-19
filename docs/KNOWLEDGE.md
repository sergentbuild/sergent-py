# Sergent Python Reference Implementation Knowledge

This document is the distilled knowledge of the whole workspace: what this reference
implementation is for, how its layers carry one Run from observation to commit, and where each
specific subject lives. The [Sergent Specification](../sergent/docs/KNOWLEDGE.md) teaches the
concepts; this implementation teaches how each concept becomes practical Python design. Read the
specification first, then this document, then the package knowledge file for the subject at hand.

## Purpose of This Reference Implementation

### Two audiences

Application developers get a ready-to-use framework. They implement their Scene and its
deterministic Operations, write the Recipe that expresses their agentic decision-making process,
and let the runtime do the rest: proposal decoding, validation, rehearsal, commit, and evidence.

Implementers in other languages get a worked materialization. Each package shows one layer of
the code layering the specification recommends [for implementers](../sergent/docs/for-implementers.md),
and each package knowledge file pairs every specification concept with the design that carries
it in Python. An implementer who studies the specification and this implementation can build a
conforming implementation in any capable language.

### How it respects the specification

The specification is the bible and this implementation is its loyalest follower.

- It invents no vocabulary. Every public name is a term from the
  [terminology](../sergent/docs/terminology.md) spelled as a Python identifier. Where the
  implementation makes a Python-specific choice, the owning package knowledge file names the
  choice beside the specification rule it materializes, so a reader can always separate the
  concept from its materialization.
- The engine performs the Run flow of the
  [execution model](../sergent/docs/execution-model.md) step for step. It does nothing the
  specification does not ask for; and it skips nothing the specification requires.
- Runtime input is admitted only at the
  [five trust boundaries](../sergent/docs/trust-boundaries.md#the-five-boundaries). Typed
  values are trusted everywhere else. A check inside a package is a construction check that
  reports a developer mistake, never a second parse of admitted data.
- The [Run Record](../sergent/docs/run-record-spec.md) and the
  [Run Record file](../sergent/docs/run-record-file-format.md) are produced exactly as
  specified. Captured values keep their Python-native names, as the specification allows.
- The reference copy of the specification under `sergent/` is read-only in this repository and
  maintained by the author. Every document here links to it instead of restating it.

The Python-specific materials are few and deliberate: Pydantic v2 closed-world models for every
specification value, so unknown keys fail loudly; asyncio for the non-blocking Run; the official
provider SDKs behind one model client interface; and the four-package layering described next.

## Feynman Explanation

### Three application layers, four packages

The [Sergent Vision](../sergent/docs/framework.md#sergent-vision) describes a Sergentic
application as three layers: the user behavior layer sets the direction, the agentic layer
observes and proposes, and the algorithmic layer owns the domain data and its deterministic
Operations. This implementation does not replace those layers. It supplies the agentic layer's
runtime and the vocabulary through which the other two layers talk to it. The application keeps
the user behavior layer and the algorithmic layer.

The four packages are the implementation-side layering. Dependencies flow one-way only.

- At the bottom of the layering, the core package is the vocabulary. It holds the specification 
  values and the three interfaces the runtime composes: the model client, the Scene Actions, and the 
  Recipe. It has no engine, no I/O, and no wiring, so every other package can speak its types without
  inheriting its constraints.
- On the higher layer, the runtime package contains the engine. It performs the Run flow,
  responsible for every Scene mutation and the shared live state authority, delivers progress to
  observers, builds the Run Record, and ships the opt-in Run Record harness. It knows the model only
  through the core model client interface.
- The providers package is the external systems boundary. It makes the concrete asynchronous
  model calls through each provider's official SDK, encodes the Proposal Schema in the
  provider's native structured-output facility, retries transient faults within a fixed bound,
  and returns one strictly parsed JSON object beside the call evidence. It never sees proposal
  types or the Operation Registry.
- The public API package aka the battery package sits on the top. It wires the three packages from
  the lower layers together, supplies convenience constructors and generic helpers, and re-exports
  the curated vocabulary an application imports.

The engine and the transport never depend on each other. They meet only in the public API package 
(the battery), which hands the engine a model client built by the transport.

### The batteries-included public API

An application imports the batteries-included public API package only, never a framework package directly.

The three framework packages keep empty package preludes so their internals can move freely; the 
battery prelude is the one curated, stable surface, and every name on it traces to a specification
term.

This default wiring builds the real model client when the application supplies none. Model
selection is treated as data, not configuration: the application passes the full provider and model 
name to every Run, and per-call settings such as thinking effort, output cap, and timeout parameters 
travel with the request. The providers package also ships a scripted fake model client for offline
tests only; it is not designed as an application fallback.

### The life of one Run through the packages

1. The application implements the Scene Actions and the Recipe against the core interfaces and
   assembles a Sergent Instance through the battery. Construction captures the Recipe's
   proposal types and derives every reachable Proposal Schema once, as the
   [construction-time capture](../sergent/docs/execution-model.md#construction-time-capture)
   requires, so a malformed Recipe fails before any Run starts.
2. The application starts a Run with its Scene (a snapshot) or its shared live state, a MindBuf,
   and the provider and model name. The Run is one asyncio coroutine.
3. The runtime performs the [Run flow](../sergent/docs/execution-model.md#the-sergent-run-flow):
   Target selection, the Intent Proposal (a model call or the pass-through variant), Intent
   derivation and validation, the Plan Proposal (a model call), Execution Plan derivation, the
   admissibility pass, Recipe validation, Patch compilation and validation, dry-run with Scene
   verification, and commit. The two model calls are the only suspension points; every other
   step is plain synchronous code, so many Runs share one event loop and interleave only at the
   model calls, exactly as the
   [async execution](../sergent/docs/execution-model.md#async-execution) section expects.
4. Each model call reaches the providers package through the core model client interface. The
   request carries the canonical Proposal Schema, the provider encodes it natively, the response
   text is parsed once into one JSON object, and the call evidence returns with it. The typed
   crossing into an Intent Proposal or Plan Proposal happens in the runtime, never in the
   transport.
5. Commit goes through the Scene authority the application chose from its
   [writer model](../sergent/docs/framework.md#writer-model-and-revision-policy). A plain Scene
   is a snapshot input and commits without a current-state comparison. Shared live state checks
   the revision at commit, fails stale work, or rebases through the application's deterministic
   rule.
6. The Run closes with a Sergent Result carrying the Run Record. Observers receive each progress
   step and the result in registration order and can never change the outcome, as the
   [observer delivery](../sergent/docs/observability.md#observer-delivery) contract fixes. The
   opt-in Run Record harness is one such observer; it writes Run Record files, and the
   application chooses the directory, identity, retention, and redaction.

### Where validation lives

The [trust boundary specification](../sergent/docs/trust-boundaries.md) enumerates five
boundaries, and each has one owner here. Model output is admitted by the runtime at its two
typed crossings. User input and persistence load are admitted by the application at the entry
that receives them. Shared live state at commit is checked by the runtime's revision-checked
authority. External systems, meaning provider responses, credentials, and environment discovery,
are admitted by the providers package. Core owns construction: its closed-world values reject
unknown keys and malformed shapes when they are built. Everywhere else, typed values are
trusted, and the specification's
[three-question method](../sergent/docs/trust-boundaries.md#the-method-to-discard-redundant-validation)
decides whether any other check may exist.

### Composing validated Runs

A model call differs from an ordinary awaited ext service by its trust boundary: it returns an
untrusted proposal that may be malformed, incomplete, or hostile, and the timeouts, retries,
cancellation, and validation around it are the wrapper that unreliable dependency needs. The
consequence is compositional. The safe unit of composition is the validated Run, its Sergent
Result, because validation lives inside it. Applications compose validated Runs with ordinary
asyncio tools such as gather, semaphores, queues, task groups, and timeouts, plus the battery's
bounded fan-out helper. Four disciplines keep that composition honest: model output is a
proposal and is never fed blindly into another call; a retry is a fresh attempt, so an iterative
pattern needs a stop signal and a budget; every model call spends tokens and rate limit, so every
fan-out or refinement loop is budgeted; and applications reuse asyncio instead of rebuilding it.

The specification keeps the flow vocabulary to **Continue** and **Stop** on purpose.
Any richer flow shapes are ordinary application control flow around validated Runs.

Thus, we see these patterns recur:

- **Turn-based** activities with dedicated decision-making. A turn has a clear done state, and the
  application, the user, or an inspecting Run decides whether the next turn starts. Games,
  interviews, and iterative development follow this shape.
- **Divide and conquer** with parallelism. The application splits a large task over the Scene's
  hierarchy into independent subtasks, runs one Run per subtask under a concurrency bound, and
  examines the aggregated result before committing it. It needs a task analyzer and a result
  examiner, and each subtask may carry its own validation.
- **Multi-agent control plane.** Budgeted serial refinement loops and worker Runs whose validation
  chain and sandboxed execution live inside them give long-running agentic work a strong
  reliability guarantee.
- **Real-time assistant.** A Run works in the background on a bounded region while the user keeps
  editing; its result is patched into the user-owned Scene, and any user edit made since the Run
  started overrides the assistant's work. This non-intrusive shape is nicknamed the Clark
  pattern after the robot in the film Futureworld.
- **Embedded side-processor.** A mission-critical system embeds the engine to summarize, cross-check,
  or perform non-critical work inside its own process. A thin agentic layer written against the
  battery replaces a separate agentic system, and the only added operational duty is provider
  credential management.

The [example app tour in the spec](../sergent/docs/KNOWLEDGE.md#example-applications-quick-tour) 
shows each pattern realized in a complete application.

## Navigation Map

### The specification

- [Specification overview](../sergent/docs/KNOWLEDGE.md): the big picture and the reading order
  for the seven specification subjects and the recommended practices.
- [Terminology](../sergent/docs/terminology.md): the normative vocabulary. Every public Python
  name in this implementation is one of these terms.

### The packages

Each package has a knowledge file that pairs the specification concepts it materializes with the
Python design that carries them.

- [sergent-py knowledge](../sergent-py/docs/KNOWLEDGE.md): the building pattern an application
  follows and the structure of the public surface, including the map from each specification
  concept to the exact public name an application imports.
- [sergent-py-runtime knowledge](../sergent-py-runtime/docs/KNOWLEDGE.md): the end-to-end
  walkthrough of a Run with its Python owners, how the engine works with the core and providers
  packages, and how side effects, failures, cancellation, and persistence are handled.
- [sergent-py-providers knowledge](../sergent-py-providers/docs/KNOWLEDGE.md): why the model
  transport is shaped as one client with one adapter per provider, the end-to-end call
  machinery, the error handling contract, and how to add a provider. It links the catalog of
  supported providers and their credentials.
- [sergent-py-core knowledge](../sergent-py-core/docs/KNOWLEDGE.md): the design philosophy of
  the values and interfaces, a subject-by-subject tour, and the coding rules that keep the
  vocabulary closed and typed.

### Where to start

- Building an application: read the sergent-py knowledge file, then the core knowledge file for
  the interfaces you implement.
- Understanding or diagnosing a Run outcome: read the runtime knowledge file with the
  [Run Record specification](../sergent/docs/run-record-spec.md) beside it.
- Adding or fixing a provider adapter: read the providers knowledge file and its catalog.
- The [example repository](https://github.com/sergentbuild/sergent-py-examples) that provides 
  real world example apps built with this frame. Each example is carefully chosen to represent a unique class of technical challenges.
