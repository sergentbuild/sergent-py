test:
    @uv run pytest

lint:
    @uv run ruff check .
    @uv run pyright

fmt:
    uv run ruff format .
