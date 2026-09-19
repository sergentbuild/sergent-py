# Bare `just` errors; developer must specify a recipe name.
# No quotes around the echo arg so cmd.exe doesn't echo the literal quotes.
[private]
default:
    @echo "ERROR: no recipe specified"
    @exit 1

set shell := ["bash", "-euo", "pipefail", "-c"]
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]

test:
    @uv run pytest

lint:
    @uv run ruff check .
    @uv run pyright

fmt:
    uv run ruff format .
