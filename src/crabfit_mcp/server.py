"""Explicit Crab Fit tools; no automatic OpenAPI exposure."""

import base64

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from urllib.parse import quote

from .client import api_client, configured_url, request
from .config import config_path, load_timezone, save_timezone, validate_timezone
from .slots import expand_times, validate_times


def validate_id(event_id: str) -> str:
    if not event_id.strip() or "/" in event_id or "\\" in event_id or not event_id.strip("."):
        raise ToolError("event_id must be a nonblank ID, not a URL or path")
    return quote(event_id, safe="")


def validated_slots(times: list[str], *, allow_empty: bool) -> list[str]:
    try:
        return validate_times(times, allow_empty=allow_empty)
    except ValueError as error:
        raise ToolError(str(error)) from None




def event_result(data: dict) -> dict:
    try:
        if not all(isinstance(data[key], str) for key in ("id", "name", "timezone")):
            raise ValueError
        validate_id(data["id"])
        validate_timezone(data["timezone"])
        if type(data["created_at"]) is not int or not isinstance(data["times"], list):
            raise ValueError
        if not all(isinstance(value, str) for value in data["times"]):
            raise ValueError
        slots = expand_times(data["times"])
    except (KeyError, ValueError, ToolError):
        raise ToolError("Unexpected response from Crab Fit") from None
    return {
        **{key: data[key] for key in ("id", "name", "times", "timezone", "created_at")},
        "url": configured_url("CRABFIT_WEB_URL", "https://crab.fit") + "/" + quote(data["id"], safe=""),
        "available_slots": slots,
    }


def participant_result(data: dict) -> dict:
    try:
        if not isinstance(data["name"], str) or not data["name"].strip():
            raise ValueError
        if type(data["created_at"]) is not int or not isinstance(data["availability"], list):
            raise ValueError
        if not all(isinstance(value, str) for value in data["availability"]):
            raise ValueError
        validate_times(data["availability"], allow_empty=True)
    except (KeyError, ValueError):
        raise ToolError("Unexpected response from Crab Fit") from None
    return {key: data[key] for key in ("name", "availability", "created_at")}


def create_server() -> FastMCP:
    server = FastMCP("Crab Fit")

    @server.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def get_preferences() -> dict:
        """Read the saved IANA timezone before asking the user for one or
        converting local event hours to UTC. A null timezone means not configured."""
        return {"timezone": load_timezone(), "config_path": str(config_path())}

    @server.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    async def set_timezone(timezone: str) -> dict:
        """Save the user's default IANA timezone once, e.g. Europe/Paris.
        Persists across restarts and applies to create_event when timezone is omitted.
        Does not change existing events. Only call when the user chooses a timezone."""
        save_timezone(timezone)
        return {"timezone": timezone, "config_path": str(config_path())}

    @server.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
    async def create_event(times: list[str], timezone: str | None = None, name: str | None = None) -> dict:
        """Create an event. UTC slots use HHmm-DDMMYYYY (0900-20102026) or HHmm-d
        (0900-2, Sunday=0); do not mix formats. Omit timezone to use the saved
        preference; read get_preferences before asking the user for a timezone.
        timezone is an IANA display zone, not a conversion of UTC slots.
        An explicit timezone overrides the preference for this event only.
        Never automatically retry creation."""
        slots = validated_slots(times, allow_empty=False)
        if timezone is None:
            timezone = load_timezone()
            if timezone is None:
                raise ToolError("No default timezone saved; ask once and call set_timezone, or supply timezone for this event")
        validate_timezone(timezone)
        configured_url("CRABFIT_WEB_URL", "https://crab.fit")
        payload = {"times": slots, "timezone": timezone}
        if name is not None:
            payload["name"] = name
        async with api_client() as client:
            return event_result(await request(client, "POST", "event", status=201, json=payload))

    @server.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
    async def get_event(event_id: str) -> dict:
        """Read an event by ID (not URL), including selectable available_slots.
        Slots are UTC HHmm-DDMMYYYY (0915-20102026) or HHmm-d (0915-2;
        Sunday=0). This does not log in or create participants."""
        path_id = validate_id(event_id)
        configured_url("CRABFIT_WEB_URL", "https://crab.fit")
        async with api_client() as client:
            return event_result(await request(client, "GET", f"event/{path_id}"))

    @server.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
    async def set_availability(event_id: str, person_name: str, availability: list[str], password: str | None = None) -> dict:
        """Log in or create a participant and fully REPLACE their availability.
        [] clears all previous selections. To add slots, supply the full desired
        selection; there is no merge. Use available_slots from get_event: UTC
        HHmm-DDMMYYYY (0915-20102026) or HHmm-d (0915-2; Sunday=0).
        Names are case-insensitive upstream. Optional password is a participant
        password, not an API key. Never automatically retry a failed mutation."""
        path_id = validate_id(event_id)
        if not person_name.strip() or "/" in person_name or "\\" in person_name:
            raise ToolError("person_name must be nonblank and contain no slash or backslash")
        slots = validated_slots(availability, allow_empty=True)
        configured_url("CRABFIT_WEB_URL", "https://crab.fit")
        async with api_client() as client:
            event = event_result(await request(client, "GET", f"event/{path_id}"))
            allowed = set(event["available_slots"])
            if any(slot not in allowed for slot in slots):
                raise ToolError("Availability must contain only available_slots from this event")
            headers = {}
            if password:
                headers["Authorization"] = "Bearer " + base64.b64encode(password.encode("utf-8")).decode("ascii")
            encoded_name = quote(person_name, safe="")
            if not person_name.strip("."):
                encoded_name = encoded_name.replace(".", "%2E")
            path = f"event/{path_id}/people/{encoded_name}"
            try:
                participant_result(await request(client, "GET", path, headers=headers))
            except ToolError as error:
                raise ToolError(f"{error}; availability was not confirmed and the participant may have been created") from None
            try:
                person = participant_result(await request(client, "PATCH", path, headers=headers, json={"availability": slots}))
            except ToolError as error:
                raise ToolError(f"{error}; availability was not confirmed and the participant may have been created") from None
        return {**person, "event_id": event_id, "url": event["url"]}

    return server


def main() -> None:
    create_server().run(transport="stdio")
