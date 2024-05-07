from collections import OrderedDict
from pathlib import Path
from typing import Any

import anyio
import pytest
import tomlkit

from par_run.executor import (
    Command,
    CommandGroup,
    CommandStatus,
    ProcessingStrategy,
    _get_optional_keys,
    _validate_mandatory_keys,
    read_commands_toml,
)
from par_run.executor import (
    internal_error_ret_code as internal_err_ret_code,
)
from py_tests.conftest import AnyIOBackendT


def test_command_incr_line_count() -> None:
    command = Command(name="test", cmd="echo 'Hello, World!'")
    assert command.num_non_empty_lines == 0

    command.incr_line_count("Hello, World!")
    assert command.num_non_empty_lines == 1

    command.incr_line_count("")
    assert command.num_non_empty_lines == 1


def test_command_append_unflushed() -> None:
    command = Command(name="test", cmd="echo 'Hello, World!'")
    assert command.unflushed == []

    command.append_unflushed("Hello, World!")
    assert command.unflushed == ["Hello, World!"]

    command.append_unflushed("")
    assert command.unflushed == ["Hello, World!", ""]


def test_command_set_running() -> None:
    command = Command(name="test", cmd="echo 'Hello, World!'")
    assert command.status == CommandStatus.NOT_STARTED

    command.set_running()
    assert command.status == CommandStatus.RUNNING  # type: ignore


class TestCommandCB:
    async def on_start(self, cmd: Command) -> None:
        assert cmd
        assert cmd.name.startswith("test")

    async def on_recv(self, cmd: Command, output: str) -> None:
        assert cmd
        assert cmd.name.startswith("test")
        assert output is not None

    async def on_term(self, cmd: Command, exit_code: int) -> None:
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


def test_command_group_parallel(anyio_backend: AnyIOBackendT) -> None:  # noqa: ARG001, ANN001
    command1 = Command(name="test1", cmd="echo 'Hello, World!'", passenv=["PATH"])
    command2 = Command(name="test2", cmd="echo 'World, Hey!'", setenv={"TEST": "test"})
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    anyio.run(group.run, ProcessingStrategy.ON_COMP, TestCommandCB())
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
    anyio.run(group.run, ProcessingStrategy.ON_RECV, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.status == CommandStatus.SUCCESS for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())


def test_command_group_serial(anyio_backend: AnyIOBackendT) -> None:  # noqa: ARG001, ANN001
    command1 = Command(name="test1", cmd="echo 'Hello, World!'", passenv=["PATH"])
    command2 = Command(name="test2", cmd="echo 'World, Hey!'", setenv={"TEST": "test"})
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands, serial=True)
    anyio.run(group.run, ProcessingStrategy.ON_COMP, TestCommandCB())
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
    anyio.run(group.run, ProcessingStrategy.ON_RECV, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.status == CommandStatus.SUCCESS for cmd in group.cmds.values())
    assert all(cmd.ret_code == 0 for cmd in group.cmds.values())


def test_command_group_serial_part_fail(anyio_backend: AnyIOBackendT) -> None:  # noqa: ARG001, ANN001
    command1 = Command(name="test1", cmd="echo 'Hello, World!' && exit 1", passenv=["PATH"])
    command2 = Command(name="test2", cmd="echo 'World, Hey!'", setenv={"TEST": "test"})
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands, serial=True)

    anyio.run(group.run, ProcessingStrategy.ON_COMP, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert command1.ret_code == 1
    assert command2.ret_code == internal_err_ret_code
    assert command1.status == CommandStatus.FAILURE
    assert command2.status == CommandStatus.CANCELLED
    assert command1.num_non_empty_lines == 1
    assert command2.num_non_empty_lines == 0
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())

    command1 = Command(name="test1", cmd="echo 'Hello, World!' && exit 1")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands, serial=True)
    anyio.run(group.run, ProcessingStrategy.ON_RECV, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert command1.ret_code == 1
    assert command2.ret_code == internal_err_ret_code
    assert command1.status == CommandStatus.FAILURE
    assert command2.status == CommandStatus.CANCELLED
    assert command1.num_non_empty_lines == 1
    assert command2.num_non_empty_lines == 0
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())


@pytest.fixture(
    params=[
        pytest.param(("asyncio", {"use_uvloop": True}), id="asyncio+uvloop"),
        pytest.param(("asyncio", {"use_uvloop": False}), id="asyncio"),
        pytest.param(("trio", {}), id="trio"),
    ]
)
def anyio_backend_asyncio(request: pytest.FixtureRequest) -> tuple[str, dict[str, Any]]:
    return request.param


def test_command_group_timeout_on_recv(anyio_backend_asyncio) -> None:  # noqa: ARG001, ANN001
    command1 = Command(name="test1", cmd="echo 'Hello, World!' && sleep 2 && exit 0", passenv=["PATH"])
    commands = OrderedDict()
    commands[command1.name] = command1
    group = CommandGroup(name="test_group", cmds=commands, timeout=1)
    anyio.run(group.run, ProcessingStrategy.ON_RECV, TestCommandCB())

    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code == internal_err_ret_code for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.status == CommandStatus.TIMEOUT for cmd in group.cmds.values())


def test_command_group_timeout_on_comp(anyio_backend_asyncio) -> None:  # noqa: ARG001, ANN001
    command1 = Command(name="test1", cmd="echo 'Hello, World!' && sleep 2 && exit 0", passenv=["PATH"])
    commands = OrderedDict()
    commands[command1.name] = command1
    group = CommandGroup(name="test_group", cmds=commands, timeout=1)
    anyio.run(group.run, ProcessingStrategy.ON_COMP, TestCommandCB())
    timeout_ret_code = 999
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code == timeout_ret_code for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(len(cmd.unflushed) > 0 for cmd in group.cmds.values())
    assert all(cmd.status == CommandStatus.TIMEOUT for cmd in group.cmds.values())


def test_command_group_part_fail(anyio_backend: AnyIOBackendT) -> None:  # noqa: ARG001, ANN001
    command1 = Command(name="test1", cmd="echo 'Hello, World!'")
    command2 = Command(name="test2", cmd="echo 'World, Hey!'; exit 1")
    commands = OrderedDict()
    commands[command1.name] = command1
    commands[command2.name] = command2
    group = CommandGroup(name="test_group", cmds=commands)
    anyio.run(group.run, ProcessingStrategy.ON_COMP, TestCommandCB())
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
    anyio.run(group.run, ProcessingStrategy.ON_RECV, TestCommandCB())
    assert all(cmd.status.completed() for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())
    assert all(cmd.num_non_empty_lines == 1 for cmd in group.cmds.values())
    assert all(cmd.unflushed == [] for cmd in group.cmds.values())
    assert all(cmd.status in [CommandStatus.SUCCESS, CommandStatus.FAILURE] for cmd in group.cmds.values())
    assert all(cmd.ret_code in [0, 1] for cmd in group.cmds.values())


async def test_command_group_async(anyio_backend: AnyIOBackendT) -> None:  # noqa: ARG001, ANN001
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


async def test_command_group_async_part_fail(anyio_backend: AnyIOBackendT) -> None:  # noqa: ARG001, ANN001
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


def test_validate_mandatory_keys() -> None:
    data = tomlkit.table()
    data["key1"] = "value1"
    data["key2"] = "value2"
    data["key3"] = "value3"

    keys = ["key1", "key2", "key3"]
    context = "test_context"

    result = _validate_mandatory_keys(data, keys, context)
    assert result == ("value1", "value2", "value3")


def test_validate_mandatory_keys_missing_key() -> None:
    data = tomlkit.table()
    data["key1"] = "value1"
    data["key3"] = "value3"

    keys = ["key1", "key2", "key3"]
    context = "test_context"

    with pytest.raises(ValueError) as exc_info:
        _validate_mandatory_keys(data, keys, context)

    assert str(exc_info.value) == "key2 is mandatory, not found in test_context"


def test__get_optional_keys() -> None:
    data = tomlkit.table()
    data["key1"] = "value1"
    data["key2"] = "value2"
    data["key3"] = "value3"

    keys = ["key1", "key2", "key3"]
    expected_result1 = ("value1", "value2", "value3")
    assert _get_optional_keys(data, keys) == expected_result1

    keys = ["key1", "key2", "key4"]
    expected_result2 = ("value1", "value2", None)
    assert _get_optional_keys(data, keys) == expected_result2

    keys = ["key4", "key5", "key6"]
    expected_result3 = (None, None, None)
    assert _get_optional_keys(data, keys) == expected_result3

    keys = []
    expected_result4 = ()
    assert _get_optional_keys(data, keys) == expected_result4

    data = tomlkit.table()
    keys = ["key1", "key2", "key3"]
    expected_result5 = (None, None, None)
    assert _get_optional_keys(data, keys) == expected_result5


@pytest.mark.parametrize("filename", ["pyproject.toml", "commands.toml"])
def test_read_commands_toml(filename: str) -> None:
    command_groups = read_commands_toml(filename)
    assert isinstance(command_groups, list)
    assert len(command_groups) > 0
    for group in command_groups:
        assert isinstance(group, CommandGroup)
        assert group.name
        assert isinstance(group.desc, str) or group.desc is None
        assert isinstance(group.cmds, OrderedDict)
        assert isinstance(group.timeout, int)
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


def test_read_commands_toml_missing_section(tmp_path: Path) -> None:
    # Create a valid TOML file without the par-run section
    toml_content = """
[BAD_HEADER]
desc = "par-run from pyproject.toml"
"""

    toml_file = tmp_path / "test_commands.toml"
    toml_file.write_text(toml_content)

    # Call the function and assert that it raises a ValueError
    with pytest.raises(ValueError):
        read_commands_toml(toml_file)


def test_read_commands_toml_pyproj(tmp_path: Path) -> None:
    # Create a valid TOML file without the par-run section
    toml_content = """
[tool.par-run]
desc = "par-run from pyproject.toml"

[[tool.par-run.groups]]
name = "Formatting"
desc = "Code formatting commands."
cont_on_fail = true # default is false
serial = false # default is false
timeout = 5

  [[tool.par-run.groups.commands]]
  name = "ruff_fmt"
  exec = "ruff format src py_tests"
  # Define an empty extras using standard table notation, or simply omit it if it's always empty

  [[tool.par-run.groups.commands]]
  name = "ruff_fix"
  exec = "ruff check --fix src py_tests"

[[tool.par-run.groups]]
name = "Formatting2"
desc = "Code formatting commands."
cont_on_fail = true # default is false
serial = true # default is false
timeout = 10

  [[tool.par-run.groups.commands]]
  name = "ruff_fmt"
  exec = "ruff format src py_tests"
  # Define an empty extras using standard table notation, or simply omit it if it's always empty

  [[tool.par-run.groups.commands]]
  name = "ruff_fix"
  exec = "ruff check --fix src py_tests"
    """

    toml_file = tmp_path / "pyproject.toml"
    toml_file.write_text(toml_content)

    num_groups = 2
    group_1_timeout = 5
    group_2_timeout = 10

    groups = read_commands_toml(toml_file)
    assert len(groups) == num_groups
    assert groups[0].name == "Formatting"
    assert groups[0].timeout == group_1_timeout
    assert groups[0].serial is False

    assert groups[1].name == "Formatting2"
    assert groups[1].timeout == group_2_timeout
    assert groups[1].serial


def test_read_commands_toml_non_pyproj(tmp_path: Path) -> None:
    # Create a valid TOML file without the par-run section
    toml_content = """
[par-run]
desc = "par-run from pyproject.toml"

[[par-run.groups]]
name = "Formatting"
desc = "Code formatting commands."
cont_on_fail = true # default is false
serial = false # default is false
timeout = 5

  [[par-run.groups.commands]]
  name = "ruff_fmt"
  exec = "ruff format src py_tests"
  # Define an empty extras using standard table notation, or simply omit it if it's always empty

  [[par-run.groups.commands]]
  name = "ruff_fix"
  exec = "ruff check --fix src py_tests"

[[par-run.groups]]
name = "Formatting2"
desc = "Code formatting commands."
cont_on_fail = true # default is false
serial = true # default is false
timeout = 10

  [[par-run.groups.commands]]
  name = "ruff_fmt"
  exec = "ruff format src py_tests"
  # Define an empty extras using standard table notation, or simply omit it if it's always empty

  [[par-run.groups.commands]]
  name = "ruff_fix"
  exec = "ruff check --fix src py_tests"
    """

    toml_file = tmp_path / "test_commands.toml"
    toml_file.write_text(toml_content)

    num_groups = 2
    group_1_timeout = 5
    group_2_timeout = 10

    groups = read_commands_toml(toml_file)
    assert len(groups) == num_groups
    assert groups[0].name == "Formatting"
    assert groups[0].timeout == group_1_timeout
    assert groups[0].serial is False

    assert groups[1].name == "Formatting2"
    assert groups[1].timeout == group_2_timeout
    assert groups[1].serial


def test_read_commands_toml_timeout_default(tmp_path: Path) -> None:
    # Create a valid TOML file without the par-run section
    toml_content = """
[par-run]
desc = "par-run from pyproject.toml"

[[par-run.groups]]
name = "Formatting"
desc = "Code formatting commands."
cont_on_fail = true # default is false
serial = false # default is false

  [[par-run.groups.commands]]
  name = "ruff_fmt"
  exec = "ruff format src py_tests"
  # Define an empty extras using standard table notation, or simply omit it if it's always empty

  [[par-run.groups.commands]]
  name = "ruff_fix"
  exec = "ruff check --fix src py_tests"
  # Define an empty extras using standard table notation, or simply omit it if it's always empty
    """

    toml_file = tmp_path / "test_commands.toml"
    toml_file.write_text(toml_content)

    groups = read_commands_toml(toml_file)
    default_timeout = 30
    assert groups[0].timeout == default_timeout
