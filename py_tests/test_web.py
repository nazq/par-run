import pytest
import requests
from fastapi.testclient import TestClient

from par_run.executor import Command, CommandStatus
from par_run.web import WebCommandCB, ws_app


@pytest.fixture()
def test_client():
    yield TestClient(ws_app)


def test_ws_main():
    client = TestClient(ws_app)
    response = client.get("/")
    http_ok = 200
    assert response.status_code == http_ok


@pytest.mark.skip(reason="Test hanging")
async def test_ws_success(test_client, mocker):
    with test_client.websocket_connect("/ws") as ws:
        cmd = Command(name="test_cmd", cmd="echo 'Hello World'", status=CommandStatus.NOT_STARTED)
        mock_rich_print = mocker.patch("par_run.web.rich.print")
        cb = WebCommandCB(ws)
        cb.on_start(cmd)
        mock_rich_print.assert_called_once()
        cb.on_recv(cmd, "Hello World")
        mock_rich_print.assert_called_once()
        cmd.status = CommandStatus.SUCCESS
        cb.on_term(cmd, 0)


@pytest.mark.skip(reason="Test hanging")
async def test_ws_fail(test_client, mocker):
    with test_client.websocket_connect("/ws") as ws:
        cmd = Command(name="test_cmd", cmd="echo 'Hello World'; exit 1", status=CommandStatus.NOT_STARTED)
        mock_rich_print = mocker.patch("par_run.web.rich.print")
        cb = WebCommandCB(ws)
        await cb.on_start(cmd)
        mock_rich_print.assert_called_once()
        await cb.on_recv(cmd, "Hello World")
        mock_rich_print.assert_called_once()
        cmd.status = CommandStatus.FAILURE
        await cb.on_term(cmd, 1)


@pytest.mark.skip(reason="Test hanging")
async def test_ws_on_recv(test_client, mocker):
    with test_client.websocket_connect("/ws") as ws:
        cmd = Command(name="test_cmd", cmd="echo 'Hello World'", status=CommandStatus.NOT_STARTED)
        mock_rich_print = mocker.patch("par_run.web.rich.print")
        cb = WebCommandCB(ws)
        await cb.on_start(cmd)
        await cb.on_recv(cmd, "Hello World")
        mock_rich_print.assert_called_once()


@pytest.mark.skip(reason="Test hanging")
async def test_get_cfg(test_client):
    resp = test_client.get("/get-commands-config")
    assert resp.status_code == requests.codes.ok
    assert resp.json()
