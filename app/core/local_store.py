"""Local application store (SQLite).

Holds everything that makes the app "learn": tasks, the required fields per task,
document templates (saved layouts), per-template field mappings, and the learned
fuzzy-match resolutions so a description seen once is recognized forever.

This is entirely separate from the NRF_REPORTS warehouse, which is read-only.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from app.core import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_fields (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    field_key       TEXT NOT NULL,          -- machine name, e.g. customer_number
    display_name    TEXT NOT NULL,
    required        INTEGER NOT NULL DEFAULT 1,
    data_type       TEXT NOT NULL DEFAULT 'text',   -- text|number|date|money
    validation_type TEXT NOT NULL DEFAULT 'none',    -- none|exact|fuzzy
    sql_table       TEXT DEFAULT '',        -- e.g. BILLTO
    sql_value_col   TEXT DEFAULT '',        -- column returned as canonical value
    sql_match_cols  TEXT DEFAULT '',        -- JSON list of columns to match against
    description     TEXT DEFAULT '',        -- shown to the user as guidance
    order_index     INTEGER NOT NULL DEFAULT 0,
    UNIQUE(task_id, field_key)
);

CREATE TABLE IF NOT EXISTS templates (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    file_type     TEXT NOT NULL DEFAULT 'pdf',
    fingerprint   TEXT NOT NULL DEFAULT '', -- structural signature of the source layout
    sample_text   TEXT DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE(task_id, name)
);

CREATE TABLE IF NOT EXISTS field_mappings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id   INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
    field_key     TEXT NOT NULL,
    method        TEXT NOT NULL DEFAULT 'ai',   -- ai|regex|anchor|cell|fixed
    locator       TEXT NOT NULL DEFAULT '{}',   -- JSON describing how to find the value
    UNIQUE(template_id, field_key)
);

CREATE TABLE IF NOT EXISTS learned_matches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    field_key     TEXT NOT NULL,
    source_value  TEXT NOT NULL,    -- the raw value seen on documents (e.g. their description)
    resolved_value TEXT NOT NULL,   -- the confirmed canonical value (e.g. our SKU)
    resolved_label TEXT DEFAULT '', -- human-friendly label of the resolved value
    confidence    REAL NOT NULL DEFAULT 100.0,
    created_at    TEXT NOT NULL,
    UNIQUE(task_id, field_key, source_value)
);

CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    template_id   INTEGER REFERENCES templates(id) ON DELETE SET NULL,
    file_name     TEXT NOT NULL,
    file_hash     TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'new',  -- new|extracted|validated|exported|error
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    action     TEXT NOT NULL,
    detail     TEXT DEFAULT ''
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LocalStore:
    """Thin DAO over a single SQLite file. Connection-per-thread safe."""

    _lock = threading.Lock()
    _instance: "LocalStore | None" = None

    def __init__(self) -> None:
        paths.ensure_dirs()
        self._local = threading.local()
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            # Migrations: add columns that didn't exist in older schema versions
            for stmt in (
                "ALTER TABLE templates ADD COLUMN line_items_hint TEXT DEFAULT ''",
            ):
                try:
                    conn.execute(stmt)
                except Exception:  # column already exists
                    pass

    @classmethod
    def instance(cls) -> "LocalStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = LocalStore()
            return cls._instance

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(paths.LOCAL_DB_PATH)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            self._local.conn = conn
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ---------------- audit ----------------
    def audit(self, action: str, detail: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO audit_log (ts, action, detail) VALUES (?, ?, ?)",
                (_now(), action, detail),
            )

    # ---------------- tasks ----------------
    def create_task(self, name: str, description: str = "") -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO tasks (name, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (name.strip(), description.strip(), _now(), _now()),
            )
            return int(cur.lastrowid)

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY name").fetchall()
            return [dict(r) for r in rows]

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return dict(row) if row else None

    def update_task(self, task_id: int, name: str, description: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE tasks SET name = ?, description = ?, updated_at = ? WHERE id = ?",
                (name.strip(), description.strip(), _now(), task_id),
            )

    def delete_task(self, task_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    # ---------------- task fields ----------------
    def set_task_fields(self, task_id: int, fields: list[dict[str, Any]]) -> None:
        """Replace the full field set for a task."""
        with self._conn() as conn:
            conn.execute("DELETE FROM task_fields WHERE task_id = ?", (task_id,))
            for idx, f in enumerate(fields):
                conn.execute(
                    "INSERT INTO task_fields (task_id, field_key, display_name, required, "
                    "data_type, validation_type, sql_table, sql_value_col, sql_match_cols, "
                    "description, order_index) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        task_id,
                        f["field_key"].strip(),
                        f.get("display_name", f["field_key"]).strip(),
                        1 if f.get("required", True) else 0,
                        f.get("data_type", "text"),
                        f.get("validation_type", "none"),
                        f.get("sql_table", ""),
                        f.get("sql_value_col", ""),
                        json.dumps(f.get("sql_match_cols", [])),
                        f.get("description", ""),
                        idx,
                    ),
                )
            conn.execute(
                "UPDATE tasks SET updated_at = ? WHERE id = ?", (_now(), task_id)
            )

    def get_task_fields(self, task_id: int) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM task_fields WHERE task_id = ? ORDER BY order_index",
                (task_id,),
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["sql_match_cols"] = json.loads(d.get("sql_match_cols") or "[]")
                d["required"] = bool(d["required"])
                out.append(d)
            return out

    # ---------------- templates ----------------
    def upsert_template(
        self,
        task_id: int,
        name: str,
        file_type: str,
        fingerprint: str,
        sample_text: str = "",
    ) -> int:
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM templates WHERE task_id = ? AND name = ?",
                (task_id, name),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE templates SET file_type=?, fingerprint=?, sample_text=?, "
                    "updated_at=? WHERE id=?",
                    (file_type, fingerprint, sample_text, _now(), existing["id"]),
                )
                return int(existing["id"])
            cur = conn.execute(
                "INSERT INTO templates (task_id, name, file_type, fingerprint, "
                "sample_text, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (task_id, name, file_type, fingerprint, sample_text, _now(), _now()),
            )
            return int(cur.lastrowid)

    def list_templates(self, task_id: int) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM templates WHERE task_id = ? ORDER BY name", (task_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def all_templates(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM templates").fetchall()
            return [dict(r) for r in rows]

    def delete_template(self, template_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))

    def get_line_items_hint(self, template_id: int) -> str:
        """Return the saved AI line-items description hint for this template."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT line_items_hint FROM templates WHERE id = ?", (template_id,)
            ).fetchone()
            return (row["line_items_hint"] or "") if row else ""

    def save_line_items_hint(self, template_id: int, hint: str) -> None:
        """Persist a natural-language line-items extraction hint to this template."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE templates SET line_items_hint = ?, updated_at = ? WHERE id = ?",
                (hint.strip(), _now(), template_id),
            )

    # ---------------- field mappings ----------------
    def set_field_mappings(
        self, template_id: int, mappings: list[dict[str, Any]]
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM field_mappings WHERE template_id = ?", (template_id,)
            )
            for m in mappings:
                conn.execute(
                    "INSERT INTO field_mappings (template_id, field_key, method, locator) "
                    "VALUES (?,?,?,?)",
                    (
                        template_id,
                        m["field_key"],
                        m.get("method", "ai"),
                        json.dumps(m.get("locator", {})),
                    ),
                )

    def get_field_mappings(self, template_id: int) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM field_mappings WHERE template_id = ?", (template_id,)
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["locator"] = json.loads(d.get("locator") or "{}")
                out.append(d)
            return out

    # ---------------- learned matches ----------------
    def remember_match(
        self,
        task_id: int,
        field_key: str,
        source_value: str,
        resolved_value: str,
        resolved_label: str = "",
        confidence: float = 100.0,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO learned_matches (task_id, field_key, source_value, "
                "resolved_value, resolved_label, confidence, created_at) "
                "VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(task_id, field_key, source_value) DO UPDATE SET "
                "resolved_value=excluded.resolved_value, "
                "resolved_label=excluded.resolved_label, "
                "confidence=excluded.confidence",
                (
                    task_id,
                    field_key,
                    source_value.strip(),
                    resolved_value.strip(),
                    resolved_label.strip(),
                    confidence,
                    _now(),
                ),
            )

    def recall_match(
        self, task_id: int, field_key: str, source_value: str
    ) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM learned_matches WHERE task_id = ? AND field_key = ? "
                "AND source_value = ?",
                (task_id, field_key, source_value.strip()),
            ).fetchone()
            return dict(row) if row else None

    def list_learned(self, task_id: int) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM learned_matches WHERE task_id = ? "
                "ORDER BY field_key, source_value",
                (task_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def forget_match(self, match_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM learned_matches WHERE id = ?", (match_id,))

    # ---------------- documents ----------------
    def record_document(
        self,
        task_id: int | None,
        template_id: int | None,
        file_name: str,
        file_hash: str,
        status: str = "new",
    ) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO documents (task_id, template_id, file_name, file_hash, "
                "status, created_at) VALUES (?,?,?,?,?,?)",
                (task_id, template_id, file_name, file_hash, status, _now()),
            )
            return int(cur.lastrowid)

    def set_document_status(self, doc_id: int, status: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE documents SET status = ? WHERE id = ?", (status, doc_id)
            )

    def recent_documents(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
