.PHONY: check
check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src
	uv run lint-imports
	uv run pytest
