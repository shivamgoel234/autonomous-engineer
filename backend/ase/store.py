"""Small relational persistence layer. Each operation owns its transaction."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .domain import TERMINAL


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                  created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                  request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
                  status TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
                  data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_id TEXT NOT NULL REFERENCES runs(id), kind TEXT NOT NULL,
                  message TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_run_id ON events(run_id, id);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def add_project(self, name, kind):
        item = dict(id=uuid.uuid4().hex, name=name, kind=kind, created_at=now())
        with self.connect() as db:
            db.execute("INSERT INTO projects VALUES (:id,:name,:kind,:created_at)", item)
        return item

    def projects(self):
        with self.connect() as db:
            return [
                dict(row) for row in db.execute("SELECT * FROM projects ORDER BY created_at DESC")
            ]

    def project(self, project_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(project_id)
        return dict(row)

    def create_run(self, project_id, task, key, fingerprint):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE request_key=?", (key,)).fetchone()
            if row:
                if row["fingerprint"] != fingerprint:
                    raise ValueError("Idempotency key already used for a different request.")
                return self.decode(row), False
            run_id = uuid.uuid4().hex
            data = dict(
                task=task,
                created_at=now(),
                attempt=0,
                tool_calls=0,
                input_tokens=0,
                output_tokens=0,
                elapsed_seconds=0,
                tests=[],
                diff="",
                changed_files=[],
                review=None,
                error=None,
            )
            db.execute(
                "INSERT INTO runs(id,project_id,request_key,fingerprint,status,data) "
                "VALUES (?,?,?,?,?,?)",
                (run_id, project_id, key, fingerprint, "queued", json.dumps(data)),
            )
            return dict(
                id=run_id, project_id=project_id, status="queued", cancel_requested=False, **data
            ), True

    @staticmethod
    def decode(row):
        return dict(
            id=row["id"],
            project_id=row["project_id"],
            status=row["status"],
            cancel_requested=bool(row["cancel_requested"]),
            **json.loads(row["data"]),
        )

    def run(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self.decode(row)

    def runs(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM runs ORDER BY rowid DESC LIMIT 100").fetchall()
        return [self.decode(row) for row in rows]

    def update(self, run_id, **fields):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            data = json.loads(row["data"])
            status = fields.pop("status", row["status"])
            data.update(fields)
            db.execute(
                "UPDATE runs SET status=?,data=? WHERE id=?", (status, json.dumps(data), run_id)
            )
        return self.run(run_id)

    def cancel(self, run_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            if row["status"] in TERMINAL:
                raise ValueError("Run is already terminal.")
            db.execute("UPDATE runs SET cancel_requested=1 WHERE id=?", (run_id,))
        self.event(run_id, "cancel", "Cancellation requested")

    def review(self, run_id, decision, role):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            if row["status"] != "awaiting_review":
                raise ValueError("Only a validated, unreviewed patch can be reviewed.")
            data = json.loads(row["data"])
            data["review"] = dict(decision=decision, role=role, at=now())
            db.execute(
                "UPDATE runs SET status=?,data=? WHERE id=?", (decision, json.dumps(data), run_id)
            )
        self.event(run_id, "review", f"Patch {decision} by {role}")
        return self.run(run_id)

    def event(self, run_id, kind, message, data=None):
        with self.connect() as db:
            db.execute(
                "INSERT INTO events(run_id,kind,message,data,created_at) VALUES(?,?,?,?,?)",
                (run_id, kind, message, json.dumps(data or {}), now()),
            )

    def events(self, run_id, after=0):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM events WHERE run_id=? AND id>? ORDER BY id LIMIT 100",
                (run_id, after),
            ).fetchall()
        return [{**dict(row), "data": json.loads(row["data"])} for row in rows]

    def recover(self):
        """Mark abandoned work honestly; do not replay paid model calls after a crash."""
        for run in self.runs():
            if run["status"] not in TERMINAL:
                self.update(run["id"], status="interrupted", error="Server stopped during run.")
                self.event(run["id"], "interrupted", "Interrupted run; submit a new run to retry")
