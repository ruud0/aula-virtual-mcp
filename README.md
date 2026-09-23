# Aula Virtual MCP Server

An MCP (Model Context Protocol) server that connects Claude to Blackboard Learn (Aula Virtual). Browse courses, check grades, read announcements, and download files, all through natural conversation.

## Demo

![demo](docs/demo.gif)

<!-- Record a short screen capture of a real session and save it to
     docs/demo.gif. Until then this image renders as broken. -->

## What it does

- **Authenticate** via browser-based SSO (Playwright opens a login window, saves cookies)
- **List courses** you're enrolled in
- **Get announcements** for any course
- **Get assignments** with due dates and max scores
- **Browse course content**: folders, documents, files, links
- **Check grades** across all gradebook columns
- **Download files** from course content to your local machine

## Setup

```bash
pip install mcp httpx playwright
playwright install chromium
python server.py
```

Add to your Claude Code MCP config:

```json
{
  "mcpServers": {
    "aula-virtual": {
      "command": "python",
      "args": ["C:/path/to/aula-virtual-mcp/server.py"]
    }
  }
}
```

## Usage

1. Ask Claude to `authenticate`, and a browser window opens for SSO login
2. Then use any tool: `list_courses`, `get_grades`, `get_announcements`, etc.
3. Session cookies are cached at `~/.claude/aula_virtual_session.json`

## Architecture

- `server.py`: MCP server with Blackboard Learn REST API v1 integration
- Uses `httpx` for async HTTP, `playwright` for SSO authentication

## Adaptability

Built for Universidad de Navarra's Aula Virtual, but the Blackboard Learn API is standard, so you can change `BASE_URL` to point at any Blackboard Ultra instance.
