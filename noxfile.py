from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import nox

if TYPE_CHECKING:
    from collections.abc import Mapping

nox.options.default_venv_backend = "uv|virtualenv"


def find_latest_patch_version(base_path: Path, version_prefix: str) -> Path | None:
    pattern = re.compile(rf"cpython-{version_prefix}\.(\d+)-linux-x86_64-gnu")
    latest_version = None
    latest_folder = None

    for folder in base_path.iterdir():
        if folder.is_dir():
            match = pattern.match(folder.name)
            if match:
                patch_version = int(match.group(1))
                if latest_version is None or patch_version > latest_version:
                    latest_version = patch_version
                    latest_folder = folder

    return latest_folder


def build_rust_env(session: nox.Session) -> Mapping[str, str | None]:
    uv_py_dir = Path().home() / Path(".local", "share", "uv", "python")
    if not uv_py_dir.exists():
        raise FileNotFoundError(f"uv python directory {uv_py_dir} does not exist")
    py_ver = session.python
    if not isinstance(py_ver, str):
        raise ValueError(f"Expected python version to be a string, got {type(py_ver)}")
    py_full_ver_dir = find_latest_patch_version(uv_py_dir, py_ver)
    env = {}
    env["LD_LIBRARY_PATH"] = f"{py_full_ver_dir}/lib:{os.getenv('LD_LIBRARY_PATH', '')}"
    env["RUSTFLAGS"] = f"-L {py_full_ver_dir}/lib {os.getenv('RUSTFLAGS', '')}"
    env["PATH"] = f"{py_full_ver_dir}/bin:{os.getenv('PATH', '')}"
    return env


def uv_run_w_rust_env(session: nox.Session, *args: str, env: Mapping[str, str | None] | None = None) -> None:
    rust_env = build_rust_env(session)
    if env is None:
        env = {"UV_PROJECT_ENVIRONMENT": session.virtualenv.location}
    else:
        env = {**env, "UV_PROJECT_ENVIRONMENT": session.virtualenv.location}
        env.update(rust_env)
    uv_run(session, *args, env=env)


def uv_run(session: nox.Session, *args: str, env: Mapping[str, str | None] | None = None) -> None:
    """Run a command in the virtual environment."""
    if env is None:
        env = {"UV_PROJECT_ENVIRONMENT": session.virtualenv.location}
    else:
        env = {**env, "UV_PROJECT_ENVIRONMENT": session.virtualenv.location}
    session.run("uv", "run", *args, env=env)


def _lint(session: nox.Session) -> None:
    session.run("cargo", "clippy", external=True)

    uv_run(session, "sync")
    uv_run(session, "ruff", "check", "py_src", "py_tests", "noxfile.py")
    uv_run(session, "mypy", "--disallow-untyped-defs", "py_src", "py_tests", "noxfile.py")
    uv_run(session, "ruff", "check", "--ignore-noqa", "--exit-zero", "py_src", "py_tests", "noxfile.py")


@nox.session(python=["3.9"])
def lint(session: nox.Session) -> None:
    _lint(session)


@nox.session(python=["3.9", "3.10", "3.11", "3.12"])
def lint_all(session: nox.Session) -> None:
    _lint(session)


@nox.session(python=["3.12"])
def fmt(session: nox.Session) -> None:
    session.run("cargo", "fmt", external=True)
    session.run("cargo", "clippy", "--fix", "--allow-dirty", "--allow-staged", external=True)

    uv_run(session, "sync")
    uv_run(session, "ruff", "format", "py_src", "py_tests", "noxfile.py")
    uv_run(session, "ruff", "check", "--fix", "py_src", "py_tests", "noxfile.py")


def _test(session: nox.Session) -> None:
    reports_dir = Path(".reports")
    shutil.rmtree(reports_dir, ignore_errors=True)
    rust_env = build_rust_env(session)
    uv_run(session, "maturin", "develop", "-r")
    session.run("cargo", "test", external=True, env=rust_env)
    uv_run(session, "sync")
    uv_run(session, "pytest")

    session.run("cargo", "llvm-cov", external=True)
    session.run("cargo", "llvm-cov", "report", "--html", "--output-dir", str(reports_dir / "rust"), external=True)


@nox.session(python=["3.12"])
def test(session: nox.Session) -> None:
    _test(session)


@nox.session(python=["3.9", "3.10", "3.11", "3.12"])
def test_all(session: nox.Session) -> None:
    _test(session)
