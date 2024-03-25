"""Todo"""

import asyncio
import configparser
import enum
import subprocess
from collections import OrderedDict
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path
from queue import Queue
from typing import List, Optional, Union

import rich
from pydantic import BaseModel, ConfigDict, Field

generic_pool = ProcessPoolExecutor()


class CommandStatus(enum.Enum):
    """Enum for command status."""

    NOT_STARTED = "Not Started"
    RUNNING = "Running"
    SUCCESS = "Success"
    FAILURE = "Failure"

    def completed(self) -> bool:
        """Return True if the command has completed."""
        return self in [CommandStatus.SUCCESS, CommandStatus.FAILURE]


GenFuture = Union[Future, asyncio.Future]


class Command(BaseModel):
    """Holder for a command and its name."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    cmd: str
    status: CommandStatus = CommandStatus.NOT_STARTED
    output: List[str] = []
    num_non_empty_lines: int = 0
    ret_code: Optional[int] = None
    fut: Optional[GenFuture] = Field(default=None, exclude=True)

    def append_output(self, line: str) -> None:
        """Append a line to the output and increment the non-empty line count."""
        self.output.append(line)
        if line.strip():
            self.num_non_empty_lines += 1

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


class CommandGroup(BaseModel):
    """Holder for a group of commands."""

    name: str
    cmds: OrderedDict[str, Command]

    def cancel_running(self) -> int:
        """Cancel all running commands in the group and return the exit code."""
        exit_code = 999
        for _, cmd in self.cmds.items():
            if cmd.status == CommandStatus.RUNNING:
                rich.print(
                    f"[red bold]Command {cmd} timed out, cancelling, ret_code == {exit_code}[/]"
                )
                if cmd.fut:
                    cmd.fut.cancel()
                    cmd.fut = None
                cmd.set_ret_code(exit_code)
        return exit_code


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
        f"rye run {command}",
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
                q.put((name, ret_code))
            raise ValueError("Process has no return code")
