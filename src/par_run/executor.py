"""Todo"""

import asyncio
import configparser
import enum
import multiprocessing as mp
import os
import queue
import subprocess
from collections import OrderedDict
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path
from queue import Queue
import time
from typing import List, Optional, Protocol, TypeVar, Union, Any
from pydantic import BaseModel, Field, ConfigDict
import tomlkit

# Type alias for a generic future.
GenFuture = Union[Future, asyncio.Future]

ContextT = TypeVar("ContextT")


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

    def completed(self) -> bool:
        """Return True if the command has completed."""
        return self in [CommandStatus.SUCCESS, CommandStatus.FAILURE]


class Command(BaseModel):
    """Holder for a command and its name."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    cmd: str
    passenv: Optional[list[str]] = Field(default=None)
    setenv: Optional[dict[str, str]] = Field(default=None)
    status: CommandStatus = CommandStatus.NOT_STARTED
    unflushed: List[str] = Field(default=[], exclude=True)
    num_non_empty_lines: int = Field(default=0, exclude=True)
    ret_code: Optional[int] = Field(default=None, exclude=True)
    fut: Optional[GenFuture] = Field(default=None, exclude=True)
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

    def set_ret_code(self, ret_code: int):
        """Set the return code and status of the command."""
        if self.start_time:
            self.elapsed = time.perf_counter() - self.start_time
        self.ret_code = ret_code
        if self.fut:
            self.fut.cancel()
            self.fut = None
        if ret_code == 0:
            self.status = CommandStatus.SUCCESS
        else:
            self.status = CommandStatus.FAILURE

    def set_running(self):
        """Set the command status to running."""
        self.start_time = time.perf_counter()
        self.status = CommandStatus.RUNNING


class CommandCB(Protocol):
    def on_start(self, cmd: Command) -> None: ...
    def on_recv(self, cmd: Command, output: str) -> None: ...
    def on_term(self, cmd: Command, exit_code: int) -> None: ...


class CommandAsyncCB(Protocol):
    async def on_start(self, cmd: Command) -> None: ...
    async def on_recv(self, cmd: Command, output: str) -> None: ...
    async def on_term(self, cmd: Command, exit_code: int) -> None: ...


class QRetriever:
    def __init__(self, q: Queue, timeout: int, retries: int):
        self.q = q
        self.timeout = timeout
        self.retries = retries

    def get(self):
        retry_count = 0
        while True:
            try:
                return self.q.get(block=True, timeout=self.timeout)
            except queue.Empty:
                if retry_count < self.retries:
                    retry_count += 1
                    continue
                else:
                    raise TimeoutError("Timeout waiting for command output")

    def __str__(self) -> str:
        return f"QRetriever(timeout={self.timeout}, retries={self.retries})"


class CommandGroup(BaseModel):
    """Holder for a group of commands."""

    name: str
    desc: Optional[str] = None
    cmds: OrderedDict[str, Command] = Field(default_factory=OrderedDict)
    timeout: int = Field(default=30)
    retries: int = Field(default=3)

    async def run_async(
        self,
        strategy: ProcessingStrategy,
        callbacks: CommandAsyncCB,
    ):
        q = mp.Manager().Queue()
        pool = ProcessPoolExecutor()
        futs = [
            asyncio.get_event_loop().run_in_executor(pool, run_command, cmd.name, cmd.cmd, cmd.setenv, q)
            for _, cmd in self.cmds.items()
        ]

        for (_, cmd), fut in zip(self.cmds.items(), futs):
            cmd.fut = fut
            cmd.set_running()

        return await self._process_q_async(q, strategy, callbacks)

    def run(self, strategy: ProcessingStrategy, callbacks: CommandCB):
        q = mp.Manager().Queue()
        pool = ProcessPoolExecutor()
        futs = [pool.submit(run_command, cmd.name, cmd.cmd, cmd.setenv, q) for _, cmd in self.cmds.items()]
        for (_, cmd), fut in zip(self.cmds.items(), futs):
            cmd.fut = fut
            cmd.set_running()
        return self._process_q(q, strategy, callbacks)

    def _process_q(
        self,
        q: Queue,
        strategy: ProcessingStrategy,
        callbacks: CommandCB,
    ) -> int:
        grp_exit_code = 0

        if strategy == ProcessingStrategy.ON_RECV:
            for _, cmd in self.cmds.items():
                callbacks.on_start(cmd)

        q_ret = QRetriever(q, self.timeout, self.retries)
        while True:
            q_result = q_ret.get()

            # Can only get here with a valid message from the Q
            cmd_name = q_result[0]
            exit_code: Optional[int] = q_result[1] if isinstance(q_result[1], int) else None
            output_line: Optional[str] = q_result[1] if isinstance(q_result[1], str) else None
            if exit_code is None and output_line is None:
                raise ValueError("Invalid Q message")  # pragma: no cover

            cmd = self.cmds[cmd_name]
            if strategy == ProcessingStrategy.ON_RECV:
                if output_line is not None:
                    cmd.incr_line_count(output_line)
                    callbacks.on_recv(cmd, output_line)
                elif exit_code is not None:
                    cmd.set_ret_code(exit_code)
                    callbacks.on_term(cmd, exit_code)
                    if exit_code != 0:
                        grp_exit_code = 1
                else:
                    raise ValueError("Invalid Q message")  # pragma: no cover

            if strategy == ProcessingStrategy.ON_COMP:
                if output_line is not None:
                    cmd.incr_line_count(output_line)
                    cmd.append_unflushed(output_line)
                elif exit_code is not None:
                    callbacks.on_start(cmd)
                    for line in cmd.unflushed:
                        callbacks.on_recv(cmd, line)
                    cmd.clear_unflushed()
                    callbacks.on_term(cmd, exit_code)
                    cmd.set_ret_code(exit_code)
                    if exit_code != 0:
                        grp_exit_code = 1
                else:
                    raise ValueError("Invalid Q message")  # pragma: no cover

            if all(cmd.status.completed() for _, cmd in self.cmds.items()):
                break
        return grp_exit_code

    async def _process_q_async(
        self,
        q: Queue,
        strategy: ProcessingStrategy,
        callbacks: CommandAsyncCB,
    ) -> int:
        grp_exit_code = 0

        if strategy == ProcessingStrategy.ON_RECV:
            for _, cmd in self.cmds.items():
                await callbacks.on_start(cmd)

        q_ret = QRetriever(q, self.timeout, self.retries)
        while True:
            await asyncio.sleep(0)
            q_result = q_ret.get()

            # Can only get here with a valid message from the Q
            cmd_name = q_result[0]
            exit_code: Optional[int] = q_result[1] if isinstance(q_result[1], int) else None
            output_line: Optional[str] = q_result[1] if isinstance(q_result[1], str) else None
            if exit_code is None and output_line is None:
                raise ValueError("Invalid Q message")  # pragma: no cover

            cmd = self.cmds[cmd_name]
            if strategy == ProcessingStrategy.ON_RECV:
                if output_line is not None:
                    cmd.incr_line_count(output_line)
                    await callbacks.on_recv(cmd, output_line)
                elif exit_code is not None:
                    cmd.set_ret_code(exit_code)
                    await callbacks.on_term(cmd, exit_code)
                    if exit_code != 0:
                        grp_exit_code = 1
                else:
                    raise ValueError("Invalid Q message")  # pragma: no cover

            if strategy == ProcessingStrategy.ON_COMP:
                if output_line is not None:
                    cmd.incr_line_count(output_line)
                    cmd.append_unflushed(output_line)
                elif exit_code is not None:
                    await callbacks.on_start(cmd)
                    for line in cmd.unflushed:
                        await callbacks.on_recv(cmd, line)
                    cmd.clear_unflushed()
                    await callbacks.on_term(cmd, exit_code)
                    cmd.set_ret_code(exit_code)
                    if exit_code != 0:
                        grp_exit_code = 1
                else:
                    raise ValueError("Invalid Q message")  # pragma: no cover

            if all(cmd.status.completed() for _, cmd in self.cmds.items()):
                break
        return grp_exit_code


def read_commands_ini(filename: Union[str, Path]) -> list[CommandGroup]:
    """Read a commands.ini file and return a list of CommandGroup objects.

    Args:
        filename (Union[str, Path]): The filename of the commands.ini file.

    Returns:
        list[CommandGroup]: A list of CommandGroup objects.
    """
    config = configparser.ConfigParser()
    config.read(filename)

    command_groups = []
    for section in config.sections():
        if section.startswith("group."):
            group_name = section.replace("group.", "")
            commands = OrderedDict()
            for name, cmd in config.items(section):
                name = name.strip()
                commands[name] = Command(name=name, cmd=cmd.strip())
            command_group = CommandGroup(name=group_name, cmds=commands)
            command_groups.append(command_group)

    return command_groups


def write_commands_ini(filename: Union[str, Path], command_groups: list[CommandGroup]):
    """Write a list of CommandGroup objects to a commands.ini file.

    Args:
        filename (Union[str, Path]): The filename of the commands.ini file.
        command_groups (list[CommandGroup]): A list of CommandGroup objects.
    """
    config = configparser.ConfigParser()

    for group in command_groups:
        section_name = f"group.{group.name}"
        config[section_name] = {}
        for _, command in group.cmds.items():
            config[section_name][command.name] = command.cmd

    with open(filename, "w", encoding="utf-8") as configfile:
        config.write(configfile)


def _validate_mandatory_keys(data: tomlkit.items.Table, keys: list[str], context: str) -> tuple[Any, ...]:
    """Validate that the mandatory keys are present in the data.

    Args:
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


def _get_optional_keys(data: tomlkit.items.Table, keys: list[str], default=None) -> tuple[Optional[Any], ...]:
    """Get Optional keys or default.

    Args:
        data (tomlkit.items.Table): The data to use as source
        keys (list[str]): The optional keys.
    """
    return tuple(data.get(key, default) for key in keys)


def read_commands_toml(filename: Union[str, Path]) -> list[CommandGroup]:
    """Read a commands.toml file and return a list of CommandGroup objects.

    Args:
        filename (Union[str, Path]): The filename of the commands.toml file.

    Returns:
        list[CommandGroup]: A list of CommandGroup objects.
    """

    with open(filename, "r", encoding="utf-8") as toml_file:
        toml_data = tomlkit.parse(toml_file.read())

    cmd_groups_data = toml_data.get("tool", {}).get("par-run", {})
    if not cmd_groups_data:
        raise ValueError("No par-run data found in toml file")
    _ = cmd_groups_data.get("description", None)

    command_groups = []
    for group_data in cmd_groups_data.get("groups", []):
        (group_name,) = _validate_mandatory_keys(group_data, ["name"], "top level par-run group")
        group_desc, group_timeout, group_retries = _get_optional_keys(
            group_data, ["desc", "timeout", "retries"], default=None
        )

        if not group_timeout:
            group_timeout = 30
        if not group_retries:
            group_retries = 3

        commands = OrderedDict()
        for cmd_data in group_data.get("commands", []):
            name, exec = _validate_mandatory_keys(cmd_data, ["name", "exec"], f"command group {group_name}")
            setenv, passenv = _get_optional_keys(cmd_data, ["setenv", "passenv"], default=None)

            commands[name] = Command(name=name, cmd=exec, setenv=setenv, passenv=passenv)
        command_group = CommandGroup(
            name=group_name, desc=group_desc, cmds=commands, timeout=group_timeout, retries=group_retries
        )
        command_groups.append(command_group)

    return command_groups


def run_command(name: str, command: str, setenv: Optional[dict[str, str]], q: Queue) -> None:
    """Run a command and put the output into a queue. The output is a tuple of the command
    name and the output line. The final output is a tuple of the command name and a dictionary
    with the return code.

    Args:
        name (Command): Command to run.
        q (Queue): Queue to put the output into.
    """

    new_env = None
    if setenv:
        new_env = os.environ.copy()
        new_env.update(setenv)

    with subprocess.Popen(
        command,
        shell=True,
        env=new_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ) as process:
        if process.stdout:
            for line in iter(process.stdout.readline, ""):
                q.put((name, line.strip()))
            process.stdout.close()
            process.wait()
            ret_code = process.returncode
            if ret_code is not None:
                q.put((name, int(ret_code)))
            else:
                raise ValueError("Process has no return code")  # pragma: no cover
