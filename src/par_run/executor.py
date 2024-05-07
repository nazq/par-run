"""Todo"""

import enum
import os
import subprocess
import time
from collections import OrderedDict
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Any, Optional, Protocol, Union, cast

import anyio
import anyio.to_thread
import tomlkit
from pydantic import BaseModel, ConfigDict, Field

internal_error_ret_code = 999


class ProcessingStrategy(enum.Enum):
    """Enum for processing strategies."""

    ON_COMP = "comp"
    ON_RECV = "recv"


class CommandStatus(enum.Enum):
    """Enum for command status."""

    NOT_STARTED = "Not Started"
    RUNNING = "Running"
    SUCCESS = "Success"
    FAILURE = "Failure"
    TIMEOUT = "Timeout"
    CANCELLED = "Cancelled"

    def completed(self) -> bool:
        """Return True if the command has completed."""
        return self in [CommandStatus.SUCCESS, CommandStatus.FAILURE, CommandStatus.TIMEOUT, CommandStatus.CANCELLED]


class Command(BaseModel):
    """Holder for a command and its name."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    cmd: str
    passenv: Optional[list[str]] = Field(default=None)
    setenv: Optional[dict[str, str]] = Field(default=None)
    status: CommandStatus = CommandStatus.NOT_STARTED
    unflushed: list[str] = Field(default=[], exclude=True)
    num_non_empty_lines: int = Field(default=0, exclude=True)
    ret_code: Optional[int] = Field(default=None, exclude=True)
    start_time: Optional[float] = Field(default=None, exclude=True)
    elapsed: Optional[float] = Field(default=None, exclude=True)

    def incr_line_count(self, line: str) -> None:
        """Increment the non-empty line count."""
        if line.strip():
            self.num_non_empty_lines += 1

    def append_unflushed(self, line: str) -> None:
        """Append a line to the output and increment the non-empty line count."""
        self.unflushed.append(line)

    def clear_unflushed(self) -> None:
        """Clear the unflushed output."""
        self.unflushed.clear()

    def set_ret_code(self, ret_code: int) -> None:
        """Set the return code and status of the command."""
        if self.start_time:
            self.elapsed = time.perf_counter() - self.start_time
        self.ret_code = ret_code
        if ret_code == 0:
            self.status = CommandStatus.SUCCESS
        else:
            self.status = CommandStatus.FAILURE

    def set_timeout(self) -> None:
        """Set the command status to timeout."""
        self.status = CommandStatus.TIMEOUT
        if self.start_time:
            self.elapsed = time.perf_counter() - self.start_time
        self.ret_code = internal_error_ret_code

    def set_running(self) -> None:
        """Set the command status to running."""
        self.start_time = time.perf_counter()
        self.status = CommandStatus.RUNNING

    def set_cancelled(self) -> None:
        """Set the command status to cancelled."""
        self.status = CommandStatus.CANCELLED
        self.ret_code = internal_error_ret_code


class CommandCB(Protocol):
    async def on_start(self, cmd: Command) -> None: ...
    async def on_recv(self, cmd: Command, output: str) -> None: ...
    async def on_term(self, cmd: Command, exit_code: int) -> None: ...


class CommandGroup(BaseModel):
    """Holder for a group of commands."""

    name: str
    desc: Optional[str] = None
    cmds: OrderedDict[str, Command] = Field(default_factory=OrderedDict)
    timeout: int = Field(default=30)
    cont_on_fail: bool = Field(default=False)
    serial: bool = Field(default=False)
    status: CommandStatus = CommandStatus.NOT_STARTED

    def update_status(self, cmds: OrderedDict[str, Command]) -> None:
        """Update the status of the command group."""
        if all(cmd.status == CommandStatus.SUCCESS for cmd in cmds.values()):
            self.status = CommandStatus.SUCCESS
        else:
            self.status = CommandStatus.FAILURE

    async def run_serial(self, callbacks: CommandCB) -> None:
        try:
            for ix in range(len(self.cmds.values())):
                cmd = list(self.cmds.values())[ix]
                cmd.set_running()
                async with anyio.create_task_group() as nursery:
                    nursery.start_soon(self._run_command, cmd, ProcessingStrategy.ON_RECV, callbacks)
                if cmd.status != CommandStatus.SUCCESS and not self.cont_on_fail:
                    # Cancel all remaining cmds
                    for jx in range(ix + 1, len(self.cmds.values())):
                        cmd = list(self.cmds.values())[jx]
                        cmd.set_cancelled()
                    self.update_status(self.cmds)
                    break
        except Exception as _:
            self.status = CommandStatus.FAILURE
        else:
            self.update_status(self.cmds)

    async def run_parallel(self, strategy: ProcessingStrategy, callbacks: CommandCB) -> None:
        try:
            async with anyio.create_task_group() as nursery:
                for cmd in self.cmds.values():
                    nursery.start_soon(self._run_command, cmd, strategy, callbacks)
                    cmd.set_running()
        except Exception as _:
            self.status = CommandStatus.FAILURE
        else:
            self.update_status(self.cmds)

    async def run(self, strategy: ProcessingStrategy, callbacks: CommandCB) -> None:
        if self.serial:
            await self.run_serial(callbacks)
        else:
            await self.run_parallel(strategy, callbacks)

    async def _proces_stdxx_line(
        self, cmd: Command, line: str, strategy: ProcessingStrategy, callbacks: CommandCB
    ) -> None:
        if strategy == ProcessingStrategy.ON_RECV:
            await callbacks.on_recv(cmd, line)
        elif strategy == ProcessingStrategy.ON_COMP:
            cmd.append_unflushed(line)
        cmd.incr_line_count(line)

    async def _process_stdxxx(
        self, cmd: Command, strategy: ProcessingStrategy, stream: AsyncIterable[bytes], callbacks: CommandCB
    ) -> None:
        await callbacks.on_start(cmd)

        incomplete_line = ""

        async for chunk in stream:
            # Decode the bytes to a string
            decoded_chunk = chunk.decode("utf-8")
            # Combine the remainder of the last chunk with the new chunk
            lines = (incomplete_line + decoded_chunk).split("\n")

            # The last line might be incomplete; hold it back
            incomplete_line = lines.pop() if lines[-1] else ""

            for line in lines:
                await self._proces_stdxx_line(cmd, line, strategy, callbacks)

        if incomplete_line:
            await self._proces_stdxx_line(cmd, incomplete_line, strategy, callbacks)  # pragma: no cover

        if strategy == ProcessingStrategy.ON_COMP:
            for _ix, line in enumerate(cmd.unflushed):
                await callbacks.on_recv(cmd, line)
            cmd.clear_unflushed()

    async def _run_command(self, cmd: Command, strategy: ProcessingStrategy, callbacks: CommandCB) -> int:
        env = os.environ.copy()
        if cmd.setenv:
            env.update(cmd.setenv)

        # Running the command asynchronously and capturing the output
        try:
            with anyio.fail_after(self.timeout):
                async with (
                    await anyio.open_process(
                        command=cmd.cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
                    ) as process,
                    anyio.create_task_group() as tg,
                ):
                    if process.stdout:
                        tg.start_soon(self._process_stdxxx, cmd, strategy, process.stdout, callbacks)
                    await process.wait()
        except TimeoutError:
            cmd.set_timeout()
            await callbacks.on_term(cmd, internal_error_ret_code)
            return internal_error_ret_code
        else:
            exit_code = cast(int, process.returncode)
            cmd.set_ret_code(exit_code)
            await callbacks.on_term(cmd, exit_code)
            return exit_code


def _validate_mandatory_keys(data: tomlkit.items.Table, keys: list[str], context: str) -> tuple[Any, ...]:
    """Validate that the mandatory keys are present in the data.

    Args:
    ----
        data (tomlkit.items.Table): The data to validate.
        keys (list[str]): The mandatory keys.

    """
    vals = []
    for key in keys:
        val = data.get(key, None)
        if not val:
            raise ValueError(f"{key} is mandatory, not found in {context}")
        vals.append(val)
    return tuple(vals)


def _get_optional_keys(data: tomlkit.items.Table, keys: list[str], default: Any = None) -> tuple[Optional[Any], ...]:  # noqa: ANN001, ANN401
    """Get Optional keys or default.

    Args:
    ----
        data (tomlkit.items.Table): The data to use as source
        keys (list[str]): The optional keys.

    """
    res = tuple(data.get(key, default) for key in keys)
    return res


def read_commands_toml(filename: Union[str, Path]) -> list[CommandGroup]:
    """Read a commands.toml file and return a list of CommandGroup objects.

    Args:
    ----
        filename (Union[str, Path]): The filename of the commands.toml file.

    Returns:
    -------
        list[CommandGroup]: A list of CommandGroup objects.

    """
    with Path(filename).open(encoding="utf-8") as toml_file:
        toml_data = tomlkit.parse(toml_file.read())

    if (isinstance(filename, Path) and filename.name == "pyproject.toml") or (
        isinstance(filename, str) and filename == "pyproject.toml"
    ):
        cmd_groups_data = toml_data.get("tool", {}).get("par-run", {})
    else:
        cmd_groups_data = toml_data.get("par-run", None)

    if not cmd_groups_data:
        raise ValueError(f"No par-run data found in toml file {filename}")
    _ = cmd_groups_data.get("description", None)

    command_groups = []
    for group_data in cmd_groups_data.get("groups", []):
        (group_name,) = _validate_mandatory_keys(group_data, ["name"], "top level par-run group")
        group_desc, group_timeout = _get_optional_keys(
            group_data,
            ["desc", "timeout"],
            default=None,
        )
        (group_cont_on_fail, group_serial) = _get_optional_keys(group_data, ["cont_on_fail", "serial"], default=False)

        if not group_timeout:
            group_timeout = 30
        group_cont_on_fail = bool(group_cont_on_fail and group_cont_on_fail is True)
        group_serial = bool(group_serial and group_serial is True)

        commands = OrderedDict()
        for cmd_data in group_data.get("commands", []):
            name, exec = _validate_mandatory_keys(cmd_data, ["name", "exec"], f"command group {group_name}")
            setenv, passenv = _get_optional_keys(cmd_data, ["setenv", "passenv"], default=None)

            commands[name] = Command(name=name, cmd=exec, setenv=setenv, passenv=passenv)
        command_group = CommandGroup(
            name=group_name,
            desc=group_desc,
            cmds=commands,
            timeout=group_timeout,
            cont_on_fail=group_cont_on_fail,
            serial=group_serial,
        )
        command_groups.append(command_group)

    return command_groups
