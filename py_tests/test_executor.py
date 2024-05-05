from collections import OrderedDict

import pytest
import tomlkit
import trio

from par_run.executor import (
    Command,
    CommandGroup,
    CommandStatus,
    ProcessingStrategy,
    _get_optional_keys,
    _validate_mandatory_keys,
    read_commands_toml,
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


def test_command_set_running():
    command = Command(name="test", cmd="echo 'Hello, World!'")
    assert command.status == CommandStatus.NOT_STARTED

    command.set_running()
    assert command.status == CommandStatus.RUNNING


class TestCommandCB:
    async def on_start(self, cmd: Command):
        assert cmd
        assert cmd.name.startswith("test")

    async def on_recv(self, cmd: Command, output: str):
        assert cmd
        assert cmd.name.startswith("test")
        assert output

    async def on_term(self, cmd: Command, exit_code: int):
        assert cmd
        assert cmd.name.startswith("test")
        assert isinstance(exit_code, int)

        """Callback function for when a command receives output"""
        if cmd.status == CommandStatus.SUCCESS:
            assert cmd.status.completed()
            assert cmd.ret_code == 0
        elif cmd.status == CommandStatus.FAILURE:
            assert cmd.status.completed()
            assert cmd.ret_code != 0


def test_command_group():
    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    trio.run(group.run, ProcessingStrategy.ON_COMP, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.status == CommandStatus.SUCCESS for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())

    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    trio.run(group.run, ProcessingStrategy.ON_RECV, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.status == CommandStatus.SUCCESS for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())


def test_command_group_part_fail():
    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'; exit 1")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    trio.run(group.run, ProcessingStrategy.ON_COMP, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.status in [CommandStatus.SUCCESS, CommandStatus.FAILURE] for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())

    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'; exit 1")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    trio.run(group.run, ProcessingStrategy.ON_RECV, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.status in [CommandStatus.SUCCESS, CommandStatus.FAILURE] for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())


async def test_command_group_async():
    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    await group.run(ProcessingStrategy.ON_COMP, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.status == CommandStatus.SUCCESS for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())

    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    await group.run(ProcessingStrategy.ON_RECV, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.status == CommandStatus.SUCCESS for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())


async def test_command_group_async_part_fail():
    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'; exit 1")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    await group.run(ProcessingStrategy.ON_COMP, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.status in [CommandStatus.SUCCESS, CommandStatus.FAILURE] for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())
    assert group.status == CommandStatus.FAILURE

    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'; exit 1")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    await group.run(ProcessingStrategy.ON_RECV, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.status in [CommandStatus.SUCCESS, CommandStatus.FAILURE] for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())
    assert group.status == CommandStatus.FAILURE


def test_validate_mandatory_keys():
    data = tomlkit.table()
    data["key1"] = "value1"
    data["key2"] = "value2"
    data["key3"] = "value3"

    keys = ["key1", "key2", "key3"]
    context = "test_context"

    result = _validate_mandatory_keys(data, keys, context)
    assert result == ("value1", "value2", "value3")


def test_validate_mandatory_keys_missing_key():
    data = tomlkit.table()
    data["key1"] = "value1"
    data["key3"] = "value3"

    keys = ["key1", "key2", "key3"]
    context = "test_context"

    with pytest.raises(ValueError) as exc_info:
        _validate_mandatory_keys(data, keys, context)

    assert str(exc_info.value) == "key2 is mandatory, not found in test_context"


def test__get_optional_keys():
    data = tomlkit.table()
    data["key1"] = "value1"
    data["key2"] = "value2"
    data["key3"] = "value3"

    keys = ["key1", "key2", "key3"]
    expected_result = ("value1", "value2", "value3")
    assert _get_optional_keys(data, keys) == expected_result

    keys = ["key1", "key2", "key4"]
    expected_result = ("value1", "value2", None)
    assert _get_optional_keys(data, keys) == expected_result

    keys = ["key4", "key5", "key6"]
    expected_result = (None, None, None)
    assert _get_optional_keys(data, keys) == expected_result

    keys = []
    expected_result = ()
    assert _get_optional_keys(data, keys) == expected_result

    data = tomlkit.table()
    keys = ["key1", "key2", "key3"]
    expected_result = (None, None, None)
    assert _get_optional_keys(data, keys) == expected_result


@pytest.mark.parametrize("filename", ["pyproject.toml", "commands.toml"])
def test_read_commands_toml(filename):
    command_groups = read_commands_toml(filename)
    assert isinstance(command_groups, list)
    assert len(command_groups) > 0
    for group in command_groups:
        assert isinstance(group, CommandGroup)
        assert group.name
        assert isinstance(group.desc, str) or group.desc is None
        assert isinstance(group.cmds, OrderedDict)
        assert isinstance(group.timeout, int)
        assert isinstance(group.retries, int)
        assert isinstance(group.cont_on_fail, bool)
        assert isinstance(group.serial, bool)

        for cmd_name, cmd in group.cmds.items():
            assert isinstance(cmd, Command)
            assert cmd.name == cmd_name
            assert cmd.cmd

    # Test case 2: Invalid commands.toml file
    with pytest.raises(FileNotFoundError):
        filename = "invalid_commands.toml"
        read_commands_toml(filename)


def test_read_commands_toml_missing_section(tmp_path):
    # Create a valid TOML file without the par-run section
    toml_content = """
    [command_group]
    name = "Test Group"
    desc = "Test description"
    timeout = 30
    retries = 3
    cont_on_fail = false
    serial = false

    [[command_group.cmds]]
    name = "Test Command"
    cmd = "echo 'Hello, World!'"
    """

    toml_file = tmp_path / "test_commands.toml"
    toml_file.write_text(toml_content)

    # Call the function and assert that it raises a ValueError
    with pytest.raises(ValueError):
        read_commands_toml(toml_file)
