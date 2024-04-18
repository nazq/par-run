import multiprocessing as mp
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Queue

import pytest
import tomlkit

from par_run.executor import (
    Command,
    CommandGroup,
    CommandStatus,
    ProcessingStrategy,
    QRetriever,
    _get_optional_keys,
    _validate_mandatory_keys,
    read_commands_toml,
    run_command,
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
    fut = pool.submit(run_command, command.name, command.cmd, {}, q)
    command.fut = fut
    command.set_running()
    _ = fut.result()

    msg = q.get()
    assert isinstance(msg, tuple)
    exp_msg_len = 2
    assert len(msg) == exp_msg_len
    assert msg[0] == command.name
    assert msg[1] == "Hello, World!"
    exit_code = q.get()[1]

    command.set_ret_code(exit_code)
    assert command.ret_code == 0
    assert command.status == CommandStatus.SUCCESS
    assert command.fut is None
    assert command.status.completed()


def test_command_set_ret_code_failure():
    command = Command(name="test", cmd="exit 1")
    q = mp.Manager().Queue()
    pool = ProcessPoolExecutor()
    fut = pool.submit(run_command, command.name, command.cmd, {}, q)
    command.set_running()
    command.fut = fut
    _ = fut.result()
    msg = q.get()

    assert isinstance(msg, tuple)
    exp_msg_len = 2
    assert len(msg) == exp_msg_len
    assert msg[0] == command.name
    exit_code = msg[1]
    command.set_ret_code(exit_code)
    assert command.ret_code == exit_code
    assert command.status == CommandStatus.FAILURE
    assert command.fut is None
    assert command.status.completed()


def test_command_set_running():
    command = Command(name="test", cmd="echo 'Hello, World!'")
    assert command.status == CommandStatus.NOT_STARTED

    command.set_running()
    assert command.status == CommandStatus.RUNNING


class TestCommandCB:
    def on_start(self, cmd: Command):
        assert cmd
        assert cmd.name.startswith("test")

    def on_recv(self, cmd: Command, output: str):
        assert cmd
        assert cmd.name.startswith("test")
        assert output

    def on_term(self, cmd: Command, exit_code: int):
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


class TestCommandCBAsync:
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
    group_exit = group.run(ProcessingStrategy.ON_COMP, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.fut is None for cmd in group.cmds.values())
    assert all(cmd.status == CommandStatus.SUCCESS for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())
    assert group_exit == 0

    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    group_exit = group.run(ProcessingStrategy.ON_RECV, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.fut is None for cmd in group.cmds.values())
    assert all(cmd.status == CommandStatus.SUCCESS for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())
    assert group_exit == 0


def test_command_group_part_fail():
    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'; exit 1")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    group_exit = group.run(ProcessingStrategy.ON_COMP, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.fut is None for cmd in group.cmds.values())
    assert all(cmd.status in [CommandStatus.SUCCESS, CommandStatus.FAILURE] for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())
    assert group_exit == 1

    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'; exit 1")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    group_exit = group.run(ProcessingStrategy.ON_RECV, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.fut is None for cmd in group.cmds.values())
    assert all(cmd.status in [CommandStatus.SUCCESS, CommandStatus.FAILURE] for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())
    assert group_exit == 1


@pytest.mark.asyncio()
async def test_command_group_async():
    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    await group.run_async(ProcessingStrategy.ON_COMP, TestCommandCBAsync())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.fut is None for cmd in group.cmds.values())
    assert all(cmd.status == CommandStatus.SUCCESS for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())

    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    await group.run_async(ProcessingStrategy.ON_RECV, TestCommandCBAsync())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.fut is None for cmd in group.cmds.values())
    assert all(cmd.status == CommandStatus.SUCCESS for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())


@pytest.mark.asyncio()
async def test_command_group_async_part_fail():
    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'; exit 1")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    group_exit = await group.run_async(ProcessingStrategy.ON_COMP, TestCommandCBAsync())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.fut is None for cmd in group.cmds.values())
    assert all(cmd.status in [CommandStatus.SUCCESS, CommandStatus.FAILURE] for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())
    assert group_exit == 1

    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'; exit 1")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    group_exit = await group.run_async(ProcessingStrategy.ON_RECV, TestCommandCBAsync())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.fut is None for cmd in group.cmds.values())
    assert all(cmd.status in [CommandStatus.SUCCESS, CommandStatus.FAILURE] for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())
    assert group_exit == 1


def test_run_command():
    q = mp.Manager().Queue()
    run_command("Test", "echo 'Hello, World!'", {}, q)

    msg = q.get()
    assert isinstance(msg, tuple)
    exp_msg_len = 2
    assert len(msg) == exp_msg_len
    assert msg[0] == "Test"
    assert msg[1] == "Hello, World!"
    exit_code = q.get()[1]
    assert exit_code == 0


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


@pytest.mark.parametrize("setenv", [None, {"key": "value"}])
def test_run_command_w_env(setenv):
    q = mp.Queue()
    run_command("test", "echo 'Hello, World!'", setenv, q)
    output = q.get()
    assert output[0] == "test"
    assert isinstance(output[1], (int, str))


def test_qretriever_get():
    q = Queue()
    q.put("Hello, World!")
    retriever = QRetriever(q, timeout=1, retries=0)
    result = retriever.get()
    assert result == "Hello, World!"


def test_qretriever_get_timeout():
    q = Queue()
    retriever = QRetriever(q, timeout=1, retries=0)
    try:
        retriever.get()
        raise AssertionError()
    except TimeoutError as e:
        assert str(e) == "Timeout waiting for command output"


def test_qretriever_get_retry():
    q = Queue()
    retriever = QRetriever(q, timeout=1, retries=2)
    try:
        retriever.get()
        raise AssertionError("TimeoutError not raised")
    except TimeoutError as e:
        assert str(e) == "Timeout waiting for command output"


def test_qretriever_str():
    q = Queue()
    retriever = QRetriever(q, timeout=1, retries=0)
    result = str(retriever)
    assert result == "QRetriever(timeout=1, retries=0)"
