from collections import OrderedDict
from collections.abc import Generator

import pytest
import requests
from fastapi.testclient import TestClient
from httpx import AsyncClient
from pytest_mock import MockerFixture

from par_run.executor import Command, CommandGroup
from par_run.web import ws_app

from .conftest import AnyIOBackendT


@pytest.fixture(
    params=[
        pytest.param(("asyncio", {"use_uvloop": True}), id="asyncio+uvloop"),
        pytest.param(("asyncio", {"use_uvloop": False}), id="asyncio"),
    ]
)
def anyio_backend(request: pytest.FixtureRequest) -> AnyIOBackendT:
    return request.param  # type: ignore


@pytest.fixture()
def test_client(anyio_backend: AnyIOBackendT) -> Generator[TestClient, None, None]:
    yield TestClient(ws_app, backend=anyio_backend[0], backend_options=anyio_backend[1])


@pytest.fixture()
def async_client() -> Generator[AsyncClient, None, None]:
    yield AsyncClient(app=ws_app, base_url="http://test")


def test_ws_main() -> None:
    client = TestClient(ws_app)
    response = client.get("/")
    http_ok = 200
    assert response.status_code == http_ok


def test_ws_full(test_client: TestClient, mocker: MockerFixture, anyio_backend: AnyIOBackendT) -> None:  # noqa: ARG001
    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    groups = [CommandGroup(name="test_group", cmds=commands)]

    mocker.patch("par_run.web.read_commands_toml", return_value=groups)

    with test_client.websocket_connect("/ws") as ws:
        _res = ws.receive_json()
        assert _res


def test_ws_full_part_fail(test_client: TestClient, mocker: MockerFixture, anyio_backend: AnyIOBackendT) -> None:  # noqa: ARG001
    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!' && exit 1")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    groups = [CommandGroup(name="test_group", cmds=commands)]

    mocker.patch("par_run.web.read_commands_toml", return_value=groups)

    with test_client.websocket_connect("/ws") as ws:
        _res = ws.receive_json()
        assert _res


async def test_get_cfg(test_client: TestClient) -> None:
    resp = test_client.get("/get-commands-config")
    assert resp.status_code == requests.codes.ok
    assert resp.json()
