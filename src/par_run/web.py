"""Web UI Module"""

from pathlib import Path
import rich
from fastapi import Body, FastAPI, Request, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .executor import Command, CommandGroup, ProcessingStrategy, read_commands_ini, write_commands_ini

BASE_PATH = Path(__file__).resolve().parent

ws_app = FastAPI()
ws_app.mount("/static", StaticFiles(directory=str(BASE_PATH / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_PATH / "templates"))


@ws_app.get("/")
async def ws_main(request: Request):
    """Get the main page."""
    print("Main page")
    return templates.TemplateResponse("index.html", {"request": request})


@ws_app.get("/get-commands-config")
async def get_commands_config():
    """Get the commands configuration."""
    return read_commands_ini("commands.ini")


@ws_app.post("/update-commands-config")
async def update_commands_config(updated_config: list[CommandGroup] = Body(...)):
    """Update the commands configuration."""
    write_commands_ini("commands.ini", updated_config)
    return {"message": "Configuration updated successfully"}


class WebCommandCB:
    """Websocket command callbacks."""

    def __init__(self, ws: WebSocket):
        self.ws = ws

    async def on_start(self, cmd: Command):
        rich.print(f"[blue bold]Started command {cmd.name}[/]")

    async def on_recv(self, cmd: Command, output: str):
        await self.ws.send_json({"commandName": cmd.name, "output": output})

    async def on_term(self, cmd: Command, exit_code: int):
        await self.ws.send_json({"commandName": cmd.name, "output": {"ret_code": exit_code}})


@ws_app.websocket_route("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Websocket endpoint to run commands."""
    rich.print("Websocket connection")
    master_groups = read_commands_ini("commands.ini")
    print(master_groups)
    await websocket.accept()
    cb = WebCommandCB(websocket)
    print("Running commands")
    exit_code = 0
    for grp in master_groups:
        exit_code = exit_code or await grp.run_async(ProcessingStrategy.ON_RECV, cb)
