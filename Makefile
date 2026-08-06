.DEFAULT_GOAL := all

WEB_PORT ?= 30300

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
	rm -f .coverage
	rm -rf .ruff_cache
	rm -rf megalinter-reports

.PHONY: format
format:  ## Format the code.
	uv run ruff check . --fix
	uv run ruff format .

.PHONY: lint
lint:  ## Run all linters (ruff/mypy/pylint).
	uv run ruff check .
	uv run ruff format --check .
	make mypy
	make pylint

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

.PHONY: pylint
pylint:  ## Run pylint.
	uv run pylint app --reports=n --output-format=colorized --rcfile=.pylintrc -j 0

.PHONY: run
run:  ## Run the app with uvicorn.
	uv run uvicorn app.main:app --host 0.0.0.0 --port $(WEB_PORT) --reload

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

# Docker compose make commands

.PHONY: compose-build
compose-build:  ## Build the main application's Docker container
	docker compose build --build-arg="GIT_COMMIT=$(shell git rev-parse HEAD)" --build-arg="BUILD_TIME=$(shell date +%s)"

.PHONY: compose-pull
compose-pull:  ## Pull Docker containers
	docker compose pull

.PHONY: compose-up
compose-up:  ## Start Docker containers
	docker compose up --detach

.PHONY: compose-down
compose-down:  ## Stop and remove Docker containers and volumes
	docker compose down --volumes

.PHONY: compose-stop
compose-stop:  ## Stop Docker containers
	docker compose stop

.PHONY: docker-shell
docker-shell:  ## Shell into the main application's Docker container
	docker compose exec web bash

.PHONY: docker-logs
docker-logs:  ## Show logs from the main application's Docker container
	docker compose logs --follow web

# Aliases
.PHONY: start
start: compose-up
.PHONY: stop
stop: compose-stop
.PHONY: shell
shell: docker-shell
