import nox

nox.options.default_venv_backend = "uv|virtualenv"


def uv_run(session: nox.Session, *args: str) -> None:
    """Run a command in the virtual environment."""
    session.run("uv", "run", *args, env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location})


@nox.session(python=["3.9", "3.10", "3.11", "3.12"])
def lint(session: nox.Session) -> None:
    uv_run(session, "sync")
    uv_run(session, "ruff", "check", "py_src", "py_tests", "noxfile.py")
    uv_run(session, "mypy", "--disallow-untyped-defs", "py_src", "py_tests", "noxfile.py")
    uv_run(session, "ruff", "check", "--ignore-noqa", "--exit-zero", "py_src", "py_tests", "noxfile.py")


@nox.session(python=["3.12"])
def fmt(session: nox.Session) -> None:
    uv_run(session, "sync")
    uv_run(session, "ruff", "format", "py_src", "py_tests", "noxfile.py")
    uv_run(session, "ruff", "check", "--fix", "py_src", "py_tests", "noxfile.py")
