# Sergent Python Reference Implementation

## Introduction

Sergent is a technical concept and vision for agentic software in which the user stays in
charge: the model only proposes, and a deterministic runtime derives, validates, rehearses, and
commits every change. The language-agnostic [Sergent Specification](sergent/docs/KNOWLEDGE.md)
records that vision as a rulebook. This repository keeps a read-only reference copy of the
specification under `sergent/`; the specification's own repository is the authority.

This repository is the **Sergent Python reference implementation**. It gives application
developers a complete, ready-to-use framework for building Sergentic applications in Python. It
gives implementers in other languages a worked example of how every rule of the specification
becomes practical code. The specification teaches the concepts; this implementation shows how
each concept is materialized.

The implementation targets Python 3.11 and newer. It is pure Python with no native extensions
and no operating-system dependency, so it runs on Linux, macOS, and Windows. Its major
dependencies are Pydantic v2 for typed values and boundary validation, the standard asyncio
library for non-blocking Runs, and the official provider SDKs (OpenAI, Anthropic, Google GenAI)
for model calls. Local Ollama models are reached through the OpenAI SDK.

## Components

The implementation is a uv-managed workspace of four packages. Dependencies point down only:
the public API package depends on the three below it, and the engine and the model transport
never depend on each other.

- [sergent-py](sergent-py/README.md): the batteries-included public API. It supplies the
  default wiring and the curated vocabulary an application imports. Applications import this
  package only.
- [sergent-py-runtime](sergent-py-runtime/README.md): the execution engine. It performs the Run
  flow, owns every Scene mutation, delivers progress to observers, and builds the Run Record.
- [sergent-py-providers](sergent-py-providers/README.md): the concrete model calls. It adapts
  each provider's official SDK behind one model client interface.
- [sergent-py-core](sergent-py-core/README.md): the specification values and the three
  interfaces every other package builds on. It has no engine and no I/O.

## How to Work In This Project

Start with [docs/KNOWLEDGE.md](docs/KNOWLEDGE.md), the distilled knowledge of the whole
workspace and the map to each package's knowledge file. Contributors should be comfortable with
modern Python (asyncio, typing, Pydantic v2), the uv workspace toolchain, and optionally [just](https://just.systems/).

We offer these dev-ops commands:

- syncing dependencies: `uv sync --locked`
- format code: `just fmt` or `uv run ruff format .`
- run the linting process: `just lint` or `uv run ruff check . && uv run pyright`
- run the full tests: `just test` or `uv run pytest`
