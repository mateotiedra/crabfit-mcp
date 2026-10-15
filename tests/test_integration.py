"""Opt-in, real local backend smoke; never writes to the production API."""

import asyncio
import base64
import os
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

pytestmark = pytest.mark.skipif(os.environ.get("CRABFIT_INTEGRATION") != "1", reason="requires explicitly launched local Crab Fit backend")


def test_stdio_real_backend():
    api = os.environ.get("CRABFIT_API_URL", "").rstrip("/")
    assert urlsplit(api).hostname in {"localhost", "127.0.0.1", "::1"}, "smoke writes must target a local backend"
    web = os.environ.get("CRABFIT_WEB_URL", "http://127.0.0.1:1234").rstrip("/")
    root = Path(__file__).resolve().parents[1]
    slots = ["0900-20102026", "0915-20102026", "0930-20102026", "0945-20102026"]
    auth = {"Authorization": "Bearer " + base64.b64encode(b"smoke-secret").decode()}

    async def run():
        transport = StdioTransport(command="uv", args=["run", "crabfit-mcp"], cwd=str(root), env={**os.environ, "CRABFIT_WEB_URL": web})
        async with Client(transport) as mcp, httpx.AsyncClient(base_url=api + "/", timeout=20) as backend:
            async def tool(tool_name, **args):
                return (await mcp.call_tool(tool_name, args)).data

            event = await tool("create_event", name="MCP smoke", times=[slots[0]], timezone="UTC")
            assert event["id"] and event["name"] == "MCP smoke"
            assert event["url"] == web + "/" + quote(event["id"], safe="")
            assert event["available_slots"] == slots
            discovered = await tool("get_event", event_id=event["id"])
            assert discovered == event
            args = {"event_id": event["id"], "person_name": "MCP Tester", "password": "smoke-secret"}
            path = f"event/{quote(event['id'], safe='')}/people/MCP%20Tester"

            async def persisted():
                response = await backend.get(path, headers=auth)
                response.raise_for_status()
                return response.json()["availability"]

            result = await tool("set_availability", **args, availability=slots[:2])
            assert result["availability"] == slots[:2]
            assert await persisted() == slots[:2]
            result = await tool("set_availability", **args, availability=[slots[2]])
            assert result["availability"] == [slots[2]]
            assert await persisted() == [slots[2]]
            with pytest.raises(Exception, match="Incorrect participant password"):
                await tool("set_availability", **{**args, "password": "wrong"}, availability=slots)
            assert await persisted() == [slots[2]]
            result = await tool("set_availability", **args, availability=[])
            assert result["availability"] == []
            assert await persisted() == []
            with pytest.raises(Exception, match="only available_slots"):
                await tool("set_availability", event_id=event["id"], person_name="Invalid Selection", availability=["1000-20102026"])
            # The public people listing hides empty participants; no-create is
            # established by the isolated transport test, not this listing.

    asyncio.run(run())
