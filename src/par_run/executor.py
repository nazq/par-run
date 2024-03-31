"""Todo"""

import asyncio
import configparser
import enum
import multiprocessing as mp
import queue
import subprocess
from collections import OrderedDict
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path
from queue import Queue
from typing import List, Optional, Protocol, TypeVar, Union
from pydantic import BaseModel, Field, ConfigDict


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
    status: CommandStatus = CommandStatus.NOT_STARTED
    unflushed: List[str] = Field(default=[], exclude=True)
    num_non_empty_lines: int = Field(default=0, exclude=True)
    ret_code: Optional[int] = Field(default=None, exclude=True)
    fut: Optional[GenFuture] = Field(default=None, exclude=True)

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


class CommandGroup(BaseModel):
    """Holder for a group of commands."""

    name: str
    cmds: OrderedDict[str, Command] = Field(default_factory=OrderedDict)

    async def run_async(
        self,
        strategy: ProcessingStrategy,
        callbacks: CommandAsyncCB,
    ):
        q = mp.Manager().Queue()
        pool = ProcessPoolExecutor()
        futs = [
            asyncio.get_event_loop().run_in_executor(pool, run_command, cmd.name, cmd.cmd, q)
            for _, cmd in self.cmds.items()
        ]

        for (_, cmd), fut in zip(self.cmds.items(), futs):
            cmd.fut = fut
            cmd.set_running()

        return await self._process_q_async(q, strategy, callbacks)

    def run(
        self,
        strategy: ProcessingStrategy,
        callbacks: CommandCB,
    ):
        q = mp.Manager().Queue()
        pool = ProcessPoolExecutor()
        futs = [pool.submit(run_command, cmd.name, cmd.cmd, q) for _, cmd in self.cmds.items()]
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

        timeout = 10
        retries = 3
        q_ret = QRetriever(q, timeout, retries)
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

        timeout = 10
        retries = 3
        q_ret = QRetriever(q, timeout, retries)
        while True:
            await asyncio.sleep(0)
            q_result = q_ret.get()

            # Can only get here with a valid message from the Q
            cmd_name = q_result[0]
            # print(q_result, type(q_result[0]), type(q_result[1]))
            exit_code: Optional[int] = q_result[1] if isinstance(q_result[1], int) else None
            output_line: Optional[str] = q_result[1] if isinstance(q_result[1], str) else None
            # print(output_line, exit_code)
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


def run_command(name: str, command: str, q: Queue) -> None:
    """Run a command and put the output into a queue. The output is a tuple of the command
    name and the output line. The final output is a tuple of the command name and a dictionary
    with the return code.

    Args:
        name (str): Name of the command.
        command (str): Command to run.
        q (Queue): Queue to put the output into.
    """

    with subprocess.Popen(
        f"{command}",
        shell=True,
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
