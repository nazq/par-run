"""Web UI Module"""

import asyncio
import multiprocessing as mp
import queue

from fastapi import Body, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .executor import (CommandGroup, generic_pool, read_commands_ini,
                       run_command, write_commands_ini)

ws_app = FastAPI()
ws_app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@ws_app.get("/get-commands-config")
async def get_commands_config():
    """Get the commands configuration."""
    return read_commands_ini("commands.ini")


@ws_app.post("/update-commands-config")
async def update_commands_config(updated_config: list[CommandGroup] = Body(...)):
    """Update the commands configuration."""
    write_commands_ini("commands.ini", updated_config)
    return {"message": "Configuration updated successfully"}


@ws_app.websocket_route("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Websocket endpoint to run commands."""
    loop = asyncio.get_event_loop()

    # To use Queue's across processes, you need to use the mp.Manager()
    q = mp.Manager().Queue()

    groups = read_commands_ini("commands.ini")
    await websocket.accept()

    for commands in groups:
        print(f"Running group: {commands.name}")
        futs = [
            loop.run_in_executor(generic_pool, run_command, cmd.name, cmd.cmd, q)
            for _, cmd in commands.cmds.items()
        ]

        for (_, cmd), fut in zip(commands.cmds.items(), futs):
            cmd.fut = fut

        while True:

            # None of the coroutines called in this block (e.g. send_json())
            # will yield back control. asyncio.sleep() does, and so it will allow
            # the event loop to switch context and serve multiple requests
            # concurrently.
            await asyncio.sleep(0)

            try:
                # see if our long running task has some intermediate result.
                # Will result None if there isn't any.
                # print("Checking for intermediate result")
                q_result = q.get(block=True, timeout=30)
            except queue.Empty:
                # if q.get() throws Empty exception, then nothing was
                q_result = None

            # If there is an intermediate result, let's send it to the client.
            if q_result:
                try:
                    if isinstance(q_result[1], int):
                        ret_code = q_result[1]
                        commands.cmds[q_result[0]].set_ret_code(ret_code)
                        await websocket.send_json(
                            {
                                "commandName": q_result[0],
                                "output": {"ret_code": ret_code},
                            }
                        )
                    else:
                        await websocket.send_json(
                            {"commandName": q_result[0], "output": q_result[1]}
                        )
                    # check status of all commands if non are NOT_STARTED, break out of the loop
                    if all(
                        commands.cmds[cmd].status.completed() for cmd in commands.cmds
                    ):
                        print(f"All commands have been run in {commands.name}")
                        break

                except WebSocketDisconnect as e:
                    # This happens if client has moved on, we should stop the long
                    #  running task
                    print(f"Client disconnected: {e}")
                    _ = [result.cancel() for result in futs]
                    # break out of the while loop.
                    break

    try:
        await websocket.close()
    except WebSocketDisconnect:
        pass


@ws_app.get("/")
async def ws_main(request: Request):
    """Get the main page."""
    return templates.TemplateResponse("index.html", {"request": request})
