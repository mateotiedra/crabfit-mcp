"""User-local timezone preference, shared by MCP server processes."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import tomllib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastmcp.exceptions import ToolError


def config_path() -> Path:
    root = os.environ.get("XDG_CONFIG_HOME")
    return (Path(root) if root else Path.home() / ".config") / "crabfit-mcp" / "config.toml"


def validate_timezone(timezone: str) -> None:
    try:
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ToolError("timezone must be an IANA display timezone, for example UTC or Europe/Zurich") from None


def load_timezone() -> str | None:
    try:
        with config_path().open("rb") as file:
            data = tomllib.load(file)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise ToolError("Cannot read Crab Fit config.toml; repair it or use set_timezone") from None
    timezone = data.get("timezone")
    if not isinstance(timezone, str):
        raise ToolError("Crab Fit config.toml must contain an IANA timezone; use set_timezone")
    validate_timezone(timezone)
    return timezone


def save_timezone(timezone: str) -> None:
    validate_timezone(timezone)
    path = config_path()
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write("timezone = " + json.dumps(timezone) + "\n")
        temporary.replace(path)
    except OSError:
        raise ToolError("Cannot save Crab Fit timezone in config.toml; check directory permissions") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
