import nox

nox.options.default_venv_backend = "uv|virtualenv"


@nox.session(python=["3.9", "3.10", "3.11", "3.12"])
def lint(session: nox.Session) -> None:
    session.run("uv", "sync", env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location})
    session.run(
        "uv", "run", "ruff", "check", "py_src", "py_tests", env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location}
    )
    session.run(
        "uv",
        "run",
        "mypy",
        "--disallow-untyped-defs",
        "py_src",
        "py_tests",
        env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location},
    )
    session.run(
        "uv", "run", "ruff", "check", "py_src", "py_tests", env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location}
    )
    session.run(
        "uv",
        "run",
        "ruff",
        "check",
        "--ignore-noqa",
        "--exit-zero",
        "py_src",
        "py_tests",
        env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location},
    )
