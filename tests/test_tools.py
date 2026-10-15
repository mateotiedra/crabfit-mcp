import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from fastmcp import Client

from crabfit_mcp import server

EVENT = {"id": "test-event", "name": "Generated name", "times": ["0900-20102026"], "timezone": "UTC", "created_at": 1}
SLOTS = ["0900-20102026", "0915-20102026", "0930-20102026", "0945-20102026"]


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


@pytest.fixture
def install_transport(monkeypatch):
    def install(handler):
        @asynccontextmanager
        async def client():
            async with httpx.AsyncClient(base_url="https://mock.test/", transport=httpx.MockTransport(handler), timeout=20, follow_redirects=False) as http:
                yield http
        monkeypatch.setattr(server, "api_client", client)
    return install


def call(tool, **arguments):
    async def run():
        async with Client(server.create_server()) as client:
            return await client.call_tool(tool, arguments)
    return asyncio.run(run()).data


def test_event_creation_and_discovery(install_transport):
    created = []
    def handle(request):
        if request.method == "POST":
            body = json.loads(request.content)
            created.append(body)
            return httpx.Response(201, json=EVENT)
        assert request.url.path == "/event/test-event"
        return httpx.Response(200, json=EVENT)
    install_transport(handle)
    event = call("create_event", times=EVENT["times"] * 2, timezone="UTC")
    assert event["name"] == "Generated name"
    assert event["available_slots"] == SLOTS
    assert event["url"] == "https://crab.fit/test-event"
    assert "name" not in created[0]
    assert created[0]["times"] == EVENT["times"]
    assert call("get_event", event_id="test-event") == event


def test_saved_timezone_persists_and_event_override_is_temporary(install_transport):
    def handle(request):
        body = json.loads(request.content)
        return httpx.Response(201, json={**EVENT, "timezone": body["timezone"]})
    install_transport(handle)
    assert call("get_preferences")["timezone"] is None
    call("set_timezone", timezone="Europe/Paris")
    # Each call constructs a new server: the default must survive in the file.
    assert call("get_preferences")["timezone"] == "Europe/Paris"
    assert call("create_event", times=EVENT["times"])["timezone"] == "Europe/Paris"
    assert call("create_event", times=EVENT["times"], timezone="UTC")["timezone"] == "UTC"
    assert call("create_event", times=EVENT["times"])["timezone"] == "Europe/Paris"
    call("set_timezone", timezone="America/New_York")
    assert call("create_event", times=EVENT["times"])["timezone"] == "America/New_York"


def test_missing_default_fails_before_mutation(install_transport):
    requests = []
    install_transport(lambda request: requests.append(request))
    with pytest.raises(Exception, match="set_timezone"):
        call("create_event", times=EVENT["times"])
    assert requests == []


def test_invalid_timezone_does_not_replace_saved_preference():
    call("set_timezone", timezone="Europe/Paris")
    with pytest.raises(Exception, match="IANA"):
        call("set_timezone", timezone="Not/AZone")
    assert call("get_preferences")["timezone"] == "Europe/Paris"


@pytest.mark.parametrize("content", ['timezone = [', 'timezone = 42', 'timezone = "Not/AZone"'])
def test_broken_config_blocks_default_but_can_be_repaired(install_transport, tmp_path, content):
    path = tmp_path / "crabfit-mcp" / "config.toml"
    path.parent.mkdir()
    path.write_text(content)
    requests = []
    install_transport(lambda request: requests.append(request))
    with pytest.raises(Exception):
        call("create_event", times=EVENT["times"])
    assert requests == []
    call("set_timezone", timezone="Europe/Paris")
    assert call("get_preferences")["timezone"] == "Europe/Paris"


@pytest.mark.parametrize("tool,arguments", [
    ("create_event", {"times": [], "timezone": "UTC"}),
    ("create_event", {"times": EVENT["times"], "timezone": "Not/AZone"}),
    ("get_event", {"event_id": "../test"}),
    ("get_event", {"event_id": "..."}),
    ("get_event", {"event_id": " "}),
])
def test_event_validation_before_http(install_transport, tool, arguments):
    calls = []
    install_transport(lambda request: calls.append(request))
    with pytest.raises(Exception):
        call(tool, **arguments)
    assert calls == []


@pytest.mark.parametrize("response,message", [
    (httpx.Response(429, text="private upstream body"), "rate limit"),
    (httpx.Response(404), "not found"),
    (httpx.Response(500, text="private upstream body"), "HTTP error 500"),
    (httpx.Response(200, text="invalid json"), "Unexpected response"),
    (httpx.Response(200, json={"id": "incomplete"}), "Unexpected response"),
    (httpx.Response(200, json={**EVENT, "times": ["bad"]}), "Unexpected response"),
])
def test_safe_event_failures(install_transport, response, message):
    install_transport(lambda request: response)
    with pytest.raises(Exception, match=message) as error:
        call("get_event", event_id="test-event")
    assert "private upstream body" not in str(error.value)


def test_ambiguous_creation_timeout_is_not_retried(install_transport):
    calls = []
    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("sensitive transport detail", request=request)
    install_transport(handle)
    with pytest.raises(Exception, match="mutations may already have taken effect") as error:
        call("create_event", times=EVENT["times"], timezone="UTC")
    assert len(calls) == 1
    assert "sensitive transport detail" not in str(error.value)


@pytest.mark.parametrize("availability", [["1000-20102026"], ["bad"], ["0900-2"]])
def test_invalid_selection_never_creates_participant(install_transport, availability):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=EVENT)
    install_transport(handle)
    with pytest.raises(Exception):
        call("set_availability", event_id="test-event", person_name="New person", availability=availability)
    assert all("/people/" not in request.url.path for request in requests)


def test_replacement_clearing_and_password_isolation(install_transport):
    import base64
    people = {}
    def handle(request):
        if request.url.path == "/event/test-event":
            assert "authorization" not in request.headers
            return httpx.Response(200, json=EVENT)
        name = request.url.path.rsplit("/", 1)[1]
        header = request.headers.get("authorization")
        if name not in people:
            people[name] = {"password": header, "availability": []}
        person = people[name]
        if header != person["password"]:
            return httpx.Response(401, text="do not disclose secret")
        if request.method == "PATCH":
            person["availability"] = json.loads(request.content)["availability"]
        return httpx.Response(200, json={"name": name, "availability": person["availability"], "created_at": 2})
    install_transport(handle)
    args = {"event_id": "test-event", "person_name": "Alice", "password": "sëcret"}
    call("set_availability", **args, availability=SLOTS[:2])
    result = call("set_availability", **args, availability=[SLOTS[2]])
    assert result["availability"] == [SLOTS[2]]
    assert people["Alice"]["availability"] == [SLOTS[2]]
    assert result["event_id"] == "test-event"
    assert set(result) == {"name", "availability", "created_at", "event_id", "url"}
    with pytest.raises(Exception, match="Incorrect participant password"):
        call("set_availability", **{**args, "password": "wrong"}, availability=SLOTS)
    assert people["Alice"]["availability"] == [SLOTS[2]]
    call("set_availability", event_id="test-event", person_name="Bob", availability=[SLOTS[0]])
    call("set_availability", event_id="test-event", person_name="Carol", password="", availability=[SLOTS[0]])
    assert people["Bob"]["password"] is None
    assert people["Carol"]["password"] is None
    assert people["Alice"]["password"] == "Bearer " + base64.b64encode("sëcret".encode()).decode()
    result = call("set_availability", **args, availability=[])
    assert result["availability"] == people["Alice"]["availability"] == []


def test_failed_login_stops_patch(install_transport):
    methods = []
    def handle(request):
        methods.append(request.method)
        return httpx.Response(200, json=EVENT) if request.url.path == "/event/test-event" else httpx.Response(401)
    install_transport(handle)
    with pytest.raises(Exception, match="Incorrect participant password"):
        call("set_availability", event_id="test-event", person_name="Alice", password="secret", availability=[])
    assert methods == ["GET", "GET"]


@pytest.mark.parametrize("failure,message", [
    ("timeout", "mutations may already have taken effect"),
    ("rate_limit", "rate limit"),
    ("malformed", "Unexpected response"),
])
def test_partial_participant_failure_is_explicit_without_retry(install_transport, failure, message):
    methods = []
    def handle(request):
        methods.append(request.method)
        if request.url.path == "/event/test-event":
            return httpx.Response(200, json=EVENT)
        if request.method == "GET":
            return httpx.Response(200, json={"name": "Alice", "availability": [], "created_at": 2})
        if failure == "timeout":
            raise httpx.ReadTimeout("Authorization: secret", request=request)
        if failure == "rate_limit":
            return httpx.Response(429, text="secret")
        return httpx.Response(200, json={"name": "Alice"})
    install_transport(handle)
    with pytest.raises(Exception, match=message) as error:
        call("set_availability", event_id="test-event", person_name="Alice", password="secret", availability=[SLOTS[0]])
    assert "availability was not confirmed" in str(error.value)
    assert "participant may have been created" in str(error.value)
    assert "secret" not in str(error.value)
    assert methods == ["GET", "GET", "PATCH"]


@pytest.mark.parametrize("name", [" ", "a/b", "a\\b"])
def test_invalid_name_has_no_http_effect(install_transport, name):
    requests = []
    install_transport(lambda request: requests.append(request))
    with pytest.raises(Exception, match="person_name"):
        call("set_availability", event_id="test-event", person_name=name, availability=[])
    assert requests == []


@pytest.mark.parametrize("failure", ["timeout", "malformed"])
def test_uncertain_login_stops_patch_and_reports_possible_creation(install_transport, failure):
    methods = []
    def handle(request):
        methods.append(request.method)
        if request.url.path == "/event/test-event":
            return httpx.Response(200, json=EVENT)
        if failure == "timeout":
            raise httpx.ConnectError("password-secret", request=request)
        return httpx.Response(200, text="bad json")
    install_transport(handle)
    with pytest.raises(Exception, match="participant may have been created") as error:
        call("set_availability", event_id="test-event", person_name="Alice", password="password-secret", availability=[])
    assert "password-secret" not in str(error.value)
    assert methods == ["GET", "GET"]


@pytest.mark.parametrize("name", ["..", " A? #é ", "100%"])
def test_participant_identity_is_preserved_in_encoded_route(install_transport, name):
    from urllib.parse import unquote
    selected = {}
    def handle(request):
        if request.url.path == "/event/test-event":
            return httpx.Response(200, json=EVENT)
        raw_name = request.url.raw_path.split(b"/")[-1].decode()
        identity = unquote(raw_name)
        if request.method == "PATCH":
            selected[identity] = json.loads(request.content)["availability"]
        return httpx.Response(200, json={"name": identity, "availability": selected.get(identity, []), "created_at": 2})
    install_transport(handle)
    result = call("set_availability", event_id="test-event", person_name=name, availability=[SLOTS[0]])
    assert result["name"] == name
    assert selected == {name: [SLOTS[0]]}


@pytest.mark.parametrize("value", ["relative/path", "file:///tmp/api", "https://user:secret@example.com", "https://example.com?key=secret", "https://example.com:invalid"])
def test_invalid_configuration_is_safe_and_precedes_mutation(monkeypatch, install_transport, value):
    monkeypatch.setenv("CRABFIT_WEB_URL", value)
    requests = []
    install_transport(lambda request: requests.append(request))
    with pytest.raises(Exception, match="absolute HTTP") as error:
        call("create_event", times=EVENT["times"], timezone="UTC")
    assert "secret" not in str(error.value)
    assert requests == []
