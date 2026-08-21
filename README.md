# design-system-chart-exporter

[![Build Status](https://github.com/ONSdigital/design-system-chart-exporter/actions/workflows/ci.yml/badge.svg)](https://github.com/ONSdigital/design-system-chart-exporter/actions/workflows/ci.yml)
[![Build Status](https://github.com/ONSdigital/design-system-chart-exporter/actions/workflows/mega-linter.yml/badge.svg)](https://github.com/ONSdigital/design-system-chart-exporter/actions/workflows/mega-linter.yml)
[![Build Status](https://github.com/ONSdigital/design-system-chart-exporter/actions/workflows/codeql.yml/badge.svg)](https://github.com/ONSdigital/design-system-chart-exporter/actions/workflows/codeql.yml)

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
[![uv-managed](https://img.shields.io/badge/uv-managed-blue)](https://docs.astral.sh/uv/)
[![License - MIT](https://img.shields.io/badge/licence%20-MIT-1ac403.svg)](https://github.com/ONSdigital/design-system-chart-exporter/blob/main/LICENSE)

A FastAPI service for generating and exporting, ONS Design System chart images

---

## Table of Contents

[//]: # (:TODO: Enable link checking once https://github.com/tcort/markdown-link-check/issues/250 is resolved.)
<!-- markdown-link-check-disable -->
- [Getting Started](#getting-started)
    - [Pre-requisites](#pre-requisites)
    - [Installation](#installation)
- [Development](#development)
    - [Run Tests with Coverage](#run-tests-with-coverage)
    - [Linting and Formatting](#linting-and-formatting)
- [Contributing](#contributing)
- [License](#license)
<!-- markdown-link-check-enable -->

## Getting Started

To get a local copy up and running, follow these simple steps.

### Pre-requisites

Ensure you have the following installed:

1. **Python**: Version specified in `.python-version`.
   We recommend using [uv](https://docs.astral.sh/uv/) to install and pin the project Python version.
2. **[uv](https://docs.astral.sh/uv/)**: This is used to manage package dependencies and virtual
   environments.
3. **[Docker](https://docs.docker.com/engine/install/)**
4. **Operating System**: Ubuntu/macOS

### Installation

1. Clone the repository and install the required dependencies.

   ```bash
   git clone https://github.com/ONSdigital/design-system-chart-exporter.git
   ```

2. Install dependencies

   [uv](https://docs.astral.sh/uv/) is used to manage dependencies in this project. For more information, read
   the [uv documentation](https://docs.astral.sh/uv/).
   To install the Python version pinned for this project, run:

   ```bash
   uv python install
   ```

   To install all dependencies, including development dependencies, run:

   ```bash
   make install-dev
   ```

   Install the Git hooks used for local validation:

   ```bash
   make install-pre-commit
   ```

   To install only production dependencies, run:

   ```bash
   make install
   ```

   To build the Docker image for the application, run:

   ```bash
   make compose-build
   ```

3. Run the application

   Locally via `uv`:

   ```bash
   make run
   ```

   Using Docker Compose:

   ```bash
   make start
   ```

By default, the application will be available at [http://localhost:30300](http://localhost:30300).
This can be customised by setting the `WEB_PORT` environment variable.

## Development

Get started with development by running the following commands.
Before proceeding, make sure you have the development dependencies installed using the `make install-dev` command.

A Makefile is provided to simplify common development tasks. To view all available commands, run:

```bash
make
```

### Run Tests with Coverage

The unit tests are written using the [pytest](https://docs.pytest.org/en/stable/) framework. To run the tests and check
coverage, run:

```bash
make test
```

### OpenAPI specification

The OpenAPI specification for the service is available at [http://localhost:30300/openapi.json](http://localhost:30300/openapi.json)
when the service is running locally.

The repository also contains a YAML version of the OpenAPI specification at
`./openapi.yaml`. This can be used to generate client code.

The file can be updated by running the following command:

```bash
make openapi
```

### Linting and Formatting

Various tools are used to lint and format the code in this project.

#### Python

The project uses [Ruff](https://github.com/astral-sh/ruff) for linting and
formatting, [mypy](https://mypy-lang.org/) for type checking, and
[pylint](https://pylint.pycqa.org/) for additional linting of the Python code.

The tools are configured using the `pyproject.toml` file and `.pylintrc`.

To lint the Python code, run:

```bash
make lint
```

To auto-format the Python code, and correct fixable linting issues, run:

```bash
make format
```

To run the configured pre-commit hooks across the repository, run:

```bash
make pre-commit
```

#### MegaLinter (Lint/Format non-python files)

[MegaLinter](https://github.com/oxsecurity/megalinter) is utilised to lint the non-python files in the project.
It offers a single interface to execute a suite of linters for multiple languages and formats, ensuring adherence to
best practices and maintaining consistency across the repository without the need to install each linter individually.

MegaLinter examines various file types and tools, including GitHub Actions, Shell scripts, Dockerfile, etc. It is
configured using the `.mega-linter.yml` file.

To run MegaLinter, ensure you have **Docker** installed on your system.

> [!NOTE]
>
> 1. If you use Colima for Docker on macOS, run `colima start --edit` and set `mountType: virtiofs` in the profile YAML
> so that bind mounts work correctly with `make megalint`.
> 2. The initial run may take some time while the Docker image is downloaded.
> Subsequent runs will be considerably faster due to Docker caching. 🚀

To start the linter and automatically rectify fixable issues, run:

```bash
make megalint
```

To run only a specific linter, pass `LINTER` variable:

```bash
make megalint LINTER=YAML_YAMLLINT
```

This maps to MegaLinter's `ENABLE_LINTERS` environment variable. See the
[supported linters list](https://megalinter.io/latest/supported-linters/) for valid names.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

Copyright © 2026 [Crown Copyright][crown-copyright] (Office for National Statistics)

Unless stated otherwise, the codebase is released under the [MIT License](LICENSE).
This covers both the codebase and any sample code in the documentation.

The documentation in this repo are released under the [Open Government Licence v3.0][ogl-v3].

[crown-copyright]: https://www.nationalarchives.gov.uk/information-management/re-using-public-sector-information/uk-government-licensing-framework/crown-copyright/
[ogl-v3]: https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/
