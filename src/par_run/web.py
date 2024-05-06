"""Web UI Module"""

from pathlib import Path

import rich
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .executor import Command, CommandGroup, CommandStatus, ProcessingStrategy, read_commands_toml

BASE_PATH = Path(__file__).resolve().parent

ws_app = FastAPI()
ws_app.mount("/static", StaticFiles(directory=str(BASE_PATH / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_PATH / "templates"))


@ws_app.get("/")
async def ws_main(request: Request) -> HTMLResponse:
    """Get the main page."""
    return templates.TemplateResponse("index.html", {"request": request})


@ws_app.get("/get-commands-config")
async def get_commands_config() -> list[CommandGroup]:
    """Get the commands configuration."""
    return read_commands_toml("commands.toml")


class WebCommandCB:
    """Websocket command callbacks."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws

    async def on_start(self, cmd: Command) -> None:
        rich.print(f"[blue bold]Started command {cmd.name}[/]")

    async def on_recv(self, cmd: Command, output: str) -> None:
        await self.ws.send_json({"commandName": cmd.name, "output": output})

    async def on_term(self, cmd: Command, exit_code: int) -> None:
        if cmd.status == CommandStatus.SUCCESS:
            rich.print(f"[green bold]Command {cmd.name} finished[/]")
        elif cmd.status == CommandStatus.FAILURE:
            rich.print(f"[red bold]Command {cmd.name} failed, {exit_code=:}[/]")
        await self.ws.send_json({"commandName": cmd.name, "output": {"ret_code": exit_code}})


@ws_app.websocket_route("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Websocket endpoint to run commands."""
    rich.print("Websocket connection")
    master_groups = read_commands_toml("commands.toml")
    await websocket.accept()
    rich.print("Websocket accepted")
    cb = WebCommandCB(websocket)
    rich.print("Websocket command cb created")
    for grp in master_groups:
        await grp.run(ProcessingStrategy.ON_RECV, cb)
        if grp.status != CommandStatus.SUCCESS and not grp.cont_on_fail:
            break
