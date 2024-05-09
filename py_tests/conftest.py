"""pytest fixtures."""

from collections import OrderedDict
from statistics import mean
from typing import Any, Literal, Union

import pytest

from par_run.executor import Command, CommandGroup

AnyIOBackendT = tuple[Literal["asyncio", "trio"], dict[str, Any]]


def cmd_group_ids(vals: tuple[int, list[int], list[int], list[bool], list[bool]]) -> str:
    num_groups, num_cmds, num_output_lines, serial, success = _norm_generate_command_groups(*vals)

    serial_str = str(any(serial))
    success_str = str(all(success))
    num_output_lines_str = str(mean(num_output_lines))
    return (
        f"{num_groups}_groups_"
        f"{len(num_cmds)}_cmds_"
        f"{len(num_output_lines)}_outputs_"
        f"{num_output_lines_str}_serial_"
        f"{serial_str}_success_"
        f"{success_str}"
    )


@pytest.fixture(
    params=[
        (1, 2, 1, False, True),
        (2, 2, 1, False, True),
        (2, 2, 2, False, True),
        (2, 3, 3, False, True),
    ],
    ids=cmd_group_ids,
)
def mock_command_groups_par_success(request: pytest.FixtureRequest) -> list[CommandGroup]:
    return generate_command_groups(*request.param)


@pytest.fixture(
    params=[
        (1, 2, 1, True, True),
        (2, 2, 1, True, True),
        (2, 2, 2, True, True),
        (2, 3, 3, True, True),
    ],
    ids=cmd_group_ids,
)
def mock_command_groups_serial_success(request: pytest.FixtureRequest) -> list[CommandGroup]:
    return generate_command_groups(*request.param)


@pytest.fixture(
    params=[
        (1, 3, 1, True, [True, False, True]),
        (2, 2, 1, True, [True, False, True, False]),
        (2, 2, 2, True, [True, False, True, False]),
        (2, 3, 3, True, [True, False, True, False, True, False]),
    ],
    ids=cmd_group_ids,
)
def mock_command_groups_par_part_fail(request: pytest.FixtureRequest) -> list[CommandGroup]:
    return generate_command_groups(*request.param)


def _norm_generate_command_groups(  # noqa: PLR0912
    num_groups: int,
    num_cmds: Union[int, list[int]],
    num_output_lines: Union[int, list[int]],
    serial: Union[bool, list[bool]],
    success: Union[bool, list[bool]],
) -> tuple[int, list[int], list[int], list[bool], list[bool]]:
    """

    Args:
        num_groups (int): Number of groups to generate
        num_cmds (Union[int, list[int]]): Number of commands in each group, or a list of the number of commands
            in each group. Must be the same length as num_groups
        num_output_lines (Union[int, list[int]]): Number of output lines for each command,
          or a list of the number of output lines for each command. Must be the same length as num_cmds*num_groups
        serial (Union[bool, list[bool]]): Whether each group should run serially or in parallel, each group must be
            a bool or a list of bools the same length as num_cmds*num_groups
        success (Union[bool, list[bool]]): Whether each command should succeed or fail, each command must be a bool
            or a list of bools the same length as num_cmds*num_groups

    Returns:
        tuple[int, list[int], list[int], list[bool], list[bool]]: _description_
    """
    if num_groups < 1:
        raise ValueError("num_groups must be greater than 0")

    if isinstance(num_cmds, list):
        if len(num_cmds) != num_groups:
            raise ValueError("num_cmds must be a list the same length as num_groups, or an int")
        else:
            pass
    else:
        num_cmds = [num_cmds] * num_groups
    tot_cmds = sum(num_cmds)
    if isinstance(num_output_lines, list):
        if len(num_output_lines) != tot_cmds:
            raise ValueError("num_output_lines must be an int or the same length as num_cmds*num_groups")
        else:
            pass
    else:
        num_output_lines = [num_output_lines] * tot_cmds
    if isinstance(serial, list):
        if len(serial) != tot_cmds:
            raise ValueError("serial must be a list the same length as num_groups, or an bool")
        else:
            pass
    else:
        serial = [serial] * tot_cmds

    if isinstance(success, list):
        if len(success) != tot_cmds:
            raise ValueError("success must be a list the same length as num_cmds, or an bool")
        else:
            pass
    else:
        success = [success] * tot_cmds
    return num_groups, num_cmds, num_output_lines, serial, success


def generate_command_groups(
    num_groups: int,
    num_cmds: Union[int, list[int]],
    num_output_lines: Union[int, list[int]],
    serial: Union[bool, list[bool]],
    success: Union[bool, list[bool]],
) -> CommandGroup:
    num_groups, num_cmds, num_output_lines, serial, success = _norm_generate_command_groups(
        num_groups,
        num_cmds,
        num_output_lines,
        serial,
        success,
    )

    echo = "Hello, World!"
    cmd_groups: list[CommandGroup] = []
    for group_ix in range(num_groups):
        cmds = OrderedDict()
        for cmd_ix in range(num_cmds[group_ix]):
            cmd_name = f"test_{cmd_ix}"
            multi_part_cmds = [f"echo '{echo_ix}:{echo}'" for echo_ix in range(num_output_lines[group_ix])]
            multi_part_cmds.append(f"exit {0 if success[cmd_ix] else 1}")
            cmd_str = " && ".join(multi_part_cmds)
            cmds[cmd_name] = Command(name=cmd_name, cmd=cmd_str)
        cmd_groups.append(CommandGroup(name=f"test_group{group_ix}", cmds=cmds, serial=serial[group_ix]))
    return cmd_groups


@pytest.fixture(
    params=[
        pytest.param(("asyncio", {"use_uvloop": True}), id="asyncio+uvloop"),
        pytest.param(("asyncio", {"use_uvloop": False}), id="asyncio"),
    ],
)
def anyio_backend(request: pytest.FixtureRequest) -> AnyIOBackendT:
    return request.param  # type: ignore


@pytest.fixture(
    params=[
        pytest.param(("asyncio", {"use_uvloop": True}), id="asyncio+uvloop"),
        pytest.param(("asyncio", {"use_uvloop": False}), id="asyncio"),
        pytest.param(("trio", {}), id="trio"),
    ],
)
def anyio_backend_asyncio(request: pytest.FixtureRequest) -> tuple[str, dict[str, Any]]:
    return request.param
