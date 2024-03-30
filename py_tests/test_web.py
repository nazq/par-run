from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from par_run.executor import Command, CommandStatus
from par_run.web import WebCommandCB, ws_app


@pytest.fixture
def async_mock():
    """Creates an async version of MagicMock."""

    class AsyncMock(MagicMock):
        async def __call__(self, *args, **kwargs):
            return super(AsyncMock, self).__call__(*args, **kwargs)

    return AsyncMock


client = TestClient(ws_app)


def test_ws_main():
    response = client.get("/")
    assert response.status_code == 200


def test_get_commands_config(mocker):
    # Mock read_commands_ini to return a known value
    mock_read = mocker.patch("par_run.web.read_commands_ini", return_value=[{"name": "test", "cmds": []}])

    response = client.get("/get-commands-config")
    assert response.status_code == 200
    assert response.json() == [{"name": "test", "cmds": []}]
    mock_read.assert_called_once_with("commands.ini")


@pytest.mark.skip(reason="Need to align pydantic models")
def test_update_commands_config(mocker):
    # Mock write_commands_ini to do nothing
    mocker.patch("par_run.web.write_commands_ini")

    command_group_payload = [
        {
            "name": "test_group",
            "cmds": [
                {"name": "command1", "cmd": "echo Hello World"},
                {"name": "command2", "cmd": "echo Goodbye World"},
            ],
        }
    ]

    response = client.post("/update-commands-config", json=command_group_payload)
    assert response.status_code == 200


@pytest.mark.skip(reason="WebSocket testing is not yet implemented")
@pytest.mark.asyncio
async def test_websocket_endpoint(mocker):
    # Mock read_commands_ini and CommandGroup.run_async if necessary
    mocker.patch("par_run.web.read_commands_ini", return_value=[])
    mock_run_async = mocker.patch("par_run.executor.CommandGroup.run_async", return_value=0)

    print("websocket_endpoint1")
    # Connect to the WebSocket endpoint
    with client.websocket_connect("/ws") as websocket:
        # Send a message to initiate command execution or any other interaction
        # Adjust this part based on how your WebSocket endpoint is supposed to be used
        while True:
            response = websocket.receive_json()
            print(response)  # Print each response for inspection

            # Add a condition to break the loop when all responses are received
            # This condition depends on your WebSocket server's implementation
            if "ret_code" in response:  # Example condition, adjust as necessary
                break

    # Verify that run_async was called if it's part of the WebSocket interaction
    mock_run_async.assert_awaited()


@pytest.mark.skip(reason="WebSocket testing is not yet implemented")
@pytest.mark.asyncio
async def test_webcommandcb_on_start(async_mock):
    ws = MagicMock()
    ws.send_json = async_mock()

    cmd = Command(name="test_cmd", cmd="echo 'Hello World'", status=CommandStatus.NOT_STARTED)

    cb = WebCommandCB(ws)
    await cb.on_start(cmd)

    # Since ws.send_json is an async mock, you should check if it's awaited with the expected arguments
    ws.send_json.assert_awaited_with({"commandName": cmd.name, "output": "[blue bold]Started command test_cmd[/]"})


@pytest.mark.asyncio
async def test_webcommandcb_on_recv(async_mock):
    # Mock WebSocket with async send_json
    ws = MagicMock()
    ws.send_json = async_mock()

    cmd = Command(name="test_cmd", cmd="echo 'Hello World'")

    # Initialize WebCommandCB with the mocked WebSocket
    cb = WebCommandCB(ws)

    # Invoke on_recv method
    await cb.on_recv(cmd, "Hello World")

    # Assert WebSocket send_json was called with the expected data
    assert ws.send_json.called
    assert ws.send_json.call_args[0][0] == {
        "commandName": "test_cmd",
        "output": "Hello World",
    }


@pytest.mark.asyncio
async def test_webcommandcb_on_term(async_mock):
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
