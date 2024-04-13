"""CLI for running commands in parallel"""

import contextlib
import enum
from collections import OrderedDict
from pathlib import Path
from typing import Annotated, Optional

import rich
import typer

from .executor import Command, CommandStatus, ProcessingStrategy, read_commands_toml

PID_FILE = ".par-run.uvicorn.pid"

cli_app = typer.Typer()


# Web only functions
def clean_up():
    """Clean up by removing the PID file."""
    Path(PID_FILE).unlink()
    typer.echo("Cleaned up PID file.")


def start_web_server(port: int):
    """Start the web server"""
    if Path(PID_FILE).is_file():
        typer.echo("UVicorn server is already running.")
        sys.exit(1)
    with Path(PID_FILE).open("w", encoding="utf-8") as pid_file:
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
    """Stop the UVicorn server by reading its PID from the PID file and sending a termination signal."""
    if not Path(PID_FILE).is_file():
        typer.echo("UVicorn server is not running.")
        return

    with Path(PID_FILE).open() as pid_file:
        pid = int(pid_file.read().strip())

    typer.echo(f"Stopping UVicorn server with {pid=:}...")
    with contextlib.suppress(ProcessLookupError):
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
    with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        for process in psutil.process_iter():
            process_name = process.name()
            if "uvicorn" in process_name.lower():
                uvicorn_processes.append(process)

    if uvicorn_processes:
        typer.echo("Other UVicorn processes:")
        for process in uvicorn_processes:
            typer.echo(f"PID: {process.pid}, Name: {process.name()}")
    else:
        typer.echo("No other UVicorn processes found.")


def get_web_server_status():
    """Get the status of the UVicorn server by reading its PID from the PID file."""
    if not Path(PID_FILE).is_file():
        typer.echo("No pid file found. Server likely not running.")
        list_uvicorn_processes()
        return

    with Path(PID_FILE).open() as pid_file:
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


class WebCommand(enum.Enum):
    """Web command enumeration."""

    START = "start"
    STOP = "stop"
    RESTART = "restart"
    STATUS = "status"

    def __str__(self):
        return self.value


class CLICommandCBOnComp:
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


class CLICommandCBOnRecv:
    def on_start(self, cmd: Command):
        rich.print(f"[blue bold]{cmd.name}: Started[/]")

    def on_recv(self, cmd: Command, output: str):
        rich.print(f"{cmd.name}: {output}")

    def on_term(self, cmd: Command, exit_code: int):
        """Callback function for when a command receives output"""
        if cmd.status == CommandStatus.SUCCESS:
            rich.print(f"[green bold]{cmd.name}: Finished[/]")
        elif cmd.status == CommandStatus.FAILURE:
            rich.print(f"[red bold]{cmd.name}: Failed, {exit_code=:}[/]")


def format_elapsed_time(seconds: float) -> str:
    """Converts a number of seconds into a human-readable time format of HH:MM:SS.xxx

    Args:
    ----
    seconds (float): The number of seconds elapsed.

    Returns:
    -------
    str: The formatted time string.

    """
    hours = int(seconds) // 3600
    minutes = (int(seconds) % 3600) // 60
    seconds = seconds % 60  # Keeping the fractional part of seconds

    # Return formatted string with seconds rounded to 2 d.p.
    return f"{hours:02}:{minutes:02}:{seconds:06.3f}"


style_default = typer.Option(help="Processing strategy", default="comp")
show_default = typer.Option(help="Show available groups and commands", default=False)
pyproj_default = typer.Option(help="The default toml file to use", default=Path("pyproject.toml"))
groups_default = typer.Option(help="Run a specific group of commands, comma spearated", default=None)
cmds_default = typer.Option(help="Run specific commands, comma separated", default=None)


@cli_app.command()
def run(  # noqa: PLR0912
    style: Annotated[ProcessingStrategy, typer.Option] = style_default,
    show: Annotated[bool, typer.Option] = show_default,
    file: Annotated[Path, typer.Option] = pyproj_default,
    groups: Annotated[Optional[str], typer.Option] = groups_default,
    cmds: Annotated[Optional[str], typer.Option] = cmds_default,
):
    """Run commands in parallel"""
    # Overall exit code, need to track all command exit codes to update this
    exit_code = 0
    st_all = time.perf_counter()

    master_groups = read_commands_toml(file)
    if show:
        for grp in master_groups:
            rich.print(f"[blue bold]Group: {grp.name}[/]")
            for cmd in grp.cmds.values():
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
                },
            )
        master_groups = [grp for grp in master_groups if grp.cmds]

    if not master_groups:
        rich.print("[blue]No groups or commands found.[/]")
        raise typer.Exit(0)

    for grp in master_groups:
        if style == ProcessingStrategy.ON_COMP:
            exit_code = grp.run(style, CLICommandCBOnComp())
        elif style == ProcessingStrategy.ON_RECV:
            exit_code = grp.run(style, CLICommandCBOnRecv())
        else:
            raise typer.BadParameter("Invalid processing strategy")
        if exit_code != 0 and not grp.cont_on_fail:
            break

    # Summarise the results
    console = rich.console.Console()
    res_tbl = rich.table.Table(title="Results", show_header=True, header_style="bold blue")
    res_tbl.add_column("Group", style="bold blue", width=10)
    res_tbl.add_column("Name", style="bold blue", width=15)
    res_tbl.add_column("Exec", style="bold blue", width=50, no_wrap=True)
    res_tbl.add_column("Status", style="bold blue", width=6)
    res_tbl.add_column("Elapsed", style="bold blue", width=12)
    for grp in master_groups:
        for cmd in grp.cmds.values():
            elap_str = format_elapsed_time(cmd.elapsed) if cmd.elapsed else "XX:XX:XX.xxx"

            if cmd.status == CommandStatus.SUCCESS:
                cmd_status = "✅"
            elif cmd.status == CommandStatus.FAILURE:
                cmd_status = "❌"
            else:
                cmd_status = "[yellow]❓[/]"

            row_style = "green" if cmd.status == CommandStatus.SUCCESS else "red"
            res_tbl.add_row(grp.name, cmd.name, cmd.cmd, cmd_status, elap_str, style=row_style)
    console.print(res_tbl)
    end_style = "[green bold]" if exit_code == 0 else "[red bold]"
    rich.print(f"\n{end_style}Total elapsed time: {format_elapsed_time(time.perf_counter() - st_all)}[/]")
    raise typer.Exit(exit_code)


try:
    import os
    import signal
    import subprocess
    import sys
    import time
    from pathlib import Path
    from typing import Optional

    import psutil
    import typer

    rich.print("[blue]Web commands loaded[/]")

    PID_FILE = ".par-run.uvicorn.pid"

    command_default = typer.Argument(..., help="command to control/interract with the web server")
    port_default = typer.Option(8001, help="Port to run the web server")

    @cli_app.command()
    def web(
        command: WebCommand = command_default,
        port: int = port_default,
    ):
        """Run the web server"""
        if command == WebCommand.START:
            start_web_server(port)
        elif command == WebCommand.STOP:
            stop_web_server()
        elif command == WebCommand.RESTART:
            stop_web_server()
            start_web_server(port)
        elif command == WebCommand.STATUS:
            get_web_server_status()
        else:
            typer.echo(f"Not a valid command '{command}'", err=True)
            raise typer.Abort()

except ImportError:  # pragma: no cover
    pass  # pragma: no cover

if __name__ == "__main__":
    cli_app()
