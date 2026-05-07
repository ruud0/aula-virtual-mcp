#!/usr/bin/env python3
"""Aula Virtual UNAV - Blackboard Learn MCP Server.

Connects to https://aula-virtual.unav.edu for ALL enrolled courses.
Authenticate once with the `authenticate` tool, then use the rest freely.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

DEFAULT_COURSE_ID = "_51995_1"
BASE_URL = "https://aula-virtual.unav.edu"
API_BASE = f"{BASE_URL}/learn/api/public/v1"
SESSION_FILE = Path.home() / ".claude" / "aula_virtual_session.json"

app = Server("aula-virtual")


def load_session() -> dict:
    if SESSION_FILE.exists():
        return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    return {}


def save_session(data: dict) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def make_client() -> httpx.AsyncClient:
    session = load_session()
    cookies = session.get("cookies", {})
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    return httpx.AsyncClient(
        base_url=API_BASE,
        cookies=cookies,
        headers=headers,
        follow_redirects=True,
        timeout=30.0,
    )


def _auth_hint() -> str:
    return "\n\n💡 Run the `authenticate` tool first to log in."


def _resolve_course(arguments: dict) -> str:
    return arguments.get("course_id") or DEFAULT_COURSE_ID


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    course_id_prop = {
        "type": "string",
        "description": "Course ID (e.g. '_51995_1'). Omit to use default. Use list_courses to see all enrolled courses.",
    }

    return [
        types.Tool(
            name="authenticate",
            description=(
                "Open a browser window so you can log in to Aula Virtual UNAV via SSO. "
                "Run this once; the session is saved for future calls."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="list_courses",
            description="List all courses you are enrolled in. Returns course IDs and names.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_announcements",
            description="Return the latest course announcements.",
            inputSchema={
                "type": "object",
                "properties": {"course_id": course_id_prop},
                "required": [],
            },
        ),
        types.Tool(
            name="get_assignments",
            description="Return all gradebook columns (assignments) with due dates and max scores.",
            inputSchema={
                "type": "object",
                "properties": {"course_id": course_id_prop},
                "required": [],
            },
        ),
        types.Tool(
            name="get_course_content",
            description=(
                "Browse course content. Pass a content_id to drill into a folder, "
                "or omit it to list the root content tree."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "course_id": course_id_prop,
                    "content_id": {
                        "type": "string",
                        "description": "ID of a content item to list its children. Omit for root.",
                    },
                },
                "required": [],
            },
        ),
        types.Tool(
            name="get_grades",
            description="Return your grades for every gradebook column in the course.",
            inputSchema={
                "type": "object",
                "properties": {"course_id": course_id_prop},
                "required": [],
            },
        ),
        types.Tool(
            name="download_file",
            description="Download a course file by its content ID and save it locally.",
            inputSchema={
                "type": "object",
                "properties": {
                    "course_id": course_id_prop,
                    "content_id": {
                        "type": "string",
                        "description": "The content ID of the file to download.",
                    },
                    "save_path": {
                        "type": "string",
                        "description": "Local path to save the file (e.g. C:/Users/Ruudo/Downloads/lecture.pdf).",
                    },
                },
                "required": ["content_id", "save_path"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    handlers = {
        "authenticate": lambda: authenticate(),
        "list_courses": lambda: list_courses(),
        "get_announcements": lambda: get_announcements(_resolve_course(arguments)),
        "get_assignments": lambda: get_assignments(_resolve_course(arguments)),
        "get_course_content": lambda: get_course_content(
            _resolve_course(arguments), arguments.get("content_id")
        ),
        "get_grades": lambda: get_grades(_resolve_course(arguments)),
        "download_file": lambda: download_file(
            _resolve_course(arguments), arguments["content_id"], arguments["save_path"]
        ),
    }
    handler = handlers.get(name)
    if handler is None:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
    return await handler()


async def authenticate() -> list[types.TextContent]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return [types.TextContent(
            type="text",
            text="Playwright not installed. Run:\n  pip install playwright\n  playwright install chromium",
        )]

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False, slow_mo=50)
            ctx = await browser.new_context()
            page = await ctx.new_page()

            await page.goto(
                f"{BASE_URL}/ultra/course", wait_until="domcontentloaded",
            )

            print("[aula-virtual] Log in in the browser. Waiting up to 3 minutes…", flush=True)
            await page.wait_for_url("**/ultra/**", timeout=180_000)
            await asyncio.sleep(3)

            raw_cookies = await ctx.cookies()
            cookie_dict = {c["name"]: c["value"] for c in raw_cookies}
            save_session({"cookies": cookie_dict})
            await browser.close()

        return [types.TextContent(
            type="text",
            text=f"✅ Authenticated! {len(cookie_dict)} cookies saved to {SESSION_FILE}",
        )]
    except Exception as exc:
        return [types.TextContent(type="text", text=f"Authentication error: {exc}")]


async def list_courses() -> list[types.TextContent]:
    async with make_client() as client:
        try:
            me_r = await client.get("/users/me")
            me_r.raise_for_status()
            user_id = me_r.json().get("id", "")

            r = await client.get(
                f"/users/{user_id}/courses?limit=50&availability.available=Yes"
            )
            r.raise_for_status()
            items = r.json().get("results", [])
            if not items:
                return [types.TextContent(type="text", text="No enrolled courses found.")]

            course_ids = [item.get("courseId", "") for item in items]

            lines = []
            for item in items:
                cid = item.get("courseId", "")
                # Fetch course details for the name
                try:
                    cr = await client.get(f"/courses/{cid}")
                    cr.raise_for_status()
                    cdata = cr.json()
                    name = cdata.get("name", cdata.get("courseId", "?"))
                    course_id_internal = cdata.get("id", cid)
                    lines.append(f"- `{course_id_internal}` — **{name}**")
                except Exception:
                    lines.append(f"- `{cid}` — *(could not fetch name)*")

            return [types.TextContent(type="text", text="\n".join(lines))]
        except httpx.HTTPStatusError as exc:
            return [types.TextContent(
                type="text",
                text=f"HTTP {exc.response.status_code}{_auth_hint()}",
            )]
        except Exception as exc:
            return [types.TextContent(type="text", text=f"Error: {exc}{_auth_hint()}")]


async def get_announcements(course_id: str) -> list[types.TextContent]:
    async with make_client() as client:
        try:
            r = await client.get(f"/courses/{course_id}/announcements?limit=20")
            r.raise_for_status()
            items = r.json().get("results", [])
            if not items:
                return [types.TextContent(type="text", text="No announcements found.")]
            parts = []
            for a in items:
                title = a.get("title", "Untitled")
                created = a.get("created", "")
                body = a.get("body", "")
                parts.append(f"### {title}\n*{created}*\n\n{body}")
            return [types.TextContent(type="text", text="\n\n---\n\n".join(parts))]
        except httpx.HTTPStatusError as exc:
            return [types.TextContent(
                type="text",
                text=f"HTTP {exc.response.status_code}: {exc.response.text[:300]}{_auth_hint()}",
            )]
        except Exception as exc:
            return [types.TextContent(type="text", text=f"Error: {exc}{_auth_hint()}")]


async def get_assignments(course_id: str) -> list[types.TextContent]:
    async with make_client() as client:
        try:
            r = await client.get(f"/courses/{course_id}/gradebook/columns?limit=50")
            r.raise_for_status()
            items = r.json().get("results", [])
            if not items:
                return [types.TextContent(type="text", text="No assignments found.")]
            lines = ["| Assignment | Due | Max Score |", "|---|---|---|"]
            for col in items:
                name = col.get("name", "?")
                due = col.get("due", "—")
                possible = col.get("score", {}).get("possible", "?")
                lines.append(f"| {name} | {due} | {possible} |")
            return [types.TextContent(type="text", text="\n".join(lines))]
        except httpx.HTTPStatusError as exc:
            return [types.TextContent(
                type="text",
                text=f"HTTP {exc.response.status_code}{_auth_hint()}",
            )]
        except Exception as exc:
            return [types.TextContent(type="text", text=f"Error: {exc}{_auth_hint()}")]


async def get_course_content(course_id: str, content_id: str | None = None) -> list[types.TextContent]:
    async with make_client() as client:
        try:
            if content_id:
                url = f"/courses/{course_id}/contents/{content_id}/children?limit=50"
            else:
                url = f"/courses/{course_id}/contents?limit=50"
            r = await client.get(url)
            r.raise_for_status()
            items = r.json().get("results", [])
            if not items:
                return [types.TextContent(type="text", text="No content found here.")]
            lines = []
            for item in items:
                cid = item.get("id", "")
                title = item.get("title", "Untitled")
                handler = item.get("contentHandler", {}).get("id", "unknown")
                type_map = {
                    "resource/x-bb-folder": "📁 Folder",
                    "resource/x-bb-document": "📄 Document",
                    "resource/x-bb-file": "📎 File",
                    "resource/x-bb-assignment": "📝 Assignment",
                    "resource/x-bb-externallink": "🔗 Link",
                    "resource/x-bb-video": "🎬 Video",
                }
                label = type_map.get(handler, f"[{handler}]")
                lines.append(f"- `{cid}` {label} **{title}**")
            return [types.TextContent(type="text", text="\n".join(lines))]
        except httpx.HTTPStatusError as exc:
            return [types.TextContent(
                type="text",
                text=f"HTTP {exc.response.status_code}{_auth_hint()}",
            )]
        except Exception as exc:
            return [types.TextContent(type="text", text=f"Error: {exc}{_auth_hint()}")]


async def get_grades(course_id: str) -> list[types.TextContent]:
    async with make_client() as client:
        try:
            me_r = await client.get("/users/me")
            me_r.raise_for_status()
            user_id = me_r.json().get("id", "")

            r = await client.get(
                f"/users/{user_id}/courses/{course_id}/gradebook/columns?limit=50"
            )
            r.raise_for_status()
            items = r.json().get("results", [])
            if not items:
                return [types.TextContent(type="text", text="No grades found.")]
            lines = ["| Assignment | Score | Max | Status |", "|---|---|---|---|"]
            for g in items:
                name = g.get("columnName", "?")
                score_obj = g.get("score", {})
                given = score_obj.get("given", "—")
                possible = score_obj.get("possible", "?")
                status = g.get("status", "—")
                lines.append(f"| {name} | {given} | {possible} | {status} |")
            return [types.TextContent(type="text", text="\n".join(lines))]
        except httpx.HTTPStatusError as exc:
            return [types.TextContent(
                type="text",
                text=f"HTTP {exc.response.status_code}{_auth_hint()}",
            )]
        except Exception as exc:
            return [types.TextContent(type="text", text=f"Error: {exc}{_auth_hint()}")]


async def download_file(course_id: str, content_id: str, save_path: str) -> list[types.TextContent]:
    async with make_client() as client:
        try:
            meta_r = await client.get(f"/courses/{course_id}/contents/{content_id}")
            meta_r.raise_for_status()
            meta = meta_r.json()
            title = meta.get("title", content_id)

            att_r = await client.get(f"/courses/{course_id}/contents/{content_id}/attachments")
            att_r.raise_for_status()
            attachments = att_r.json().get("results", [])
            if not attachments:
                return [types.TextContent(type="text", text=f"No downloadable attachment found for '{title}'.")]

            attachment = attachments[0]
            download_url = f"{BASE_URL}{attachment.get('downloadUri', '')}"

            session = load_session()
            cookies = session.get("cookies", {})
            async with httpx.AsyncClient(cookies=cookies, follow_redirects=True, timeout=60.0) as dl_client:
                dl_r = await dl_client.get(download_url)
                dl_r.raise_for_status()
                Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                Path(save_path).write_bytes(dl_r.content)

            size_kb = len(dl_r.content) / 1024
            return [types.TextContent(
                type="text",
                text=f"✅ Downloaded '{title}' ({size_kb:.1f} KB) → {save_path}",
            )]
        except httpx.HTTPStatusError as exc:
            return [types.TextContent(
                type="text",
                text=f"HTTP {exc.response.status_code}{_auth_hint()}",
            )]
        except Exception as exc:
            return [types.TextContent(type="text", text=f"Error: {exc}")]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
