"""SQLite task ledger: one row per media file, restartable at any stage."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from .config import DB_PATH, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    src_path      TEXT NOT NULL UNIQUE,
    kind          TEXT NOT NULL,              -- image | video
    account       TEXT,
    is_thumb      INTEGER DEFAULT 0,
    origin        TEXT,
    size          INTEGER NOT NULL,
    mtime         REAL NOT NULL,
    md5           TEXT,
    dup_of        INTEGER,
    stage1_label  TEXT,
    stage1_scores TEXT,                       -- json {label: prob}
    stage1_src    TEXT,                       -- siglip | wd | both
    stage1_at     REAL,
    stage2_json   TEXT,                       -- json VLM verdict (model A)
    stage2_model  TEXT,
    stage2_at     REAL,
    stage2_b      TEXT,                       -- json arbitration verdict (model B)
    final_json    TEXT,                       -- json merged verdict
    needs_review  INTEGER DEFAULT 0,
    category      TEXT,
    target_path   TEXT,
    move_state    TEXT DEFAULT 'pending',     -- pending | moving | moved | kept | duplicate | skipped | error | lost | rolled_back
    stash_state   TEXT DEFAULT 'pending',     -- pending | tagged | error
    error         TEXT,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_stage1 ON files(stage1_label);
CREATE INDEX IF NOT EXISTS idx_files_move   ON files(move_state);
CREATE INDEX IF NOT EXISTS idx_files_stash  ON files(stash_state);
CREATE INDEX IF NOT EXISTS idx_files_cat    ON files(category);
CREATE INDEX IF NOT EXISTS idx_files_md5    ON files(md5);

CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    stage      TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at   REAL,
    processed  INTEGER DEFAULT 0,
    errors     INTEGER DEFAULT 0,
    params     TEXT
);

CREATE TABLE IF NOT EXISTS thumb_audit (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    path             TEXT NOT NULL UNIQUE,
    account          TEXT,
    kind             TEXT,                 -- Pic | Video
    month            TEXT,
    stem             TEXT,
    size             INTEGER,
    mtime            REAL,
    match_state      TEXT,                 -- moved | kept | orphan
    ledger_id        INTEGER,
    matched_src      TEXT,
    matched_origin   TEXT,
    matched_category TEXT,
    matched_level    TEXT,
    siglip_json      TEXT,
    siglip_label     TEXT,
    siglip_nsfw      REAL,
    best_frame       INTEGER DEFAULT 0,
    vlm_json         TEXT,
    final_level      TEXT,
    final_category   TEXT,
    state            TEXT DEFAULT 'pending', -- pending | candidate | safe_siglip | safe_vlm | exact | ready_move | moved | error | skipped
    target_path      TEXT,
    error            TEXT,
    audited_at       REAL,
    moved_at         REAL
);
CREATE INDEX IF NOT EXISTS idx_thumb_audit_state ON thumb_audit(state);
CREATE INDEX IF NOT EXISTS idx_thumb_audit_match ON thumb_audit(match_state);

CREATE TABLE IF NOT EXISTS reaudit (
    file_id        INTEGER PRIMARY KEY,
    state          TEXT DEFAULT 'pending', -- pending | safe | nsfw | error
    model          TEXT,
    verdict_json   TEXT,
    final_level    TEXT,
    final_category TEXT,
    error          TEXT,
    updated_at     REAL
);
CREATE INDEX IF NOT EXISTS idx_reaudit_state ON reaudit(state);
"""


class Ledger:
    def __init__(self, path: Path | str = DB_PATH) -> None:
        ensure_dirs()
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, timeout=90, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(files)")}
        for name, ddl in (
            ("stage2_b", "TEXT"),
            ("final_json", "TEXT"),
            ("needs_review", "INTEGER DEFAULT 0"),
            ("dup_of", "INTEGER"),
            ("origin", "TEXT"),
        ):
            if name not in cols:
                self.conn.execute(f"ALTER TABLE files ADD COLUMN {name} {ddl}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ----- ingestion -------------------------------------------------
    def upsert_file(self, path: str, kind: str, account: str, is_thumb: bool, size: int, mtime: float) -> None:
        self.upsert_many([(path, kind, account, is_thumb, size, mtime)])

    def upsert_many(self, rows: Iterable[tuple[str, str, str, bool, int, float]]) -> int:
        now = time.time()
        cur = self.conn.executemany(
            """INSERT INTO files (src_path, kind, account, is_thumb, size, mtime, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(src_path) DO UPDATE SET size=excluded.size,
                 mtime=excluded.mtime, updated_at=excluded.updated_at""",
            [(p, k, a, int(t), s, m, now, now) for p, k, a, t, s, m in rows],
        )
        self.conn.commit()
        return cur.rowcount

    # ----- stage updates ---------------------------------------------
    def set_stage1(self, src_path: str, label: str, scores: dict[str, float], src: str) -> None:
        self.conn.execute(
            "UPDATE files SET stage1_label=?, stage1_scores=?, stage1_src=?, stage1_at=?, updated_at=? WHERE src_path=?",
            (label, json.dumps(scores, ensure_ascii=False), src, time.time(), time.time(), src_path),
        )

    def set_stage2(self, src_path: str, verdict: dict[str, Any], model: str) -> None:
        self.conn.execute(
            "UPDATE files SET stage2_json=?, stage2_model=?, stage2_at=?, category=?, updated_at=? WHERE src_path=?",
            (json.dumps(verdict, ensure_ascii=False), model, time.time(),
             verdict.get("category"), time.time(), src_path),
        )

    def set_move(self, src_path: str, target: str | None, state: str, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE files SET target_path=?, move_state=?, error=?, updated_at=? WHERE src_path=?",
            (target, state, error, time.time(), src_path),
        )

    def set_stash(self, src_path: str, state: str) -> None:
        self.conn.execute(
            "UPDATE files SET stash_state=?, updated_at=? WHERE src_path=?", (state, time.time(), src_path)
        )

    def commit(self) -> None:
        self.conn.commit()

    # ----- queries ----------------------------------------------------
    def pending_stage1(self, batch: int, kind: str | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM files WHERE stage1_label IS NULL"
        args: list[Any] = []
        if kind:
            q += " AND kind=?"
            args.append(kind)
        q += " ORDER BY size ASC LIMIT ?"
        args.append(batch)
        return self.conn.execute(q, args).fetchall()

    def pending_stage2(self, batch: int, model_tag: str = "vlm") -> list[sqlite3.Row]:
        """Stage-2 candidates: videos, plus images flagged as real-person content."""
        return self.conn.execute(
            """SELECT * FROM files
               WHERE stage2_json IS NULL
                 AND (kind='video'
                      OR (kind='image' AND stage1_label IN ('Normal','Enticing or Sensual','Pornography')))
               ORDER BY (kind='video') DESC, size DESC LIMIT ?""",
            (batch,),
        ).fetchall()

    def pending_stage2_retry(self, batch: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM files WHERE stage2_json IS NULL AND error IS NOT NULL LIMIT ?", (batch,)
        ).fetchall()

    def moved_candidates(self, batch: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT * FROM files
               WHERE move_state='pending' AND category IS NOT NULL
               ORDER BY id LIMIT ?""",
            (batch,),
        ).fetchall()

    def stats(self) -> dict[str, Any]:
        c = self.conn
        out: dict[str, Any] = {}
        out["total"] = c.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        out["images"] = c.execute("SELECT COUNT(*) FROM files WHERE kind='image'").fetchone()[0]
        out["videos"] = c.execute("SELECT COUNT(*) FROM files WHERE kind='video'").fetchone()[0]
        out["stage1_done"] = c.execute("SELECT COUNT(*) FROM files WHERE stage1_label IS NOT NULL").fetchone()[0]
        out["stage2_done"] = c.execute("SELECT COUNT(*) FROM files WHERE stage2_json IS NOT NULL").fetchone()[0]
        out["finalized"] = c.execute("SELECT COUNT(*) FROM files WHERE final_json IS NOT NULL").fetchone()[0]
        out["moved"] = c.execute("SELECT COUNT(*) FROM files WHERE move_state='moved'").fetchone()[0]
        out["moving"] = c.execute("SELECT COUNT(*) FROM files WHERE move_state='moving'").fetchone()[0]
        out["kept"] = c.execute("SELECT COUNT(*) FROM files WHERE move_state='kept'").fetchone()[0]
        out["duplicates"] = c.execute("SELECT COUNT(*) FROM files WHERE move_state='duplicate'").fetchone()[0]
        out["errors"] = c.execute("SELECT COUNT(*) FROM files WHERE move_state='error'").fetchone()[0]
        out["lost"] = c.execute("SELECT COUNT(*) FROM files WHERE move_state='lost'").fetchone()[0]
        out["stash_tagged"] = c.execute("SELECT COUNT(*) FROM files WHERE stash_state='tagged'").fetchone()[0]
        out["needs_review"] = c.execute("SELECT COUNT(*) FROM files WHERE needs_review=1").fetchone()[0]
        out["stage1_labels"] = {
            r[0] or "<none>": r[1]
            for r in c.execute("SELECT stage1_label, COUNT(*) FROM files GROUP BY stage1_label")
        }
        out["categories"] = {
            r[0] or "<none>": r[1] for r in c.execute("SELECT category, COUNT(*) FROM files GROUP BY category")
        }
        return out

    def start_run(self, stage: str, params: dict[str, Any] | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (stage, started_at, params) VALUES (?,?,?)",
            (stage, time.time(), json.dumps(params or {}, ensure_ascii=False)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, processed: int, errors: int) -> None:
        self.conn.execute(
            "UPDATE runs SET ended_at=?, processed=?, errors=? WHERE id=?", (time.time(), processed, errors, run_id)
        )
        self.conn.commit()