# Crab Fit MCP

Create scheduling polls and manage availability on [Crab Fit](https://crab.fit/) from your AI assistant.

A local [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server built with Python and [FastMCP](https://gofastmcp.com/). It calls the Crab Fit HTTP API directly: no browser automation, hosted MCP service, or API key required.

- **Create events** and get a shareable Crab Fit link.
- **Read events** and discover selectable time slots.
- **Submit or replace availability**, with optional participant passwords.
- **Save your timezone once** and reuse it across conversations and server restarts.

[Quick start](#quick-start) · [Usage](#usage) · [Tools](#tools) · [Configuration](#configuration) · [Troubleshooting](#troubleshooting) · [Development](#development)

## Quick start

### 1. Install the prerequisites

- **Python 3.11 or newer.**
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** to install dependencies and run the server.
- **Git** to clone this repository.
- **An MCP client with local stdio support**, such as Claude Desktop, Cursor, or an MCP-enabled coding assistant. Configuration locations vary by client.

### 2. Clone and install

```sh
git clone https://github.com/mateotiedra/crabfit-mcp.git
cd crabfit-mcp
uv sync --locked
```

Keep the checkout: your MCP client will launch the server from this directory.

### 3. Connect your assistant

Add the following server entry to your client's MCP configuration. If it already has an `mcpServers` object, merge the `crabfit` entry into it.

```json
{
  "mcpServers": {
    "crabfit": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/crabfit-mcp",
        "run",
        "--locked",
        "crabfit-mcp"
      ]
    }
  }
}
```

Replace `/absolute/path/to/crabfit-mcp` with your actual checkout path. On Windows, use a path such as `C:/Users/you/crabfit-mcp`. If the client cannot find `uv`, replace `"uv"` with its absolute executable path.

Restart or reconnect your client's MCP integration. You should see the five tools listed [below](#tools).

> Connecting or listing tools does not create an event. By default, event creation and availability submissions affect the **live Crab Fit service**.

<details>
<summary>Repository-local configuration for OMP</summary>

The included `.mcp.json` runs `uv run --locked crabfit-mcp` from the current working directory. With `uv` on your PATH, start OMP at the repository root:

```sh
omp --cwd /absolute/path/to/crabfit-mcp
```

For clients that launch servers from another directory, use the absolute-path configuration above instead.

</details>

## Usage

### Save your timezone once

Ask your assistant:

> Save Europe/Paris as my default Crab Fit timezone.

It should call `set_timezone` with `{"timezone": "Europe/Paris"}`. The preference is saved locally and read on each invocation. No server restart is required to change it.

Assistants should call `get_preferences` before asking for a timezone or converting local hours to UTC. If none is saved, ask once and save the answer. An explicit timezone on an event overrides the default **for that event only**.

### Create and share an event

> Create a Crab Fit event called “Team planning” for next Monday through Friday, from 9 am to 5 pm in my saved timezone. Give me the link.

The assistant determines the dates, converts local hours to UTC, and calls `create_event`. The result includes a shareable event URL and its selectable slots.

### Read an event and submit availability

> Show me the available slots for event `my-event-id`.

> For that event, submit my availability as Alice for Monday from 10 am to noon in my saved timezone.

**Availability submissions replace the participant's entire selection.** To add times, the assistant must send both the existing times to keep and the new ones. Sending an empty list clears the selection.

## Tools

| Tool | Arguments | Result / behavior |
| --- | --- | --- |
| `get_preferences` | None | Saved `timezone` (`null` if unset) and local `config_path`. |
| `set_timezone` | `timezone` | Validate and persist an IANA timezone such as `Europe/Paris` or `America/New_York`. |
| `create_event` | `times`, optional `timezone`, optional `name` | Create an event; return `id`, `name`, `times`, `timezone`, `created_at`, `url`, and `available_slots`. Uses the saved timezone when omitted or `null`. |
| `get_event` | `event_id` | Read an event with the same result shape. Use the ID, not the full URL. Does not create participants. |
| `set_availability` | `event_id`, `person_name`, `availability`, optional `password` | Log in or create the participant, then replace their selection. Return `name`, `availability`, `created_at`, `event_id`, and `url`. |

Omitted or empty event names use Crab Fit's generated naming. Participant names are case-insensitive upstream; nonblank names are otherwise preserved. IDs and participant names cannot contain slash or backslash.

### Time slots: important for tool callers

Natural-language examples above are prompts for an assistant. The tools themselves accept **UTC slot IDs**, not local times or ISO timestamps:

| Format | Example | Meaning |
| --- | --- | --- |
| Dated | `0900-20102026` | October 20, 2026 at 09:00 UTC |
| Weekday | `0900-2` | Tuesday at 09:00 UTC; Sunday is `0` |

- Do not mix dated and weekday formats in one list. Dates and clock values are validated; duplicate slots are removed in first-occurrence order.
- `timezone` controls **display only**. It does not convert `times`. Convert local hours using the offset for each event date, including daylight-saving changes.
- Each `create_event` entry selects a complete hour, expanded into four quarter-hour slots. For example, `0900-20102026` yields `0900`, `0915`, `0930`, and `0945` on that date. To offer 09:00–12:00 UTC, supply the hours `0900`, `1000`, and `1100`, not `1200`.
- Minutes in event entries are replaced, not added: `0959-20102026` expands to the same four slots as `0900-20102026`.
- For `set_availability`, select exact IDs from the event's returned `available_slots`. An empty `availability` list clears all previous selections.

Example `create_event` arguments, using an explicit display timezone:

```json
{
  "name": "Team meeting",
  "times": ["0900-20102026", "1000-20102026"],
  "timezone": "UTC"
}
```

Example `set_availability` arguments after reading the event:

```json
{
  "event_id": "returned-event-id",
  "person_name": "Alice",
  "availability": ["0900-20102026", "0915-20102026"]
}
```

## Configuration

### Timezone preference

The server stores one user-local preference file:

- `$XDG_CONFIG_HOME/crabfit-mcp/config.toml` if `XDG_CONFIG_HOME` is nonempty.
- Otherwise, `~/.config/crabfit-mcp/config.toml`.

```toml
timezone = "Europe/Paris"
```

Use `set_timezone` to validate and save it; the parent directory is created automatically and the file is replaced atomically. You can also create the file manually. It is dedicated to the timezone preference and shared by server processes using the same configuration directory. Changing it does not modify existing events.

If no default is saved, `create_event` requires an explicit timezone. Invalid or unreadable configuration reports an error rather than silently choosing another zone. `set_timezone` can replace invalid file content; filesystem permission errors must be fixed separately.

### Custom API endpoints

Set these environment variables in the MCP server's environment, not as tool arguments:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CRABFIT_API_URL` | `https://api.crab.fit` | Crab Fit API base URL |
| `CRABFIT_WEB_URL` | `https://crab.fit` | Base URL for returned event links |
| `XDG_CONFIG_HOME` | Unset | Override the configuration root |

For example, an MCP client server entry can include:

```json
"env": {
  "CRABFIT_API_URL": "http://127.0.0.1:3000",
  "CRABFIT_WEB_URL": "http://127.0.0.1:1234"
}
```

This is a fragment to add alongside `command` and `args`, not a complete client configuration. API and web URLs must be absolute HTTP(S) URLs without embedded credentials, queries, or fragments. Trailing slashes are removed. HTTP requests use a 20-second timeout with redirects disabled.

## Privacy and mutation safety

- The MCP process runs locally, but event and participant data is sent to the configured Crab Fit API. The default is the public production service, not local storage.
- No Crab Fit account or API key is required. Optional passwords protect individual participants; they are not API credentials.
- Passwords are UTF-8/base64 encoded in request-local Bearer headers. They are not written to disk or returned in tool results. **Base64 is not encryption:** use HTTPS outside local development. Your MCP client controls its own conversation and tool-call history.
- Invalid availability is rejected before the participant-creating request. Authentication failure prevents the availability update.
- Mutations are **never automatically retried**. After a timeout or transport failure, a mutation may already have taken effect. Check the event before repeating a creation or submission. A failed availability update may still have created the participant.
- The server exposes no event listing, statistics, or deletion tools.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Client cannot launch the server | Confirm `uv` is installed, use its absolute path if necessary, and check the checkout path in `--directory`. |
| Server seems to wait when started in a terminal | This is a stdio server, not a web UI. It waits for MCP protocol messages; connect it through your MCP client. Diagnostics go to stderr, leaving stdout for the protocol. |
| Timezone is requested again | Call `get_preferences`. Confirm the client runs as the same user and uses the same `XDG_CONFIG_HOME` as the process that saved the preference. |
| Event hours are shifted | Slots must be UTC. The display timezone does not convert them; account for daylight saving on the event dates. |
| Old tools or required timezone still appear | Restart/reconnect the MCP integration after updating the checkout. |
| Some availability disappeared | `set_availability` replaces the entire selection; send all slots you want to keep. |
| A mutation timed out | Do not blindly retry. Inspect the event first; the change may already have happened. |

## Development

```sh
uv sync --locked --dev
uv run pytest -q
```

The default suite covers time-slot validation, saved preferences, and API behavior using isolated HTTP transports. The real-backend integration test is opt-in and skipped by default.

To update an existing checkout, pull the desired changes, run `uv sync --locked`, and reconnect your MCP client.

<details>
<summary>Run the opt-in integration test against a local Crab Fit backend</summary>

Never run smoke-test mutations against production. Use a dedicated temporary backend. The integration test rejects non-loopback API hosts and launches the actual MCP stdio subprocess.

The previously verified upstream revision can be started from this worktree with:

```sh
git clone https://github.com/GRA0007/crab.fit.git .smoke-upstream
git -C .smoke-upstream checkout 628f9eefc300bf1ed3d6cc3323332c2ed9b8a350
rustup toolchain install 1.79.0 --profile minimal
cargo +1.79.0 run --manifest-path .smoke-upstream/api/Cargo.toml --locked
```

Check port 3000 is free first. If occupied, use a copied API source in the temporary smoke area with a free bind port; do not stop an unknown service. Rust 1.79 works with this pinned lockfile; the upstream `time 0.3.21` dependency fails with Rust 1.94.

In another terminal, with the development dependencies installed:

```sh
CRABFIT_INTEGRATION=1 \
CRABFIT_API_URL=http://127.0.0.1:3000 \
CRABFIT_WEB_URL=http://127.0.0.1:1234 \
uv run pytest -q tests/test_integration.py
```

The test checks event persistence, authenticated availability submission, replacement, wrong-password rejection, and clearing. Invalid-slot rejection before participant creation is covered at the isolated HTTP boundary, because the public people listing hides empty participants.

Stop only the backend you launched and remove the temporary checkout when finished. This verifies protocol and persistence, not browser rendering.

</details>

## References and attribution

- [Crab Fit](https://crab.fit/) and its [upstream source](https://github.com/GRA0007/crab.fit).
- [Crab Fit OpenAPI](https://api.crab.fit/docs/openapi.json) (API 3.0.0).
- Protocol reference: upstream revision [`628f9ee`](https://github.com/GRA0007/crab.fit/tree/628f9eefc300bf1ed3d6cc3323332c2ed9b8a350), including `api/src/routes/person.rs`, the event creation form, and the frontend time-slot serialization/expansion utilities.

Crab Fit is GPLv3; this wrapper uses it as a protocol reference and does not vendor its application code. FastMCP is Apache-2.0. These are upstream licenses, not a license grant for this repository. Dependency versions are recorded in `uv.lock`.

## Changelog

### Unreleased

- Persistent IANA timezone preferences through `get_preferences` and `set_timezone`.
- Optional `create_event.timezone`, using the saved default unless explicitly overridden.

### 0.1.0

- Dedicated stdio tools for event creation, discovery, and full availability replacement.
- Validated UTC slot IDs, display timezones, safe API errors, and shareable event links.
