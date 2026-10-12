"""KuubWave dictation history — a local MCP server (stdio) for Claude Code.

Lets Claude Code read what the user dictated earlier (KuubWave history.db).
Stdlib only, runs on any Python 3.10+. Read-only: the database is opened via
SQLite URI ``mode=ro`` per call and closed right away, so the running app is
never blocked. No network: the transport is newline-delimited JSON-RPC 2.0 on
stdin/stdout. Logs go to stderr only.

Register (user scope):
    claude mcp add kuubwave-history --scope user -- py -3 "C:\\project whspr\\mcp_history.py"

Not bundled into the installer — it's a power-user tool.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

SERVER_NAME = "kuubwave-history"
SERVER_VERSION = "1.0.0"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL = SUPPORTED_PROTOCOLS[0]
MAX_LIMIT = 200
DEFAULT_LIMIT = 20
TS_FMT = "%Y-%m-%d %H:%M:%S"


def log(*args) -> None:
    print("[kuubwave-history]", *args, file=sys.stderr, flush=True)


# --------------------------------------------------------------------- DB path
def default_db_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    primary = base / "KuubWave" / "history.db"
    legacy = base / "whspr" / "history.db"
    if not primary.exists() and legacy.exists():
        return legacy
    return primary


class ToolError(Exception):
    """Error reported to the client as a tool result with isError=true."""


def _clamp_limit(value, default=DEFAULT_LIMIT) -> int:
    if value is None:
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ToolError(f"limit must be an integer, got {value!r}")
    return max(1, min(MAX_LIMIT, n))


def _opt_positive(value, name):
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise ToolError(f"{name} must be a number, got {value!r}")
    if n <= 0:
        raise ToolError(f"{name} must be > 0")
    return n


class History:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise ToolError(
                f"Dictation history not found at {self.db_path}. "
                "Is KuubWave installed and has the user dictated anything yet? "
                "(A different path can be given with --db.)")
        uri = "file:" + quote(self.db_path.resolve().as_posix(), safe="/:") + "?mode=ro"
        try:
            con = sqlite3.connect(uri, uri=True, timeout=2.0,
                                  check_same_thread=False)
            con.execute("PRAGMA query_only = ON")
            con.execute("PRAGMA busy_timeout = 2000")
        except sqlite3.Error as e:
            raise ToolError(f"Cannot open history database read-only: {e}")
        return con

    def query(self, sql: str, params=()) -> list[tuple]:
        con = self._connect()
        try:
            return con.execute(sql, params).fetchall()
        except sqlite3.Error as e:
            raise ToolError(f"History database query failed: {e}")
        finally:
            con.close()


def _fmt_rows(rows) -> str:
    lines = []
    for ts, lang, text in rows:
        text = " ".join((text or "").split())
        lines.append(f"{ts} · {lang or '?'} · {text}")
    return "\n".join(lines)


def _since(minutes: float) -> str:
    return (_dt.datetime.now() - _dt.timedelta(minutes=minutes)).strftime(TS_FMT)


# ----------------------------------------------------------------------- tools
def tool_recent(h: History, args: dict) -> str:
    limit = _clamp_limit(args.get("limit"))
    since_minutes = _opt_positive(args.get("since_minutes"), "since_minutes")
    if since_minutes is not None:
        rows = h.query(
            "SELECT ts, lang, text FROM history WHERE ts >= ? "
            "ORDER BY ts DESC, id DESC LIMIT ?", (_since(since_minutes), limit))
    else:
        rows = h.query(
            "SELECT ts, lang, text FROM history ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,))
    if not rows:
        scope = (f" in the last {since_minutes:g} minutes"
                 if since_minutes is not None else "")
        return f"No dictations{scope}."
    return f"{len(rows)} most recent dictation(s), newest first:\n" + _fmt_rows(rows)


def tool_search(h: History, args: dict) -> str:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("query must be a non-empty string")
    needle = query.strip().casefold()
    limit = _clamp_limit(args.get("limit"))
    days = _opt_positive(args.get("days"), "days")
    sql = "SELECT ts, lang, text FROM history"
    params: tuple = ()
    if days is not None:
        sql += " WHERE ts >= ?"
        params = (_since(days * 24 * 60),)
    sql += " ORDER BY ts DESC, id DESC"
    con_rows = h.query(sql, params)
    # Python-side casefold: SQLite LIKE/lower() only fold ASCII, not Cyrillic.
    hits = [r for r in con_rows if needle in (r[2] or "").casefold()][:limit]
    if not hits:
        scope = f" in the last {days:g} day(s)" if days is not None else ""
        return f"No dictations containing {query.strip()!r}{scope}."
    return (f"{len(hits)} dictation(s) containing {query.strip()!r}, newest first:\n"
            + _fmt_rows(hits))


def tool_stats(h: History, args: dict) -> str:
    total, first, last, total_words = h.query(
        "SELECT COUNT(*), MIN(ts), MAX(ts), COALESCE(SUM(words), 0) FROM history")[0]
    today = _dt.date.today().strftime("%Y-%m-%d")
    t_count, t_words = h.query(
        "SELECT COUNT(*), COALESCE(SUM(words), 0) FROM history WHERE ts >= ?",
        (today + " 00:00:00",))[0]
    if not total:
        return "The dictation history is empty."
    return "\n".join([
        f"Total dictations: {total} ({total_words} words)",
        f"Today ({today}): {t_count} dictation(s), {t_words} words",
        f"Date range: {first} — {last}",
    ])


TOOLS = [
    {
        "name": "recent_dictations",
        "title": "Recent dictations",
        "description": (
            "Return the user's most recent voice dictations from KuubWave (their "
            "local speech-to-text app), newest first, one per line as "
            "'timestamp · language · text'. The user often dictates their requests "
            "and notes by voice (mostly Ukrainian, sometimes English); use this to "
            "recover what they said earlier, e.g. 'what did I dictate in the last "
            "hour', 'paste what I said a minute ago', or when a request seems to "
            "reference something they dictated elsewhere."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT,
                          "default": DEFAULT_LIMIT,
                          "description": f"Max entries to return (1-{MAX_LIMIT})."},
                "since_minutes": {"type": "number", "exclusiveMinimum": 0,
                                  "description": "Only dictations from the last N minutes."},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "search_dictations",
        "title": "Search dictations",
        "description": (
            "Search the user's voice-dictation history (KuubWave) for entries "
            "containing a word or phrase. Case-insensitive substring match that "
            "works for Cyrillic (Ukrainian/Russian) and Latin text; newest first. "
            "Use when the user asks what they said about some topic, or to find an "
            "earlier dictated message, idea or instruction. Try short stems "
            "(e.g. 'сервер' rather than 'серверу') since Ukrainian words inflect."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1,
                          "description": "Substring to look for (case-insensitive)."},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT,
                          "default": DEFAULT_LIMIT,
                          "description": f"Max entries to return (1-{MAX_LIMIT})."},
                "days": {"type": "number", "exclusiveMinimum": 0,
                         "description": "Only search the last N days."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "dictation_stats",
        "title": "Dictation statistics",
        "description": (
            "Summary of the user's KuubWave voice-dictation history: total number "
            "of dictations and words, today's count and words, and the date range "
            "covered. Use to check whether history exists or how much the user "
            "dictated today."),
        "inputSchema": {"type": "object", "properties": {},
                        "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]

HANDLERS = {
    "recent_dictations": tool_recent,
    "search_dictations": tool_search,
    "dictation_stats": tool_stats,
}


# ------------------------------------------------------------------ JSON-RPC
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


def _error(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _result(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


class Server:
    def __init__(self, db_path: Path):
        self.history = History(db_path)

    def handle_line(self, line: str):
        """Process one input line; return a response dict or None."""
        line = line.strip()
        if not line:
            return None
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            log("parse error:", e)
            return _error(None, PARSE_ERROR, f"Parse error: {e.msg}")
        if isinstance(msg, list):  # batch (2025-03-26); answer each request
            out = [r for r in (self.handle_message(m) for m in msg) if r]
            return out or None
        return self.handle_message(msg)

    def handle_message(self, msg):
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return _error(msg.get("id") if isinstance(msg, dict) else None,
                          INVALID_REQUEST, "Invalid Request")
        method = msg.get("method")
        id_ = msg.get("id")
        is_notification = "id" not in msg
        if not isinstance(method, str):
            # A response from the client (we never send requests) — ignore.
            return None if ("result" in msg or "error" in msg) else \
                _error(id_, INVALID_REQUEST, "Invalid Request")
        params = msg.get("params") or {}
        try:
            result = self.dispatch(method, params)
        except _RpcError as e:
            return None if is_notification else _error(id_, e.code, e.message)
        except Exception as e:  # never crash the loop
            log("internal error in", method, repr(e))
            return None if is_notification else _error(id_, -32603, f"Internal error: {e}")
        if is_notification:
            return None
        return _result(id_, result)

    def dispatch(self, method, params):
        if method == "initialize":
            requested = params.get("protocolVersion") if isinstance(params, dict) else None
            version = requested if requested in SUPPORTED_PROTOCOLS else LATEST_PROTOCOL
            return {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "title": "KuubWave dictation history",
                               "version": SERVER_VERSION},
                "instructions": (
                    "Read-only access to the user's local KuubWave voice-dictation "
                    "history. The user dictates many requests by voice; use these "
                    "tools to recover what they said earlier."),
            }
        if method.startswith("notifications/"):
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                raise _RpcError(INVALID_PARAMS, "tools/call requires a tool name")
            name = params["name"]
            handler = HANDLERS.get(name)
            if handler is None:
                raise _RpcError(INVALID_PARAMS, f"Unknown tool: {name}")
            args = params.get("arguments") or {}
            if not isinstance(args, dict):
                raise _RpcError(INVALID_PARAMS, "arguments must be an object")
            try:
                text = handler(self.history, args)
                is_error = False
            except ToolError as e:
                text, is_error = str(e), True
            return {"content": [{"type": "text", "text": text}], "isError": is_error}
        raise _RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")

    def serve(self, stdin, stdout):
        log(f"started, db={self.history.db_path}")
        for line in stdin:
            resp = self.handle_line(line)
            if resp is not None:
                stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                stdout.flush()
        log("stdin closed, exiting")


class _RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="KuubWave dictation history MCP server (stdio)")
    ap.add_argument("--db", help="path to history.db (default: %%LOCALAPPDATA%%\\KuubWave\\history.db)")
    ns = ap.parse_args(argv)
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", newline="\n")
        except (AttributeError, ValueError):
            pass
    db = Path(ns.db) if ns.db else default_db_path()
    try:
        Server(db).serve(sys.stdin, sys.stdout)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
