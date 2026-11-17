"""SQLite storage (single local founder). Tables hold JSON blobs; code validates them on read."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.config import data_dir

_LOCK = threading.RLock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created_at TEXT, state TEXT);
CREATE TABLE IF NOT EXISTS claims (id TEXT PRIMARY KEY, run_id TEXT, body TEXT);
CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, run_id TEXT, tier INTEGER, status TEXT, body TEXT);
CREATE TABLE IF NOT EXISTS locks (id TEXT PRIMARY KEY, run_id TEXT, name TEXT, body TEXT, sha256 TEXT, locked_at TEXT);
CREATE TABLE IF NOT EXISTS signups (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, email TEXT, ts TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS visits (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, ts TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS kv (run_id TEXT, key TEXT, body TEXT, PRIMARY KEY (run_id, key));
"""


def db_path() -> Path:
    return data_dir() / "venture.sqlite3"


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    with _LOCK:
        c = sqlite3.connect(db_path(), check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            c.executescript(_SCHEMA)
            yield c
            c.commit()
        finally:
            c.close()


def kv_get(run_id: str, key: str, default: Any = None) -> Any:
    with conn() as c:
        row = c.execute("SELECT body FROM kv WHERE run_id=? AND key=?", (run_id, key)).fetchone()
    return json.loads(row["body"]) if row else default


def kv_set(run_id: str, key: str, value: Any) -> None:
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO kv (run_id, key, body) VALUES (?,?,?)",
                  (run_id, key, json.dumps(value, default=str)))
