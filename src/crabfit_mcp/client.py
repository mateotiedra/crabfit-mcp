"""Per-invocation HTTP resources and safe API failures."""

import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from fastmcp.exceptions import ToolError


def configured_url(variable: str, default: str) -> str:
    value = os.environ.get(variable, default).rstrip("/")
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in {"http", "https"} and parsed.hostname and parsed.port != 0
    except ValueError:
        valid = False
    if not valid or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ToolError(f"{variable} must be an absolute HTTP(S) URL without credentials, query or fragment")
    return value


@asynccontextmanager
async def api_client():
    base = configured_url("CRABFIT_API_URL", "https://api.crab.fit")
    async with httpx.AsyncClient(base_url=base + "/", timeout=20, follow_redirects=False) as client:
        yield client


async def request(client: httpx.AsyncClient, method: str, path: str, *, status: int = 200, **kwargs) -> dict:
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.RequestError:
        raise ToolError("Request to Crab Fit failed; mutations may already have taken effect") from None
    if response.status_code != status:
        messages = {
            401: "Incorrect participant password",
            404: "Event or participant not found",
            429: "Crab Fit rate limit reached; retry later",
        }
        raise ToolError(messages.get(response.status_code, f"Crab Fit HTTP error {response.status_code}"))
    try:
        data = response.json()
    except ValueError:
        raise ToolError("Unexpected response from Crab Fit") from None
    if not isinstance(data, dict):
        raise ToolError("Unexpected response from Crab Fit")
    return data
