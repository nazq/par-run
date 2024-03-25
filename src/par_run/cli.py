"""CLI for running commands in parallel"""

import multiprocessing as mp
import queue
import sys
from collections import OrderedDict
from pathlib import Path
from queue import Queue
from typing import Optional

import rich
import typer

from .executor import (CommandGroup, CommandStatus, generic_pool,
                       read_commands_ini, run_command)

cli_app = typer.Typer()


@cli_app.command()
def run(
    show: bool = typer.Option(help="Show available groups and commands", default=False),
    file: Path = typer.Option(
        help="The commands.ini file to use", default=Path("commands.ini")
    ),
    groups: Optional[str] = typer.Option(
        None, help="Run a specific group of commands, comma spearated"
    ),
    cmds: Optional[str] = typer.Option(
        None, help="Run a specific commands, comma spearated"
    ),
):
    """Run commands in parallel"""
    # Overall exit code, need to track all command exit codes to update this
    exit_code = 0

    master_groups = read_commands_ini(file)
    if show:
        for grp in master_groups:
            rich.print(f"[blue bold]Group: {grp.name}[/]")
            for _, cmd in grp.cmds.items():
                rich.print(f"[green bold]{cmd.name}[/]: {cmd.cmd}")
        return

    if groups:
        master_groups = [
            grp
            for grp in master_groups
            if grp.name in [g.strip() for g in groups.split(",")]
        ]

    if cmds:
        for grp in master_groups:
            grp.cmds = OrderedDict(
                {
                    cmd_name: cmd
                    for cmd_name, cmd in grp.cmds.items()
                    if cmd_name in [c.strip() for c in cmds.split(",")]
                }
            )
        master_groups = [grp for grp in master_groups if grp.cmds]

    q = mp.Manager().Queue()

    for grp in master_groups:
        exit_code = exit_code or cli_process_group(grp, q)

    # Summarise the results
    for grp in master_groups:
        rich.print(f"[blue bold]Group: {grp.name}[/]")
        for _, cmd in grp.cmds.items():
            if cmd.status == CommandStatus.SUCCESS:
                rich.print(
                    f"[green bold]Command {cmd.name} succeeded ({cmd.num_non_empty_lines})[/]"
                )
            else:
                rich.print(
                    f"[red bold]Command {cmd.name} failed ({cmd.num_non_empty_lines})[/]"
                )

    sys.exit(exit_code)


def cli_process_group(commands: CommandGroup, q: Queue) -> int:
    """Process a group of commands. Return the exit code of the group."""
    exit_code = 0
    rich.print(f"[blue bold]Running group: {commands.name}[/]")
    futs = [
        generic_pool.submit(run_command, cmd.name, cmd.cmd, q)
        for _, cmd in commands.cmds.items()
    ]
    for (_, cmd), fut in zip(commands.cmds.items(), futs):
        cmd.fut = fut

    get_timeout_cnt = 0
    max_get_timeouts = 5
    while True:
        try:
            q_result = q.get(block=True, timeout=30)
        except queue.Empty:
            q_result = None
            get_timeout_cnt += 1
            if get_timeout_cnt > max_get_timeouts:
                exit_code = commands.cancel_running()
                break

        if q_result:
            if isinstance(q_result[1], int):
                ret_code = q_result[1]
                exit_code = exit_code or ret_code
                # Set command status
                commands.cmds[q_result[0]].set_ret_code(ret_code)

                if commands.cmds[q_result[0]].status == CommandStatus.SUCCESS:
                    rich.print(f"[green bold]Command {q_result[0]} finished[/]")
                elif commands.cmds[q_result[0]].status == CommandStatus.FAILURE:
                    rich.print(f"[red bold]Command {q_result[0]} failed[/]")
                else:
                    rich.print(
                        (
                            f"[red bold]Logic error {q_result[0]} returned {ret_code} ",
                            f"but status set to {commands.cmds[q_result[0]].status}[/]",
                        )
                    )
                for line in commands.cmds[q_result[0]].output:
                    rich.print(line)
            else:
                commands.cmds[q_result[0]].append_output(q_result[1])

        if all(commands.cmds[cmd].status.completed() for cmd in commands.cmds):
            break
    return exit_code
