"""SQLite repository.

Each entity is stored as a validated JSON document plus a few indexed columns.
This keeps the schema flexible for a prototype while still allowing efficient
per-workspace / per-run queries. Raw responses are append-only: there is no
update method for them by design.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, Type, TypeVar

from pydantic import BaseModel

from brandorbit.core.schemas import (
    Extraction,
    Finding,
    FindingStatus,
    MonitoringRun,
    Product,
    Prompt,
    PromptStatus,
    RawResponse,
    Workspace,
)

T = TypeVar("T", bound=BaseModel)

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, doc TEXT NOT NULL, created_at TEXT);
CREATE TABLE IF NOT EXISTS products (sku TEXT, workspace_id TEXT, doc TEXT NOT NULL, PRIMARY KEY (workspace_id, sku));
CREATE TABLE IF NOT EXISTS prompts (id TEXT PRIMARY KEY, workspace_id TEXT, status TEXT, category TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, workspace_id TEXT, started_at TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS responses (id TEXT PRIMARY KEY, run_id TEXT, prompt_id TEXT, provider TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS extractions (id TEXT PRIMARY KEY, response_id TEXT, method TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS findings (id TEXT PRIMARY KEY, workspace_id TEXT, run_id TEXT, status TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS provider_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, run_id TEXT, provider TEXT, model TEXT,
    status TEXT, latency_ms INTEGER, input_tokens INTEGER, output_tokens INTEGER, error TEXT);
CREATE INDEX IF NOT EXISTS idx_prompts_ws ON prompts(workspace_id);
CREATE INDEX IF NOT EXISTS idx_runs_ws ON runs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_resp_run ON responses(run_id);
CREATE INDEX IF NOT EXISTS idx_extr_resp ON extractions(response_id);
CREATE INDEX IF NOT EXISTS idx_find_ws ON findings(workspace_id);
"""


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Repository:
    def __init__(self, path: Path | str = ":memory:"):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def close(self) -> None:
        self._conn.close()

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _dump(m: BaseModel) -> str:
        return m.model_dump_json()

    @staticmethod
    def _load(model: Type[T], row: sqlite3.Row | None) -> Optional[T]:
        return model.model_validate_json(row["doc"]) if row else None

    def _load_all(self, model: Type[T], rows: list[sqlite3.Row]) -> list[T]:
        return [model.model_validate_json(r["doc"]) for r in rows]

    # ------------------------------------------------------------- workspaces
    def save_workspace(self, ws: Workspace) -> Workspace:
        with self._tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO workspaces (id, doc, created_at) VALUES (?,?,?)",
                (ws.id, self._dump(ws), ws.created_at.isoformat()),
            )
        return ws

    def get_workspace(self, ws_id: str) -> Optional[Workspace]:
        return self._load(Workspace, self._conn.execute("SELECT doc FROM workspaces WHERE id=?", (ws_id,)).fetchone())

    def list_workspaces(self) -> list[Workspace]:
        return self._load_all(Workspace, self._conn.execute("SELECT doc FROM workspaces ORDER BY created_at").fetchall())

    def delete_workspace(self, ws_id: str) -> None:
        run_ids = [r["id"] for r in self._conn.execute("SELECT id FROM runs WHERE workspace_id=?", (ws_id,))]
        with self._tx() as c:
            for rid in run_ids:
                resp_ids = [r["id"] for r in c.execute("SELECT id FROM responses WHERE run_id=?", (rid,))]
                for resp in resp_ids:
                    c.execute("DELETE FROM extractions WHERE response_id=?", (resp,))
                c.execute("DELETE FROM responses WHERE run_id=?", (rid,))
            for table in ("runs", "prompts", "products", "findings"):
                c.execute(f"DELETE FROM {table} WHERE workspace_id=?", (ws_id,))
            c.execute("DELETE FROM workspaces WHERE id=?", (ws_id,))

    # --------------------------------------------------------------- products
    def replace_products(self, ws_id: str, products: list[Product]) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM products WHERE workspace_id=?", (ws_id,))
            c.executemany(
                "INSERT INTO products (sku, workspace_id, doc) VALUES (?,?,?)",
                [(p.sku, ws_id, self._dump(p)) for p in products],
            )

    def list_products(self, ws_id: str) -> list[Product]:
        return self._load_all(Product, self._conn.execute("SELECT doc FROM products WHERE workspace_id=? ORDER BY sku", (ws_id,)).fetchall())

    # ---------------------------------------------------------------- prompts
    def save_prompt(self, p: Prompt) -> Prompt:
        with self._tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO prompts (id, workspace_id, status, category, doc) VALUES (?,?,?,?,?)",
                (p.id, p.workspace_id, p.status.value, p.category.value, self._dump(p)),
            )
        return p

    def save_prompts(self, prompts: list[Prompt]) -> None:
        for p in prompts:
            self.save_prompt(p)

    def get_prompt(self, prompt_id: str) -> Optional[Prompt]:
        return self._load(Prompt, self._conn.execute("SELECT doc FROM prompts WHERE id=?", (prompt_id,)).fetchone())

    def list_prompts(self, ws_id: str, status: Optional[PromptStatus] = None) -> list[Prompt]:
        if status:
            rows = self._conn.execute("SELECT doc FROM prompts WHERE workspace_id=? AND status=? ORDER BY id", (ws_id, status.value)).fetchall()
        else:
            rows = self._conn.execute("SELECT doc FROM prompts WHERE workspace_id=? ORDER BY id", (ws_id,)).fetchall()
        return self._load_all(Prompt, rows)

    def delete_prompt(self, prompt_id: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM prompts WHERE id=?", (prompt_id,))

    # ------------------------------------------------------------------- runs
    def save_run(self, run: MonitoringRun) -> MonitoringRun:
        with self._tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO runs (id, workspace_id, started_at, doc) VALUES (?,?,?,?)",
                (run.id, run.workspace_id, run.started_at.isoformat(), self._dump(run)),
            )
        return run

    def get_run(self, run_id: str) -> Optional[MonitoringRun]:
        return self._load(MonitoringRun, self._conn.execute("SELECT doc FROM runs WHERE id=?", (run_id,)).fetchone())

    def list_runs(self, ws_id: str) -> list[MonitoringRun]:
        return self._load_all(MonitoringRun, self._conn.execute("SELECT doc FROM runs WHERE workspace_id=? ORDER BY started_at", (ws_id,)).fetchall())

    def set_baseline(self, ws_id: str, run_id: str) -> None:
        for run in self.list_runs(ws_id):
            run.is_baseline = run.id == run_id
            self.save_run(run)

    # -------------------------------------------------------------- responses
    def add_response(self, r: RawResponse) -> RawResponse:
        """Append-only. Raises if the id already exists (raw answers are immutable)."""
        with self._tx() as c:
            c.execute(
                "INSERT INTO responses (id, run_id, prompt_id, provider, doc) VALUES (?,?,?,?,?)",
                (r.id, r.run_id, r.prompt_id, r.provider, self._dump(r)),
            )
        return r

    def get_response(self, resp_id: str) -> Optional[RawResponse]:
        return self._load(RawResponse, self._conn.execute("SELECT doc FROM responses WHERE id=?", (resp_id,)).fetchone())

    def list_responses(self, run_id: str) -> list[RawResponse]:
        return self._load_all(RawResponse, self._conn.execute("SELECT doc FROM responses WHERE run_id=? ORDER BY prompt_id, provider", (run_id,)).fetchall())

    def list_responses_for_prompt(self, prompt_id: str) -> list[RawResponse]:
        return self._load_all(RawResponse, self._conn.execute("SELECT doc FROM responses WHERE prompt_id=? ORDER BY id", (prompt_id,)).fetchall())

    # ------------------------------------------------------------ extractions
    def save_extraction(self, e: Extraction) -> Extraction:
        with self._tx() as c:
            c.execute("DELETE FROM extractions WHERE response_id=? AND method=?", (e.response_id, e.method))
            c.execute(
                "INSERT INTO extractions (id, response_id, method, doc) VALUES (?,?,?,?)",
                (e.id, e.response_id, e.method, self._dump(e)),
            )
        return e

    def get_extraction(self, response_id: str, method: str = "deterministic") -> Optional[Extraction]:
        return self._load(Extraction, self._conn.execute("SELECT doc FROM extractions WHERE response_id=? AND method=?", (response_id, method)).fetchone())

    def list_extractions(self, run_id: str, method: str = "deterministic") -> list[Extraction]:
        rows = self._conn.execute(
            "SELECT e.doc FROM extractions e JOIN responses r ON r.id = e.response_id WHERE r.run_id=? AND e.method=?",
            (run_id, method),
        ).fetchall()
        return self._load_all(Extraction, rows)

    # --------------------------------------------------------------- findings
    def save_finding(self, f: Finding) -> Finding:
        with self._tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO findings (id, workspace_id, run_id, status, doc) VALUES (?,?,?,?,?)",
                (f.id, f.workspace_id, f.run_id, f.status.value, self._dump(f)),
            )
        return f

    def list_findings(self, ws_id: str, run_id: Optional[str] = None) -> list[Finding]:
        if run_id:
            rows = self._conn.execute("SELECT doc FROM findings WHERE workspace_id=? AND run_id=? ORDER BY id", (ws_id, run_id)).fetchall()
        else:
            rows = self._conn.execute("SELECT doc FROM findings WHERE workspace_id=? ORDER BY id", (ws_id,)).fetchall()
        return self._load_all(Finding, rows)

    def get_finding(self, finding_pk: str) -> Optional[Finding]:
        return self._load(Finding, self._conn.execute("SELECT doc FROM findings WHERE id=?", (finding_pk,)).fetchone())

    def update_finding_status(self, finding_pk: str, status: FindingStatus) -> Optional[Finding]:
        f = self.get_finding(finding_pk)
        if not f:
            return None
        f.status = status
        return self.save_finding(f)

    def delete_findings_for_run(self, run_id: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM findings WHERE run_id=?", (run_id,))

    # ---------------------------------------------------------- provider logs
    def log_provider_call(self, run_id: str, provider: str, model: str, status: str, latency_ms: Optional[int],
                          input_tokens: Optional[int], output_tokens: Optional[int], error: Optional[str]) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO provider_logs (ts, run_id, provider, model, status, latency_ms, input_tokens, output_tokens, error) VALUES (?,?,?,?,?,?,?,?,?)",
                (datetime.utcnow().isoformat(), run_id, provider, model, status, latency_ms, input_tokens, output_tokens, error),
            )

    def list_provider_logs(self, run_id: Optional[str] = None, limit: int = 200) -> list[dict]:
        q = "SELECT * FROM provider_logs" + (" WHERE run_id=?" if run_id else "") + " ORDER BY id DESC LIMIT ?"
        args = (run_id, limit) if run_id else (limit,)
        return [dict(r) for r in self._conn.execute(q, args).fetchall()]

    # ------------------------------------------------------------ bookkeeping
    def counts(self) -> dict[str, int]:
        return {
            t: self._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            for t in ("workspaces", "prompts", "runs", "responses", "extractions", "findings")
        }

    def export_json(self, ws_id: str) -> str:
        """Export everything for a workspace (used by the report download)."""
        runs = self.list_runs(ws_id)
        payload = {
            "workspace": self.get_workspace(ws_id).model_dump(mode="json"),
            "products": [p.model_dump(mode="json") for p in self.list_products(ws_id)],
            "prompts": [p.model_dump(mode="json") for p in self.list_prompts(ws_id)],
            "runs": [r.model_dump(mode="json") for r in runs],
            "responses": [x.model_dump(mode="json") for r in runs for x in self.list_responses(r.id)],
            "extractions": [x.model_dump(mode="json") for r in runs for x in self.list_extractions(r.id)],
            "findings": [f.model_dump(mode="json") for f in self.list_findings(ws_id)],
        }
        return json.dumps(payload, indent=2)
