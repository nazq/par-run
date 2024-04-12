# par-run
[![License: MIT](https://img.shields.io/badge/license-MIT-C06524)](https://github.com/nazq/par-run/blob/main/LICENSE)
[![PyPI version](https://badge.fury.io/py/par-run.svg)](https://badge.fury.io/py/par-run)
[![Python Versions](https://img.shields.io/pypi/pyversions/par-run)](https://pypi.org/project/par-run/)

Ever needed to run groups of long-ish running commands in parallel groups? Then this is for you. par-run gives both a CLI and web interface to running groups of commands in parallel.  

## Getting Started

```shell
pip install par-run
par-run run
```

This expects a file call `toml` file, by default the `pyproject.toml` or you can override with the `--file` option

```toml

[tool.par-run]
desc = "par-run from pyproject.toml"

[[tool.par-run.groups]]
name = "Formatting"
desc = "Code formatting commands."
timeout = 5
retries = 3 

  [[tool.par-run.groups.commands]]
  name = "ruff_fmt"
  exec = "ruff format src py_tests"
  # Define an empty extras using standard table notation, or simply omit it if it's always empty

  [[tool.par-run.groups.commands]]
  name = "ruff_fix"
  exec = "ruff check --fix src py_tests"
  # Define an empty extras using standard table notation, or simply omit it if it's always empty


[[tool.par-run.groups]]
name = "Quality"
desc = "Code Quality Tools. No code mutation"
timeout = 5
retries = 3

  [[tool.par-run.groups.commands]]
  name = "ruff_lint"
  exec = "ruff check src py_tests"
  # extras omitted as it's empty

  [[tool.par-run.groups.commands]]
  name = "mypy"
  exec = "mypy src"
  setenv = {NODE_ENV = "production", ENABLE_LOGS = "true"}

  [[tool.par-run.groups.commands]]
  name = "pytest"
  exec = "pytest py_tests"
  setenv = {NODE_ENV = "production", ENABLE_LOGS = "true"}


[[tool.par-run.groups]]
name = "ENV"
desc = "Code Quality Tools. No code mutation"
timeout = 5
retries = 3

  [[tool.par-run.groups.commands]]
  name = "full_env"
  exec = "env"
  setenv = {MY_VAR = "production", ENABLE_LOGS = "true"}

  [[tool.par-run.groups.commands]]
  name = "my_var"
  exec = "echo \"MY_VAR=$MY_VAR\", \"ENABLE_LOGS=$ENABLE_LOGS\""
  setenv = {MY_VAR = "production", ENABLE_LOGS = "true"}

```

The tool will execute each group in parallel collating the the output until each command has completed before writing to the console. If you do not want to wait then it's possible to get the output as it's produced with the `--style recv` param.

There is also a web component included, in order to us ensure to install the optional web component

```shell
pip install par-run[web]
par-run web --help
```

This will add a new sub command with options to start/stop/restart the web service and see the commands updating to the web server on 8081
