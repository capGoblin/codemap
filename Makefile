.PHONY: check dev build-ui gen-api

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src
	uv run lint-imports
	uv run pytest
	npm --prefix frontend run typecheck
	npm --prefix frontend test

dev:
	uv run codemap serve-dev & trap 'kill $$!' EXIT; npm --prefix frontend run dev

build-ui:
	npm --prefix frontend ci
	npm --prefix frontend run build

# Needs network on first run: openapi-typescript needs TypeScript 5, the frontend uses 7.
gen-api:
	uv run python scripts/dump_openapi.py frontend/openapi.json
	OPENAPI_JSON=openapi.json npm --prefix frontend run gen:api
	rm frontend/openapi.json
