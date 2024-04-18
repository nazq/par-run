from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from par_run.executor import Command, CommandStatus, ProcessingStrategy
from par_run.web import WebCommandCB, get_commands_config, websocket_endpoint, ws_app


@pytest.fixture()
def async_mock():
    """Creates an async version of MagicMock."""

    class AsyncMock(MagicMock):
        async def __call__(self, *args, **kwargs):
            return super().__call__(*args, **kwargs)

    return AsyncMock


client = TestClient(ws_app)


def test_ws_main():
    response = client.get("/")
    http_ok = 200
    assert response.status_code == http_ok


@pytest.mark.asyncio()
async def test_webcommandcb_on_start(async_mock):
    ws = MagicMock()
    ws.send_json = async_mock()

    cmd = Command(name="test_cmd", cmd="echo 'Hello World'", status=CommandStatus.NOT_STARTED)

    cb = WebCommandCB(ws)
    await cb.on_start(cmd)


@pytest.mark.asyncio()
async def test_webcommandcb_on_recv(async_mock):
    ws = MagicMock()
    ws.send_json = async_mock()

    cmd = Command(name="test_cmd", cmd="echo 'Hello World'", status=CommandStatus.NOT_STARTED)

    cb = WebCommandCB(ws)
    await cb.on_recv(cmd, "Hello World")

    # Assert WebSocket send_json was called with the expected data
    assert ws.send_json.called
    assert ws.send_json.call_args[0][0] == {
        "commandName": "test_cmd",
        "output": "Hello World",
    }


@pytest.mark.asyncio()
async def test_webcommandcb_on_term_running(async_mock):
    # Mock WebSocket with async send_json
    ws = MagicMock()
    ws.send_json = async_mock()

    cmd = Command(name="test_cmd", cmd="echo 'Goodbye World'")

    # Initialize WebCommandCB with the mocked WebSocket
    cb = WebCommandCB(ws)

    # Invoke on_term method with an example exit code
    await cb.on_term(cmd, 0)

    # Assert WebSocket send_json was called with the expected data
    assert ws.send_json.called
    assert ws.send_json.call_args[0][0] == {
        "commandName": "test_cmd",
        "output": {"ret_code": 0},
    }


@pytest.mark.asyncio()
async def test_webcommandcb_on_term_success(async_mock):
    # Mock WebSocket with async send_json
    ws = MagicMock()
    ws.send_json = async_mock()

    cmd = Command(name="test_cmd", cmd="echo 'Goodbye World'")

    # Initialize WebCommandCB with the mocked WebSocket
    cb = WebCommandCB(ws)

    # Invoke on_term method with an example exit code
    cmd.status = CommandStatus.SUCCESS
    await cb.on_term(cmd, 0)

    # Assert WebSocket send_json was called with the expected data
    assert ws.send_json.called
    assert ws.send_json.call_args[0][0] == {
        "commandName": "test_cmd",
        "output": {"ret_code": 0},
    }


@pytest.mark.asyncio()
async def test_webcommandcb_on_term_fail(async_mock):
    # Mock WebSocket with async send_json
    ws = MagicMock()
    ws.send_json = async_mock()

    cmd = Command(name="test_cmd", cmd="echo 'Goodbye World'")

    # Initialize WebCommandCB with the mocked WebSocket
    cb = WebCommandCB(ws)

    # Invoke on_term method with an example exit code
    cmd.status = CommandStatus.FAILURE
    await cb.on_term(cmd, 1)

    # Assert WebSocket send_json was called with the expected data
    assert ws.send_json.called
    assert ws.send_json.call_args[0][0] == {
        "commandName": "test_cmd",
        "output": {"ret_code": 1},
    }


@pytest.mark.asyncio
async def test_get_commands_config():
    num_commands = 4
    response = await get_commands_config()
    assert response is not None
    assert len(response) == num_commands


@pytest.mark.skip("Not implemented")
@pytest.mark.asyncio
async def test_websocket_endpoint(async_mock):
    # Mock WebSocket with async accept
    websocket = AsyncMock()
    websocket.accept = async_mock()

    # Mock read_commands_toml function
    groups = ["group1", "group2"]
    read_commands_toml = MagicMock(return_value=groups)

    # Initialize WebCommandCB with the mocked WebSocket
    cb = WebCommandCB(websocket)
    cb.run_async = AsyncMock()
    # Invoke websocket_endpoint function
    await websocket_endpoint(websocket)

    # Assert WebSocket accept was called
    assert websocket.accept.called

    # Assert read_commands_toml was called with the expected arguments
    read_commands_toml.assert_called_once_with("commands.toml")

    # Assert cb.run_async was called for each group
    assert cb.run_async.call_count == len(groups)
    assert cb.run_async.call_args_list == [
        (("group1", ProcessingStrategy.ON_RECV, cb),),
        (("group2", ProcessingStrategy.ON_RECV, cb),),
    ]
