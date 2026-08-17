.PHONY: lint lint\:fix format format\:check typecheck test check

lint:
	uv run ruff check .

lint\:fix:
	uv run ruff check . --fix

format:
	uv run ruff format .

format\:check:
	uv run ruff format --check .

typecheck:
	uvx ty check src

test:
	uv run pytest

check: format\:check lint typecheck test
