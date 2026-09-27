.PHONY: setup
setup:
	uv sync
	@if [ ! -f .env ]; then cp .env.example .env && echo "Edit .env to set DAIKIN_HOST."; fi

.PHONY: run
run:
	uv run uvicorn main:app --reload --app-dir src --host 127.0.0.1 --port 8000

.PHONY: test
test:
	uv run coverage run -m pytest
	uv run coverage report

.PHONY: lint
lint:
	uv run ruff format --check .
	uv run ruff check .
	uv run ty check

.PHONY: format
format:
	uv run ruff format .

.PHONY: build-image
build-image:
	docker build -t daikin-mck706a-api:latest .

.PHONY: run-image
run-image:
	docker run --rm -p 8000:8000 --env-file .env daikin-mck706a-api:latest

.PHONY: precommit-install
precommit-install:
	uv run pre-commit install

.PHONY: precommit
precommit:
	uv run pre-commit run --all-files

.PHONY: clean
clean:
	@find . -name '__pycache__' -type d -prune -exec rm -r {} +
	@rm -rf .pytest_cache .ruff_cache .ty_cache htmlcov .coverage
