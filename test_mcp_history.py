"""Tests for mcp_history.py (stdlib MCP server over KuubWave history.db)."""
import datetime as dt
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import mcp_history as mh

HERE = Path(__file__).resolve().parent


def make_db(path: Path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE history(id INTEGER PRIMARY KEY, ts TEXT, lang TEXT,"
                " duration REAL, text TEXT, words INTEGER)")
    con.executemany("INSERT INTO history(ts, lang, duration, text, words) VALUES (?,?,?,?,?)",
                    rows)
    con.commit()
    con.close()


def ago(**kw):
    return (dt.datetime.now() - dt.timedelta(**kw)).strftime(mh.TS_FMT)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "history.db"
        rows = [
            (ago(days=10), "en", 1.0, "Old note about Docker", 4),
            (ago(days=2), "uk", 1.0, "Перевір СЕРВЕР на медіа", 4),
            (ago(minutes=90), "uk", 1.0, "Привіт, світе", 2),
            (ago(minutes=5), "uk", 1.0, "налаштуй сервер nginx", 3),
            (ago(minutes=1), "en", 1.0, "Fix the build", 3),
        ]
        make_db(self.db, rows)
        self.srv = mh.Server(self.db)
        self._id = 0

    def tearDown(self):
        self.tmp.cleanup()

    def rpc(self, method, params=None):
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        return self.srv.handle_line(json.dumps(msg))

    def call(self, name, **args):
        r = self.rpc("tools/call", {"name": name, "arguments": args})
        res = r["result"]
        self.assertEqual(res["content"][0]["type"], "text")
        return res["content"][0]["text"], res["isError"]


class TestProtocol(Base):
    def test_initialize_echoes_supported_version(self):
        for v in ("2025-06-18", "2025-03-26", "2024-11-05"):
            r = self.rpc("initialize", {"protocolVersion": v, "capabilities": {},
                                        "clientInfo": {"name": "t", "version": "0"}})
            self.assertEqual(r["result"]["protocolVersion"], v)
            self.assertIn("tools", r["result"]["capabilities"])
            self.assertEqual(r["result"]["serverInfo"]["name"], "kuubwave-history")

    def test_initialize_unknown_version_gets_latest(self):
        r = self.rpc("initialize", {"protocolVersion": "1999-01-01"})
        self.assertEqual(r["result"]["protocolVersion"], mh.LATEST_PROTOCOL)

    def test_notification_no_response(self):
        line = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertIsNone(self.srv.handle_line(line))

    def test_ping(self):
        self.assertEqual(self.rpc("ping")["result"], {})

    def test_unknown_method(self):
        r = self.rpc("resources/list")
        self.assertEqual(r["error"]["code"], -32601)

    def test_malformed_json(self):
        r = self.srv.handle_line("{not json")
        self.assertEqual(r["error"]["code"], -32700)
        self.assertIsNone(r["id"])
        self.assertEqual(self.rpc("ping")["result"], {})  # still alive

    def test_invalid_request(self):
        r = self.srv.handle_line(json.dumps({"id": 1, "method": "ping"}))
        self.assertEqual(r["error"]["code"], -32600)

    def test_tools_list(self):
        tools = self.rpc("tools/list")["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertEqual(names, {"recent_dictations", "search_dictations", "dictation_stats"})
        for t in tools:
            self.assertTrue(t["description"])
            self.assertEqual(t["inputSchema"]["type"], "object")
        search = next(t for t in tools if t["name"] == "search_dictations")
        self.assertEqual(search["inputSchema"]["required"], ["query"])

    def test_unknown_tool(self):
        r = self.rpc("tools/call", {"name": "nope", "arguments": {}})
        self.assertEqual(r["error"]["code"], -32602)


class TestTools(Base):
    def test_recent_newest_first(self):
        text, err = self.call("recent_dictations", limit=2)
        self.assertFalse(err)
        lines = text.splitlines()[1:]
        self.assertEqual(len(lines), 2)
        self.assertIn("Fix the build", lines[0])
        self.assertIn(" · en · ", lines[0])
        self.assertIn("налаштуй сервер", lines[1])

    def test_recent_since_minutes(self):
        text, _ = self.call("recent_dictations", since_minutes=60)
        self.assertEqual(len(text.splitlines()) - 1, 2)
        self.assertNotIn("Привіт", text)

    def test_recent_empty_window(self):
        make_db_rows = Path(self.tmp.name) / "empty.db"
        make_db(make_db_rows, [])
        srv = mh.Server(make_db_rows)
        r = srv.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                        "params": {"name": "recent_dictations"}}))
        self.assertIn("No dictations", r["result"]["content"][0]["text"])

    def test_limit_clamped(self):
        self.assertEqual(mh._clamp_limit(10_000), mh.MAX_LIMIT)
        self.assertEqual(mh._clamp_limit(0), 1)
        self.assertEqual(mh._clamp_limit(-5), 1)
        text, err = self.call("recent_dictations", limit=999)
        self.assertFalse(err)
        self.assertEqual(len(text.splitlines()) - 1, 5)

    def test_bad_limit_is_tool_error(self):
        text, err = self.call("recent_dictations", limit="abc")
        self.assertTrue(err)

    def test_search_cyrillic_case_insensitive(self):
        text, err = self.call("search_dictations", query="сЕрВеР")
        self.assertFalse(err)
        lines = text.splitlines()[1:]
        self.assertEqual(len(lines), 2)
        self.assertIn("налаштуй", lines[0])  # newest first
        self.assertIn("СЕРВЕР", lines[1])

    def test_search_days_and_limit(self):
        text, _ = self.call("search_dictations", query="сервер", days=1)
        self.assertEqual(len(text.splitlines()) - 1, 1)
        text, _ = self.call("search_dictations", query="сервер", limit=1)
        self.assertEqual(len(text.splitlines()) - 1, 1)
        text, _ = self.call("search_dictations", query="docker")
        self.assertIn("Old note", text)

    def test_search_no_match_and_empty_query(self):
        text, err = self.call("search_dictations", query="кавун")
        self.assertFalse(err)
        self.assertIn("No dictations", text)
        _, err = self.call("search_dictations", query="  ")
        self.assertTrue(err)

    def test_stats(self):
        text, err = self.call("dictation_stats")
        self.assertFalse(err)
        self.assertIn("Total dictations: 5 (16 words)", text)
        self.assertIn("Date range:", text)
        self.assertRegex(text, r"Today \(\d{4}-\d{2}-\d{2}\): [1-3] dictation")

    def test_missing_db_is_tool_error(self):
        srv = mh.Server(Path(self.tmp.name) / "missing.db")
        for name in ("recent_dictations", "search_dictations", "dictation_stats"):
            r = srv.handle_line(json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": name, "arguments": {"query": "x"}}}))
            self.assertTrue(r["result"]["isError"])
            self.assertIn("not found", r["result"]["content"][0]["text"])
        self.assertFalse((Path(self.tmp.name) / "missing.db").exists())

    def test_read_only(self):
        con = self.srv.history._connect()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("DELETE FROM history")
        finally:
            con.close()

    def test_default_path_legacy_fallback(self):
        old = os.environ.get("LOCALAPPDATA")
        try:
            os.environ["LOCALAPPDATA"] = self.tmp.name
            self.assertEqual(mh.default_db_path(),
                             Path(self.tmp.name) / "KuubWave" / "history.db")
            (Path(self.tmp.name) / "whspr").mkdir()
            make_db(Path(self.tmp.name) / "whspr" / "history.db", [])
            self.assertEqual(mh.default_db_path(),
                             Path(self.tmp.name) / "whspr" / "history.db")
        finally:
            if old is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = old


class TestSubprocess(Base):
    def test_stdio_roundtrip(self):
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "search_dictations", "arguments": {"query": "ПРИВІТ"}}},
        ]
        payload = "{broken\n" + "\n".join(json.dumps(m, ensure_ascii=False) for m in msgs) + "\n"
        env = dict(os.environ, PYTHONIOENCODING="cp1251")  # reconfigure must win
        p = subprocess.run([sys.executable, str(HERE / "mcp_history.py"), "--db", str(self.db)],
                           input=payload.encode("utf-8"), capture_output=True,
                           timeout=30, env=env)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        out = [json.loads(l) for l in p.stdout.decode("utf-8").splitlines() if l.strip()]
        self.assertEqual(len(out), 4)  # parse error + 3 responses (no reply to notification)
        self.assertEqual(out[0]["error"]["code"], -32700)
        self.assertEqual(out[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(len(out[2]["result"]["tools"]), 3)
        self.assertIn("Привіт, світе", out[3]["result"]["content"][0]["text"])
        self.assertNotIn(b"\r\n", p.stdout)


if __name__ == "__main__":
    unittest.main()
