import itertools

import psutil
import pytest
from typer.testing import CliRunner

from par_run.cli import (
    CLICommandCBOnComp,
    clean_up,
    cli_app,
    get_process_port,
    get_web_server_status,
    list_uvicorn_processes,
    start_web_server,
    stop_web_server,
)
from par_run.executor import Command, CommandGroup, CommandStatus

runner = CliRunner()


@pytest.fixture
def mock_command_group():
    command1 = Command(name="cmd1", cmd="echo 'Hello, World!'")
    command2 = Command(name="cmd2", cmd="echo 'Goodbye, World!'")
    commands = {"cmd1": command1, "cmd2": command2}
    return CommandGroup(name="group1", cmds=commands)


@pytest.fixture
def mock_command_group_part_fail():
    command1 = Command(name="cmd1", cmd="echo 'Hello, World!'")
    command2 = Command(name="cmd2", cmd="exit 1")
    commands = {"cmd1": command1, "cmd2": command2}
    return CommandGroup(name="group1", cmds=commands)


def test_run(mocker, mock_command_group):
    mocker.patch("par_run.cli.read_commands_ini", return_value=[mock_command_group])
    mocker.patch("par_run.cli.rich.print")
    result = runner.invoke(cli_app, ["run", "--show"])
    assert result.exit_code == 0


def test_CLICommandCB_on_start(mocker):
    mock_rich_print = mocker.patch("par_run.cli.rich.print")
    cb = CLICommandCBOnComp()
    command = Command(name="cmd1", cmd="echo 'Hello'")
    cb.on_start(command)
    mock_rich_print.assert_called_once()


def test_CLICommandCB_on_recv(mocker):
    mock_rich_print = mocker.patch("par_run.cli.rich.print")
    cb = CLICommandCBOnComp()
    command = Command(name="cmd1", cmd="echo 'Hello'")
    cb.on_recv(command, "Hello, World!")
    mock_rich_print.assert_called_once_with("Hello, World!")


@pytest.mark.parametrize("status", [CommandStatus.SUCCESS, CommandStatus.FAILURE])
def test_CLICommandCB_on_term(mocker, status):
    mock_rich_print = mocker.patch("par_run.cli.rich.print")
    cb = CLICommandCBOnComp()
    command = Command(name="cmd1", cmd="echo 'Hello'")
    command.status = status
    cb.on_term(command, 0)
    assert mock_rich_print.called


def test_clean_up(mocker, tmp_path):
    pid_file = tmp_path / ".par-run.uvicorn.pid"
    pid_file.write_text("1234")
    mocker.patch("par_run.cli.PID_FILE", str(pid_file))
    clean_up()
    assert not pid_file.exists()


@pytest.mark.parametrize("command", ["start", "stop", "restart", "status"])
def test_web(mocker, command):
    mocker.patch("par_run.cli.start_web_server")
    mocker.patch("par_run.cli.stop_web_server")
    mocker.patch("par_run.cli.get_web_server_status")
    result = runner.invoke(cli_app, ["web", command])
    assert result.exit_code == 0


def test_web_fail(mocker):
    mocker.patch("par_run.cli.start_web_server")
    mocker.patch("par_run.cli.stop_web_server")
    mocker.patch("par_run.cli.get_web_server_status")
    result = runner.invoke(cli_app, ["web", "NOT_A_CMD"])
    assert result.exit_code != 0


def test_start_web_server(mocker, tmp_path):
    mocker.patch("par_run.cli.subprocess.Popen")
    mocker.patch("par_run.cli.os.path.isfile", return_value=False)
    mocker.patch("par_run.cli.time.time_ns", side_effect=[0, 3 * 10**9 + 1])  # Simulate 3 seconds passing
    pid_file = tmp_path / ".par-run.uvicorn.pid"
    mocker.patch("par_run.cli.PID_FILE", str(pid_file))
    start_web_server(8000)
    assert pid_file.exists()


def test_start_web_server_running(mocker, tmp_path):
    # Setup: Mock subprocess.Popen to simulate the server process
    mock_process = mocker.MagicMock()
    mocker.patch("par_run.cli.subprocess.Popen", return_value=mock_process)
    mock_process.pid = 12345  # Example PID for the server process

    # Setup: Mock os.path.isfile to simulate the PID file does not exist initially
    mocker.patch("par_run.cli.os.path.isfile", return_value=False)

    # Setup: Mock time.time_ns to control the loop timing, ensuring it doesn't run out of values
    start_ns = 1000000
    time_ns_side_effect = itertools.chain([start_ns, start_ns + 1], itertools.repeat(start_ns + 2 * 10**9))
    mocker.patch("par_run.cli.time.time_ns", side_effect=time_ns_side_effect)

    # Setup: Mock get_process_port to return the correct port after the first loop iteration, ensuring it doesn't run out of values
    get_process_port_side_effect = itertools.chain(
        [None, 8000], itertools.repeat(8000)
    )  # First call: None, subsequent calls: 8000 (port number)
    mocker.patch("par_run.cli.get_process_port", side_effect=get_process_port_side_effect)

    # Setup: Mock typer.echo to capture output
    mock_echo = mocker.patch("par_run.cli.typer.echo")

    # Setup: Temporary PID file location
    pid_file = tmp_path / ".par-run.uvicorn.pid"
    mocker.patch("par_run.cli.PID_FILE", str(pid_file))

    # Execute: Call the function to test
    start_web_server(8000)

    # Verify: Check that the server is detected as running on the correct port
    mock_echo.assert_any_call("UVicorn server is running on port 8000 in 2000.00 ms.")

    # Cleanup: Ensure PID file is created
    assert pid_file.exists()


def test_stop_web_server(mocker, tmp_path):
    pid_file = tmp_path / ".par-run.uvicorn.pid"
    pid_file.write_text("1234")
    mocker.patch("par_run.cli.PID_FILE", str(pid_file))
    mocker.patch("par_run.cli.os.kill")
    stop_web_server()
    assert not pid_file.exists()


def test_get_web_server_status(mocker, tmp_path):
    pid_file = tmp_path / ".par-run.uvicorn.pid"
    mocker.patch("par_run.cli.PID_FILE", str(pid_file))
    mocker.patch("par_run.cli.typer.echo")
    # Test with no PID file
    get_web_server_status()
    pid_file.write_text("1234")
    # Test with PID file but no process
    mocker.patch("par_run.cli.psutil.pid_exists", return_value=False)
    get_web_server_status()
    # Test with PID file and process
    mocker.patch("par_run.cli.psutil.pid_exists", return_value=True)
    mocker.patch("par_run.cli.get_process_port", return_value=8000)
    get_web_server_status()


def test_run_with_specific_groups(mocker, mock_command_group):
    read_mock = mocker.patch("par_run.cli.read_commands_ini", return_value=[mock_command_group])
    mocker.patch("par_run.cli.rich.print")
    result = runner.invoke(cli_app, ["run", "--groups", "group1"])
    assert result.exit_code == 0
    read_mock.assert_called_once()


def test_run_with_fails(mocker, mock_command_group_part_fail):
    read_mock = mocker.patch("par_run.cli.read_commands_ini", return_value=[mock_command_group_part_fail])
    mocker.patch("par_run.cli.rich.print")
    result = runner.invoke(cli_app, ["run"])
    assert result.exit_code != 0
    read_mock.assert_called_once()


def test_run_with_specific_cmds(mocker, mock_command_group):
    mocker.patch("par_run.cli.read_commands_ini", return_value=[mock_command_group])
    mocker.patch("par_run.cli.rich.print")
    result = runner.invoke(cli_app, ["run", "--cmds", "cmd1"])
    assert result.exit_code == 0
    # Add additional assertions to check if the command was filtered correctly


def test_run_with_nonexistent_group(mocker, mock_command_group):
    mocker.patch("par_run.cli.read_commands_ini", return_value=[mock_command_group])
    mocker.patch("par_run.cli.rich.print")
    result = runner.invoke(cli_app, ["run", "--groups", "nonexistent"])
    assert result.exit_code == 0
    # Add assertion to ensure no commands are run and appropriate message is displayed


def test_run_with_nonexistent_cmd(mocker, mock_command_group):
    mocker.patch("par_run.cli.read_commands_ini", return_value=[mock_command_group])
    mocker.patch("par_run.cli.rich.print")
    result = runner.invoke(cli_app, ["run", "--cmds", "nonexistent"])
    assert result.exit_code == 0
    # Add assertion to ensure no commands are run and appropriate message is displayed


def test_start_web_server_already_running(mocker, tmp_path):
    pid_file = tmp_path / ".par-run.uvicorn.pid"
    pid_file.write_text("1234")
    mocker.patch("par_run.cli.PID_FILE", str(pid_file))
    mocker.patch("par_run.cli.typer.echo")
    with pytest.raises(SystemExit):
        start_web_server(8000)


def test_get_web_server_status_running(mocker, tmp_path):
    pid_file = tmp_path / ".par-run.uvicorn.pid"
    pid_file.write_text("1234")
    mocker.patch("par_run.cli.PID_FILE", str(pid_file))
    mocker.patch("par_run.cli.psutil.pid_exists", return_value=True)
    mocker.patch("par_run.cli.get_process_port", return_value=8000)
    mocker.patch("par_run.cli.typer.echo")
    get_web_server_status()
    # Add assertion to check the status message for a running server


def test_get_web_server_status_not_running_pid_file_exists(mocker, tmp_path):
    pid_file = tmp_path / ".par-run.uvicorn.pid"
    pid_file.write_text("1234")
    mocker.patch("par_run.cli.PID_FILE", str(pid_file))
    mocker.patch("par_run.cli.psutil.pid_exists", return_value=False)
    mocker.patch("par_run.cli.typer.echo")
    get_web_server_status()
    # Add assertion to check the status message and cleanup action when the server is not running but PID file exists


def test_start_web_server_failure_to_start(mocker, tmp_path):
    mocker.patch("par_run.cli.subprocess.Popen", side_effect=Exception("Failed to start"))
    pid_file = tmp_path / ".par-run.uvicorn.pid"
    mocker.patch("par_run.cli.PID_FILE", str(pid_file))
    mocker.patch("par_run.cli.typer.echo")
    with pytest.raises(Exception, match="Failed to start"):
        start_web_server(8000)


def test_stop_web_server_failure(mocker, tmp_path):
    pid_file = tmp_path / ".par-run.uvicorn.pid"
    pid_file.write_text("1234")
    mocker.patch("par_run.cli.PID_FILE", str(pid_file))
    mocker.patch("par_run.cli.os.kill", side_effect=Exception("Failed to kill"))
    mocker.patch("par_run.cli.typer.echo")
    with pytest.raises(Exception, match="Failed to kill"):
        stop_web_server()


def test_get_process_port(mocker):
    # Mock psutil.Process and its connections method
    mock_process = mocker.patch("par_run.cli.psutil.Process")
    mock_conn = mocker.MagicMock()
    mock_conn.laddr.port = 8000  # Example port number
    mock_process.return_value.connections.return_value = [mock_conn]

    port = get_process_port(1234)  # Example PID
    assert port == 8000


def test_get_process_port_no_connections(mocker):
    # Mock psutil.Process to return no connections
    mock_process = mocker.patch("par_run.cli.psutil.Process")
    mock_process.return_value.connections.return_value = []

    port = get_process_port(1234)  # Example PID
    assert port is None


def test_list_uvicorn_processes(mocker):
    # Mock psutil.process_iter to yield mock processes
    mock_process_iter = mocker.patch("par_run.cli.psutil.process_iter")
    mock_process_uvicorn = mocker.MagicMock()
    mock_process_uvicorn.name.return_value = "uvicorn"
    mock_process_uvicorn.pid = 1234
    mock_process_other = mocker.MagicMock()
    mock_process_other.name.return_value = "other_process"
    mock_process_iter.return_value = [mock_process_uvicorn, mock_process_other]

    mock_echo = mocker.patch("par_run.cli.typer.echo")

    list_uvicorn_processes()

    # Directly assert the calls made to typer.echo
    mock_echo.assert_any_call("Other UVicorn processes:")
    mock_echo.assert_any_call("PID: 1234, Name: uvicorn")


def test_list_no_uvicorn_processes(mocker):
    # Mock psutil.process_iter to yield no UVicorn processes
    mock_process_iter = mocker.patch("par_run.cli.psutil.process_iter")
    mock_process_other = mocker.MagicMock()
    mock_process_other.name.return_value = "other_process"
    mock_process_iter.return_value = [mock_process_other]

    mock_echo = mocker.patch("par_run.cli.typer.echo")

    list_uvicorn_processes()

    # Directly assert the calls made to typer.echo
    mock_echo.assert_any_call("No other UVicorn processes found.")


def test_list_uvicorn_processes_with_exceptions(mocker):
    # Mock psutil.process_iter to yield processes that raise exceptions
    mock_process_iter = mocker.patch("par_run.cli.psutil.process_iter")

    # Create mock processes that raise the exceptions when name() is called
    mock_process_no_such_process = mocker.MagicMock()
    mock_process_no_such_process.name.side_effect = psutil.NoSuchProcess(pid=123)

    mock_process_access_denied = mocker.MagicMock()
    mock_process_access_denied.name.side_effect = psutil.AccessDenied(pid=456)

    mock_process_zombie_process = mocker.MagicMock()
    mock_process_zombie_process.name.side_effect = psutil.ZombieProcess(pid=789)

    mock_process_iter.return_value = [
        mock_process_no_such_process,
        mock_process_access_denied,
        mock_process_zombie_process,
    ]

    # Mock typer.echo to capture output
    mock_echo = mocker.patch("par_run.cli.typer.echo")

    list_uvicorn_processes()

    # Since all processes raise exceptions, the output should indicate no UVicorn processes found
    mock_echo.assert_any_call("No other UVicorn processes found.")

    # Optionally, assert that the exceptions were caught and did not cause the function to fail
    # This can be inferred from the fact that the function executed to completion and made the expected call to mock_echo


def test_get_web_server_status_running_no_port(mocker, tmp_path):
    # Setup: Create a temporary PID file with a mock PID
    pid_file = tmp_path / ".par-run.uvicorn.pid"
    pid_file.write_text("1234")  # Example PID
    mocker.patch("par_run.cli.PID_FILE", str(pid_file))

    # Mock psutil.pid_exists to return True, indicating the process exists
    mocker.patch("par_run.cli.psutil.pid_exists", return_value=True)

    # Mock get_process_port to return None, simulating an inability to determine the port
    mocker.patch("par_run.cli.get_process_port", return_value=None)

    # Mock typer.echo to capture output
    mock_echo = mocker.patch("par_run.cli.typer.echo")

    # Execute: Call the function to test
    get_web_server_status()

    # Verify: Check that the appropriate message is output when the port cannot be determined
    mock_echo.assert_any_call("UVicorn server is running with pid=1234, couldn't determine port.")
