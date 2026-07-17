.DEFAULT_GOAL := all

.PHONY: all
all: ## Show the available make targets.
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@fgrep "##" Makefile | fgrep -v fgrep

.PHONY: clean
clean: ## Clean the temporary files.
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .coverage
	rm -rf .ruff_cache
	rm -rf megalinter-reports

.PHONY: format
format:  ## Format the code.
	uv run ruff check . --fix
	uv run ruff format .

.PHONY: lint
lint:  ## Run all linters (ruff/pylint/mypy).
	uv run ruff check .
	uv run ruff format --check .
	make mypy

.PHONY: pre-commit
pre-commit:  ## Run all pre-commit hooks across the repository.
	uv run pre-commit run --all-files

.PHONY: install-pre-commit
install-pre-commit:  ## Install the local git pre-commit hooks.
	uv run pre-commit install

.PHONY: test
test:  ## Run the tests and check coverage.
	uv run pytest -n auto --cov=app --cov-report term-missing --cov-fail-under=100

.PHONY: mypy
mypy:  ## Run mypy.
	uv run mypy app

.PHONY: run
run:  ## Run the python script
	uv run python -m app

.PHONY: install
install:  ## Install the dependencies excluding dev.
	uv sync --no-dev

.PHONY: install-dev
install-dev:  ## Install the dependencies including dev.
	uv sync

.PHONY: megalint
megalint:  ## Run the mega-linter. Use LINTER=NAME to run only one.
	docker run --platform linux/amd64 --rm \
		-v /var/run/docker.sock:/var/run/docker.sock:rw \
		-v $(shell pwd):/tmp/lint:rw \
		$(if $(LINTER),-e ENABLE_LINTERS=$(LINTER),) \
		ghcr.io/oxsecurity/megalinter:v9
