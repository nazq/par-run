"""CLI for running commands in parallel"""

import os
import signal
import subprocess
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import psutil
import rich
import typer

from .executor import Command, CommandStatus, ProcessingStrategy, read_commands_ini

PID_FILE = ".par-run.uvicorn.pid"

cli_app = typer.Typer()


@cli_app.command()
def run(
    show: bool = typer.Option(help="Show available groups and commands", default=False),
    file: Path = typer.Option(help="The commands.ini file to use", default=Path("commands.ini")),
    groups: Optional[str] = typer.Option(None, help="Run a specific group of commands, comma spearated"),
    cmds: Optional[str] = typer.Option(None, help="Run a specific commands, comma spearated"),
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
        master_groups = [grp for grp in master_groups if grp.name in [g.strip() for g in groups.split(",")]]

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

    #  q = mp.Manager().Queue()
    cb = CLICommandCB()
    for grp in master_groups:
        exit_code = exit_code or grp.run(ProcessingStrategy.AS_COMPLETED, cb)

    # Summarise the results
    for grp in master_groups:
        rich.print(f"[blue bold]Group: {grp.name}[/]")
        for _, cmd in grp.cmds.items():
            if cmd.status == CommandStatus.SUCCESS:
                rich.print(f"[green bold]Command {cmd.name} succeeded ({cmd.num_non_empty_lines})[/]")
            else:
                rich.print(f"[red bold]Command {cmd.name} failed ({cmd.num_non_empty_lines})[/]")

    sys.exit(exit_code)


class CLICommandCB:
    def on_start(self, cmd: Command):
        rich.print(f"[blue bold]Completed command {cmd.name}[/]")

    def on_recv(self, _: Command, output: str):
        rich.print(output)

    def on_term(self, cmd: Command, exit_code: int):
        """Callback function for when a command receives output"""
        if cmd.status == CommandStatus.SUCCESS:
            rich.print(f"[green bold]Command {cmd.name} finished[/]")
        elif cmd.status == CommandStatus.FAILURE:
            rich.print(f"[red bold]Command {cmd.name} failed, {exit_code=:}[/]")


def clean_up():
    """
    Clean up by removing the PID file.
    """
    os.remove(PID_FILE)
    typer.echo("Cleaned up PID file.")


def start_web_server(port: int):
    """Start the web server"""
    if os.path.isfile(PID_FILE):
        typer.echo("UVicorn server is already running.")
        sys.exit(1)
    with open(PID_FILE, "w", encoding="utf-8") as pid_file:
        typer.echo(f"Starting UVicorn server on port {port}...")
        uvicorn_command = [
            "uvicorn",
            "par_run.web:ws_app",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
        ]
        process = subprocess.Popen(uvicorn_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pid_file.write(str(process.pid))

        # Wait for UVicorn to start
        wait_time = 3 * 10**9  # 3 seconds
        start_time = time.time_ns()

        while time.time_ns() - start_time < wait_time:
            test_port = get_process_port(process.pid)
            if port == test_port:
                typer.echo(f"UVicorn server is running on port {port} in {(time.time_ns() - start_time)/10**6:.2f} ms.")
                break
            time.sleep(0.1)  # Poll every 0.1 seconds

        else:
            typer.echo(f"UVicorn server did not respond within {wait_time} seconds.")
            typer.echo("run 'par-run web status' to check the status.")


def stop_web_server():
    """
    Stop the UVicorn server by reading its PID from the PID file and sending a termination signal.
    """
    if not os.path.isfile(PID_FILE):
        typer.echo("UVicorn server is not running.")
        sys.exit(1)

    with open(PID_FILE, "r") as pid_file:
        pid = int(pid_file.read().strip())

    typer.echo(f"Stopping UVicorn server with {pid=:}...")
    os.kill(pid, signal.SIGTERM)
    clean_up()


def get_process_port(pid: int) -> Optional[int]:
    process = psutil.Process(pid)
    connections = process.connections()
    if connections:
        port = connections[0].laddr.port
        return port
    return None


def list_uvicorn_processes():
    """Check for other UVicorn processes and list them"""
    uvicorn_processes = []
    for process in psutil.process_iter():
        try:
            process_name = process.name()
            if "uvicorn" in process_name.lower():
                uvicorn_processes.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    if uvicorn_processes:
        typer.echo("Other UVicorn processes:")
        for process in uvicorn_processes:
            typer.echo(f"PID: {process.pid}, Name: {process.name()}")
    else:
        typer.echo("No other UVicorn processes found.")


def get_web_server_status():
    """
    Get the status of the UVicorn server by reading its PID from the PID file.
    """
    if not os.path.isfile(PID_FILE):
        typer.echo("No pid file found. Server likely not running.")
        list_uvicorn_processes()
        return

    with open(PID_FILE, "r") as pid_file:
        pid = int(pid_file.read().strip())
        if psutil.pid_exists(pid):
            port = get_process_port(pid)
            if port:
                typer.echo(f"UVicorn server is running with {pid=}, {port=}")
            else:
                typer.echo(f"UVicorn server is running with {pid=:}, couldn't determine port.")
        else:
            typer.echo("UVicorn server is not running but pid files exists, deleting it.")
            clean_up()


@cli_app.command()
def web(
    command: str = typer.Argument(..., help="Start/Stop the web server"),
    port: int = typer.Option(8001, help="Port to run the web server"),
):
    """Run the web server"""
    if command == "start":
        start_web_server(port)
    elif command == "stop":
        stop_web_server()
    elif command == "restart":
        stop_web_server()
        start_web_server(port)
    elif command == "status":
        get_web_server_status()
    else:
        typer.echo("Command must be either 'start' or 'stop'", err=True)
        raise typer.Abort()
