# par-run
[![License: MIT](https://img.shields.io/badge/license-MIT-C06524)](https://github.com/nazq/par-run/blob/main/LICENSE)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/par-run)
![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https://github.com/nazq/par-run/blob/main/pyproject.toml)


Ever needed to run groups of long-ish running commands in parallel groups? Then this is for you. par-run gives both a CLI and web interface to running groups of commands in parallel.  

## Getting Started

```shell
pip install par-run
par-run run
```

This expects a file call `commands.ini` or you can override with the `--file` option

```ini
[group.formatting]
ruff_fmt = ruff format src py_tests
ruff_fix = ruff check --fix src py_tests

[group.quality]
ruff_lint = ruff check src py_tests
mypy = mypy src
pytest = pytest py_tests
```

The tool will execute each group in parallel collating the the output until each command has completed before writing to the console. If you do not want to wait then it's possible to get the output as it's produced with the `--style recv` param.

There is also a web component included, in order to us ensure to install the optional web component

```shell
pip install par-run[web]
par-run web --help
```

This will add a new sub command with options to start/stop/restart the web service and see the commands updating to the web server on 8081
