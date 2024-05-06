"""pytest fixtures."""

from typing import Any, Literal

AnyIOBackendT = tuple[Literal["asyncio", "trio"], dict[str, Any]]
