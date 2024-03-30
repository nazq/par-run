from collections import OrderedDict

import pytest

from par_run.executor import Command, CommandGroup


@pytest.fixture
def command_data():
    return {
        "group.test": [
            ("command1", "do something"),
            ("command2", "do something else"),
        ]
    }


@pytest.fixture
def expected_command_groups():
    return [
        CommandGroup(
            name="test",
            cmds=OrderedDict(
                [
                    ("command1", Command(name="command1", cmd="do something")),
                    ("command2", Command(name="command2", cmd="do something else")),
                ]
            ),
        )
    ]
