#!/usr/bin/env python3
"""Tiny local-only Ollama chat UI."""
from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_MODEL = "gemma4:26b"
DEFAULT_OLLAMA = "http://127.0.0.1:11434"
ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
PROJECT_ROOT = ROOT.parent
DATA_DIR = Path(os.environ.get("OLLAMA_CHAT_DATA", PROJECT_ROOT / "data"))
DB_PATH = Path(os.environ.get("OLLAMA_CHAT_DB", DATA_DIR / "chat.sqlite3"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                thinking TEXT DEFAULT '',
                timestamp TEXT NOT NULL,
                model TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
            """
        )
        # Upgrade older databases.
        cols = {row[1] for row in db.execute("PRAGMA table_info(messages)")}
        if "thinking" not in cols:
            db.execute("ALTER TABLE messages ADD COLUMN thinking TEXT DEFAULT ''")


def rowdict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def db_connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def ensure_conversation(db: sqlite3.Connection, conversation_id: str | None, title_seed: str = "New chat") -> str:
    if conversation_id:
        exists = db.execute("SELECT id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if exists:
            return conversation_id
    cid = str(uuid.uuid4())
    title = (title_seed.strip().splitlines()[0][:48] or "New chat")
    ts = now_iso()
    db.execute("INSERT INTO conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)", (cid, title, ts, ts))
    return cid


def load_messages(db: sqlite3.Connection, conversation_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT role, content, COALESCE(thinking,'') AS thinking, timestamp, model FROM messages WHERE conversation_id=? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    return [rowdict(r) for r in rows]


def ollama_url(path: str) -> str:
    base = Handler.ollama_host.rstrip("/")
    return base + path


class Handler(BaseHTTPRequestHandler):
    server_version = "OllamaLocalChat/3.0"
    ollama_host = DEFAULT_OLLAMA
    default_model = DEFAULT_MODEL

    def log_message(self, fmt: str, *args: Any) -> None:
        print("%s - %s" % (self.address_string(), fmt % args), file=sys.stderr)

    def _send(self, status: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def json(self, status: int, data: Any) -> None:
        self._send(status, json.dumps(data).encode("utf-8"))

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self.serve_static("index.html", "text/html; charset=utf-8")
        if path.startswith("/static/"):
            name = path.removeprefix("/static/")
            if "/" in name or ".." in name:
                return self.json(404, {"error": "not found"})
            ctype = "text/plain; charset=utf-8"
            if name.endswith(".css"):
                ctype = "text/css; charset=utf-8"
            elif name.endswith(".js"):
                ctype = "text/javascript; charset=utf-8"
            return self.serve_static(name, ctype)
        if path == "/api/config":
            return self.json(200, {"default_model": self.default_model, "ollama_host": self.ollama_host})
        if path == "/api/models":
            return self.api_models()
        if path == "/api/conversations":
            return self.api_conversations()
        if path.startswith("/api/conversations/"):
            cid = path.rsplit("/", 1)[-1]
            return self.api_conversation(cid)
        self.json(404, {"error": "not found"})

    def serve_static(self, name: str, ctype: str) -> None:
        p = STATIC / name
        if not p.exists() or not p.is_file():
            return self.json(404, {"error": "not found"})
        self._send(200, p.read_bytes(), ctype)

    def api_models(self) -> None:
        names = [self.default_model]
        try:
            with urllib.request.urlopen(ollama_url("/api/tags"), timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for item in data.get("models", []):
                name = item.get("name")
                if name and name not in names:
                    names.append(name)
        except Exception as e:
            return self.json(200, {"models": names, "warning": f"Could not read Ollama models: {e}"})
        self.json(200, {"models": names})

    def api_conversations(self) -> None:
        with db_connect() as db:
            rows = db.execute(
                "SELECT id,title,created_at,updated_at FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
        self.json(200, {"conversations": [rowdict(r) for r in rows]})

    def api_conversation(self, cid: str) -> None:
        with db_connect() as db:
            conv = db.execute("SELECT id,title,created_at,updated_at FROM conversations WHERE id=?", (cid,)).fetchone()
            if not conv:
                return self.json(404, {"error": "conversation not found"})
            self.json(200, {"conversation": rowdict(conv), "messages": load_messages(db, cid)})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/chat":
                return self.api_chat()
            if path == "/api/conversations":
                return self.api_new_conversation()
            if path.endswith("/rename") and path.startswith("/api/conversations/"):
                cid = path.split("/")[3]
                return self.api_rename(cid)
            if path.endswith("/clear") and path.startswith("/api/conversations/"):
                cid = path.split("/")[3]
                return self.api_clear(cid)
            if path.endswith("/export") and path.startswith("/api/conversations/"):
                cid = path.split("/")[3]
                return self.api_export(cid)
        except json.JSONDecodeError:
            return self.json(400, {"error": "invalid json"})
        except Exception as e:
            return self.json(500, {"error": str(e)})
        self.json(404, {"error": "not found"})

    def do_DELETE(self) -> None:
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/conversations/"):
            cid = path.rsplit("/", 1)[-1]
            with db_connect() as db:
                db.execute("DELETE FROM conversations WHERE id=?", (cid,))
            return self.json(200, {"ok": True})
        self.json(404, {"error": "not found"})

    def api_new_conversation(self) -> None:
        data = self.read_json()
        title = data.get("title") or "New chat"
        with db_connect() as db:
            cid = ensure_conversation(db, None, title)
            conv = db.execute("SELECT id,title,created_at,updated_at FROM conversations WHERE id=?", (cid,)).fetchone()
        self.json(200, {"conversation": rowdict(conv)})

    def api_rename(self, cid: str) -> None:
        title = str(self.read_json().get("title") or "").strip()[:80]
        if not title:
            return self.json(400, {"error": "title required"})
        with db_connect() as db:
            db.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?", (title, now_iso(), cid))
        self.json(200, {"ok": True})

    def api_clear(self, cid: str) -> None:
        with db_connect() as db:
            db.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now_iso(), cid))
        self.json(200, {"ok": True})

    def api_export(self, cid: str) -> None:
        with db_connect() as db:
            conv = db.execute("SELECT title FROM conversations WHERE id=?", (cid,)).fetchone()
            if not conv:
                return self.json(404, {"error": "conversation not found"})
            messages = load_messages(db, cid)
        lines = [f"# {conv['title']}", ""]
        for m in messages:
            lines.append(f"## {m['role'].title()} — {m['model']} — {m['timestamp']}")
            lines.append("")
            if m.get("thinking"):
                lines.append("<details><summary>Thinking</summary>")
                lines.append("")
                lines.append(m["thinking"])
                lines.append("")
                lines.append("</details>")
                lines.append("")
            lines.append(m["content"])
            lines.append("")
        body = "\n".join(lines).encode("utf-8")
        filename = "chat-export.md"
        self.send_response(200)
        self.send_header("Content-Type", "text/markdown; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_event(self, name: str, data: Any) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        self.wfile.write(f"event: {name}\n".encode("utf-8"))
        for line in payload.splitlines() or [""]:
            self.wfile.write(f"data: {line}\n".encode("utf-8"))
        self.wfile.write(b"\n")
        self.wfile.flush()

    def api_chat(self) -> None:
        data = self.read_json()
        model = str(data.get("model") or self.default_model).strip() or self.default_model
        content = str(data.get("message") or "").strip()
        system = str(data.get("system") or "").strip()
        private = bool(data.get("private"))
        cid = data.get("conversation_id")
        if not content:
            return self.json(400, {"error": "message required"})

        history: list[dict[str, str]] = []
        created_cid = cid
        if not private:
            with db_connect() as db:
                created_cid = ensure_conversation(db, cid, content)
                history = [{"role": m["role"], "content": m["content"]} for m in load_messages(db, created_cid)]
                ts = now_iso()
                db.execute(
                    "INSERT INTO messages(conversation_id,role,content,thinking,timestamp,model) VALUES(?,?,?,?,?,?)",
                    (created_cid, "user", content, "", ts, model),
                )
                db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (ts, created_cid))
        else:
            history = data.get("private_history") or []

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.extend(history)
        messages.append({"role": "user", "content": content})

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.send_event("meta", {"conversation_id": created_cid, "model": model, "timestamp": now_iso()})

        request_body = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": True,
        }
        answer_parts: list[str] = []
        thinking_parts: list[str] = []

        try:
            req = urllib.request.Request(
                ollama_url("/api/chat"),
                data=json.dumps(request_body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                for raw in resp:
                    if not raw:
                        continue
                    text = raw.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    # Ollama returns JSONL. Be forgiving in case a proxy or old endpoint changes shape.
                    if text.startswith("data:"):
                        text = text[5:].strip()
                    try:
                        obj = json.loads(text)
                    except json.JSONDecodeError:
                        answer_parts.append(text)
                        self.send_event("content", {"text": text})
                        continue
                    if obj.get("error"):
                        raise RuntimeError(str(obj["error"]))
                    msg = obj.get("message") or {}
                    thinking = msg.get("thinking") or obj.get("thinking") or ""
                    content_part = msg.get("content") or obj.get("response") or ""
                    if thinking:
                        thinking_parts.append(thinking)
                        self.send_event("thinking", {"text": thinking})
                    if content_part:
                        answer_parts.append(content_part)
                        self.send_event("content", {"text": content_part})
                    if obj.get("done"):
                        break
        except urllib.error.URLError as e:
            self.send_event("error", {"error": f"Could not reach Ollama at {self.ollama_host}: {e}"})
            return
        except Exception as e:
            self.send_event("error", {"error": str(e)})
            return

        answer = "".join(answer_parts).strip()
        thinking = "".join(thinking_parts).strip()
        ts = now_iso()
        if not private and created_cid and answer:
            with db_connect() as db:
                db.execute(
                    "INSERT INTO messages(conversation_id,role,content,thinking,timestamp,model) VALUES(?,?,?,?,?,?)",
                    (created_cid, "assistant", answer, thinking, ts, model),
                )
                db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (ts, created_cid))
        self.send_event("done", {"conversation_id": created_cid, "timestamp": ts})


def main() -> int:
    parser = argparse.ArgumentParser(description="Local-only browser chat interface for Ollama")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--ollama", default=DEFAULT_OLLAMA)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    if args.host != "127.0.0.1":
        print("Warning: binding to a non-loopback host exposes the app beyond this machine.", file=sys.stderr)

    init_db()
    Handler.ollama_host = args.ollama
    Handler.default_model = args.model
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True

    def shutdown(signum: int, frame: Any) -> None:
        print("\nShutting down...")
        httpd.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    print(f"Ollama Local Chat running at http://{args.host}:{args.port}")
    print(f"Ollama API: {args.ollama}")
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
