import multiprocessing as mp
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
import pytest
from par_run.executor import (
    Command,
    CommandGroup,
    CommandStatus,
    run_command,
    ProcessingStrategy,
    read_commands_ini,
    write_commands_ini,
)


def test_command_incr_line_count():
    command = Command(name="test", cmd="echo 'Hello, World!'")
    assert command.num_non_empty_lines == 0

    command.incr_line_count("Hello, World!")
    assert command.num_non_empty_lines == 1

    command.incr_line_count("")
    assert command.num_non_empty_lines == 1


def test_command_append_unflushed():
    command = Command(name="test", cmd="echo 'Hello, World!'")
    assert command.unflushed == []

    command.append_unflushed("Hello, World!")
    assert command.unflushed == ["Hello, World!"]

    command.append_unflushed("")
    assert command.unflushed == ["Hello, World!", ""]


def test_command_set_ret_code_success():
    command = Command(name="test", cmd="echo 'Hello, World!'")
    assert command.ret_code is None
    assert command.status == CommandStatus.NOT_STARTED
    assert not command.status.completed()

    q = mp.Manager().Queue()
    pool = ProcessPoolExecutor()
    fut = pool.submit(run_command, command.name, command.cmd, q)
    command.fut = fut
    _ = fut.result()

    msg = q.get()
    assert isinstance(msg, tuple)
    assert len(msg) == 2
    assert msg[0] == command.name
    assert msg[1] == "Hello, World!"
    exit_code = q.get()[1]

    command.set_ret_code(exit_code)
    assert command.ret_code == 0
    assert command.status == CommandStatus.SUCCESS
    assert command.fut is None
    assert command.status.completed()


def test_command_set_ret_code_failure():
    command = Command(name="test", cmd="echo 'Hello, World!'")
    assert command.ret_code is None
    assert command.status == CommandStatus.NOT_STARTED

    command.set_ret_code(1)
    assert command.ret_code == 1
    assert command.status == CommandStatus.FAILURE
    assert command.fut is None


def test_command_set_running():
    command = Command(name="test", cmd="echo 'Hello, World!'")
    assert command.status == CommandStatus.NOT_STARTED

    command.set_running()
    assert command.status == CommandStatus.RUNNING


class TestCommandCB:
    def on_start(self, cmd: Command):
        print(f"Test start command {cmd.name}")

    def on_recv(self, cmd: Command, output: str):
        print(f"{cmd.name}: {output}")

    def on_term(self, cmd: Command, exit_code: int):
        """Callback function for when a command receives output"""
        if cmd.status == CommandStatus.SUCCESS:
            print(f"Command {cmd.name} finished")
        elif cmd.status == CommandStatus.FAILURE:
            print(f"Command {cmd.name} failed, {exit_code=:}")


class TestCommandCBAsync:
    async def on_start(self, cmd: Command):
        print(f"Test start command {cmd.name}")

    async def on_recv(self, cmd: Command, output: str):
        print(f"{cmd.name}: {output}")

    async def on_term(self, cmd: Command, exit_code: int):
        """Callback function for when a command receives output"""
        if cmd.status == CommandStatus.SUCCESS:
            print(f"Command {cmd.name} finished")
        elif cmd.status == CommandStatus.FAILURE:
            print(f"Command {cmd.name} failed, {exit_code=:}")


def test_command_group():
    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    group.run(ProcessingStrategy.AS_COMPLETED, TestCommandCB())

    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    group.run(ProcessingStrategy.ON_RECV, TestCommandCB())


@pytest.mark.asyncio
async def test_command_group_async():
    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    await group.run_async(ProcessingStrategy.AS_COMPLETED, TestCommandCBAsync())

    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    await group.run_async(ProcessingStrategy.ON_RECV, TestCommandCBAsync())


def test_run_command():
    q = mp.Manager().Queue()
    run_command("Test", "echo 'Hello, World!'", q)

    msg = q.get()
    assert isinstance(msg, tuple)
    assert len(msg) == 2
    assert msg[0] == "Test"
    assert msg[1] == "Hello, World!"
    exit_code = q.get()[1]

    assert exit_code == 0


@pytest.fixture
def command_data():
    return {
        "group.test": [
            ("command1", "do something"),
            ("command2", "do something else"),
        ]
    }


@pytest.fixture
def expected_command_groups():
    return [
        CommandGroup(
            name="test",
            cmds=OrderedDict(
                [
                    ("command1", Command(name="command1", cmd="do something")),
                    ("command2", Command(name="command2", cmd="do something else")),
                ]
            ),
        )
    ]


def test_read_commands_ini(mocker, command_data, expected_command_groups):
    # Mock ConfigParser and its methods
    mock_config_parser = mocker.patch("par_run.executor.configparser.ConfigParser")
    mock_config_instance = mock_config_parser.return_value
    mock_config_instance.read = mocker.MagicMock()
    mock_config_instance.sections.return_value = list(command_data.keys())
    mock_config_instance.items.side_effect = lambda section: command_data[section]

    # Call the function under test
    result = read_commands_ini("dummy_path")

    # Assert the result
    assert len(result) == len(expected_command_groups)
    for res_group, exp_group in zip(result, expected_command_groups):
        assert res_group.name == exp_group.name
        assert list(res_group.cmds.keys()) == list(exp_group.cmds.keys())
        for cmd_name in res_group.cmds:
            assert res_group.cmds[cmd_name].cmd == exp_group.cmds[cmd_name].cmd


def test_write_and_read_commands_ini(expected_command_groups, tmp_path):
    # Use tmp_path to create a temporary file path for the INI file
    temp_file = tmp_path / "commands.ini"

    # Write the command groups to the temporary INI file
    write_commands_ini(temp_file, expected_command_groups)

    # Read back the command groups from the INI file
    read_command_groups = read_commands_ini(temp_file)

    # Compare the original command groups with the ones read from the file
    assert len(expected_command_groups) == len(read_command_groups), "Number of command groups mismatch"

    for original, read_back in zip(expected_command_groups, read_command_groups):
        assert original.name == read_back.name, "Command group name mismatch"
        assert len(original.cmds) == len(read_back.cmds), "Number of commands in a group mismatch"

        for cmd_name, cmd in original.cmds.items():
            assert cmd_name in read_back.cmds, f"Command {cmd_name} not found in read command group"
            assert cmd.cmd == read_back.cmds[cmd_name].cmd, f"Command {cmd_name} mismatch"
