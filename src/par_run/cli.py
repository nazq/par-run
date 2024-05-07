"""CLI for running commands in parallel"""

import contextlib
import enum
from collections import OrderedDict
from pathlib import Path
from typing import Annotated, Any, Optional

import anyio
import rich
import typer

from .executor import Command, CommandGroup, CommandStatus, ProcessingStrategy, read_commands_toml

PID_FILE = ".par-run.uvicorn.pid"

cli_app = typer.Typer()


# Web only functions
def clean_up() -> None:
    """Clean up by removing the PID file."""
    Path(PID_FILE).unlink()
    typer.echo("Cleaned up PID file.")


def start_web_server(port: int) -> None:
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
                typer.echo(f"Server running at http://localhost:{port}/")
                break
            time.sleep(0.1)  # Poll every 0.1 seconds

        else:
            typer.echo(f"UVicorn server did not respond within {wait_time} seconds.")
            typer.echo("run 'par-run web status' to check the status.")


def stop_web_server() -> None:
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


def list_uvicorn_processes() -> None:
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


def get_web_server_status() -> None:
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

    def __str__(self) -> str:
        return self.value


class AsyncBackend(enum.Enum):
    """Async backend enumeration."""

    TRIO = "trio"
    ASYNCIO = "asyncio"
    ASYNCIO_NATIVE = "asyncio-native"

    def __str__(self) -> str:
        return self.value


class CLICommandCBOnComp:
    async def on_start(self, cmd: Command) -> None:
        rich.print(f"[blue bold]{cmd.name}: Started[/]")

    async def on_recv(self, _: Command, output: str) -> None:
        rich.print(output)

    async def on_term(self, cmd: Command, exit_code: int) -> None:
        """Callback function for when a command receives output"""
        if cmd.status == CommandStatus.SUCCESS:
            rich.print(f"[green bold]{cmd.name}: Finished[/]")
        elif cmd.status == CommandStatus.FAILURE:
            rich.print(f"[red bold]{cmd.name}: Failed, {exit_code=:}[/]")


class CLICommandCBOnRecv:
    async def on_start(self, cmd: Command) -> None:
        rich.print(f"[blue bold]{cmd.name}: Started[/]")

    async def on_recv(self, cmd: Command, output: str) -> None:
        rich.print(f"{cmd.name}: {output}")

    async def on_term(self, cmd: Command, exit_code: int) -> None:
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


def show_commands(groups: list[CommandGroup]) -> None:
    for grp in groups:
        rich.print(f"[blue bold]Group: {grp.name}[/]")
        rich.print(f"Params: cont_on_fail={grp.cont_on_fail}, serial={grp.serial}, timeout={grp.timeout}")
        for cmd in grp.cmds.values():
            rich.print(f"[green bold]{cmd.name}[/]: {cmd.cmd}")


def filter_groups(
    group_list: list[CommandGroup], filter_groups: Optional[str], filter_cmds: Optional[str]
) -> list[CommandGroup]:
    if filter_groups:
        group_list = [grp for grp in group_list if grp.name in [g.strip() for g in filter_groups.split(",")]]

    if filter_cmds:
        for grp in group_list:
            grp.cmds = OrderedDict(
                {
                    cmd_name: cmd
                    for cmd_name, cmd in grp.cmds.items()
                    if cmd_name in [c.strip() for c in filter_cmds.split(",")]
                },
            )
        group_list = [grp for grp in group_list if grp.cmds]
    return group_list


def add_table_break(tbl: rich.table.Table, break_ch: str = "-", break_style: Optional[str] = None) -> rich.table.Table:
    break_data: list[str] = [break_ch * int(col.width) for col in tbl.columns if col.width is not None]
    tbl.add_row(
        *break_data,
        style=break_style,
    )
    return tbl


def build_results_tbl() -> rich.table.Table:
    res_tbl = rich.table.Table(title="Results", show_header=True, header_style="bold blue", box=rich.box.ROUNDED)
    group_w, name_w, cmd_w, status_w, elap_w = (10, 15, 50, 6, 12)
    res_tbl.add_column("Group", style="bold blue", width=group_w, no_wrap=True)
    res_tbl.add_column("Name", style="bold blue", width=name_w, no_wrap=True)
    res_tbl.add_column("Command", style="bold blue", width=cmd_w, no_wrap=True)
    res_tbl.add_column("Status", style="bold blue", width=status_w, no_wrap=True)
    res_tbl.add_column("Elapsed", style="bold blue", width=elap_w, no_wrap=True)
    return res_tbl


def command_status_to_emoji(cmd: Command) -> tuple[str, str]:
    if cmd.status == CommandStatus.SUCCESS:
        return ("✅", "green")
    elif cmd.status == CommandStatus.FAILURE:
        return ("❌", "red")
    elif cmd.status == CommandStatus.TIMEOUT:
        return ("⏰", "orange1")
    else:
        return ("🚫", "red")


def add_command_row(tbl: rich.table.Table, cmd: Command, group_name: str) -> rich.table.Table:
    elap_str = format_elapsed_time(cmd.elapsed) if cmd.elapsed else "XX:XX:XX.xxx"
    emoji, row_style = command_status_to_emoji(cmd)
    tbl.add_row(group_name, cmd.name, cmd.cmd, emoji, elap_str, style=row_style)
    return tbl


def fmt_group_name(cmd_group: CommandGroup) -> str:
    if cmd_group.status == CommandStatus.SUCCESS:
        return f"[green]{cmd_group.name}[/]"
    elif cmd_group.status == CommandStatus.FAILURE:
        return f"[red]{cmd_group.name}[/]"
    else:
        return f"[yellow]{cmd_group.name}[/]"


style_default = typer.Option(help="Processing strategy, for serial commands this is always --recv", default="comp")
show_default = typer.Option(help="Show available groups and commands", default=False)
pyproj_default = typer.Option(help="The default toml file to use", default=Path("pyproject.toml"))
groups_default = typer.Option(help="Run a specific group of commands, comma spearated", default=None)
cmds_default = typer.Option(help="Run specific commands, comma separated", default=None)
backend_default = typer.Option(help="The backend to use", default="trio")

backend_options: dict[AsyncBackend, Any] = {
    AsyncBackend.TRIO: {"backend": "trio", "backend_options": {}},
    AsyncBackend.ASYNCIO: {"backend": "asyncio", "backend_options": {"use_uvloop": True}},
    AsyncBackend.ASYNCIO_NATIVE: {"backend": "asyncio", "backend_options": {"use_uvloop": False}},
}


@cli_app.command()
def run(  # noqa: PLR0913
    style: Annotated[ProcessingStrategy, typer.Option] = style_default,
    show: Annotated[bool, typer.Option] = show_default,
    file: Annotated[Path, typer.Option] = pyproj_default,
    groups: Annotated[Optional[str], typer.Option] = groups_default,
    cmds: Annotated[Optional[str], typer.Option] = cmds_default,
    backend: Annotated[AsyncBackend, typer.Option] = backend_default,
) -> None:
    """Run commands in parallel"""
    # Overall exit code, need to track all command exit codes to update this
    exit_code = 0
    st_all = time.perf_counter()

    actual_backend = backend_options[backend]["backend"]
    actual_backend_opts = backend_options[backend]["backend_options"]

    master_groups = read_commands_toml(file)
    if show:
        return show_commands(master_groups)

    master_groups = filter_groups(master_groups, groups, cmds)

    if not master_groups:
        rich.print("[blue]No groups or commands found.[/]")
        raise typer.Exit(0)

    for grp in master_groups:
        # Run the async function with Trio's event loop
        if style == ProcessingStrategy.ON_COMP:
            anyio.run(grp.run, style, CLICommandCBOnComp(), backend=actual_backend, backend_options=actual_backend_opts)
        elif style == ProcessingStrategy.ON_RECV:
            anyio.run(grp.run, style, CLICommandCBOnRecv(), backend=actual_backend, backend_options=actual_backend_opts)
        else:
            raise typer.BadParameter("Invalid processing strategy")  # pragma: no cover
        if grp.status != CommandStatus.SUCCESS:
            exit_code = 1
            if not grp.cont_on_fail:
                break
    # Summarise the results
    console = rich.console.Console()
    res_tbl = build_results_tbl()

    for grp_ix, grp in enumerate(master_groups):
        for ix, cmd in enumerate(grp.cmds.values()):
            if grp_ix > 0 and ix == 0:
                add_table_break(res_tbl)
            grp_name = fmt_group_name(grp)
            if ix > 0:
                grp_name = ""
            add_command_row(res_tbl, cmd, grp_name)

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
    ) -> None:
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
            typer.echo(f"Not a valid command '{command}'", err=True)  # pragma: no cover
            raise typer.Abort()  # pragma: no cover

except ImportError:  # pragma: no cover
    pass  # pragma: no cover
