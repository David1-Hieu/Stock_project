"""SQLite persistence for watchlist, portfolio, monitoring and AI history."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def get_db_path() -> Path:
    configured = os.getenv("STOCK_ANALYZE_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    path = PROJECT_ROOT / "data" / "stock_analyze.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _rows(rows: Iterable[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(row) for row in rows]


def init_db() -> Path:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL UNIQUE,
                note TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                added_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL UNIQUE,
                quantity REAL NOT NULL DEFAULT 0,
                avg_cost REAL NOT NULL DEFAULT 0,
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                rsi REAL,
                macd REAL,
                macd_signal REAL,
                ema20 REAL,
                ema50 REAL,
                ema200 REAL,
                technical_score REAL,
                fundamental_score REAL,
                valuation_score REAL,
                risk_score REAL,
                final_score REAL,
                is_benchmark INTEGER NOT NULL DEFAULT 0,
                captured_at TEXT NOT NULL,
                UNIQUE(symbol, trade_date)
            );

            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                analysis_date TEXT NOT NULL,
                window_sessions INTEGER NOT NULL DEFAULT 5,
                action TEXT NOT NULL,
                confidence TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(symbol, analysis_date, window_sessions)
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                page TEXT DEFAULT '',
                symbol TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )
    return path


# ---------- Watchlist ----------
def get_watchlist() -> List[Dict[str, Any]]:
    init_db()
    with _db() as conn:
        rows = conn.execute("SELECT * FROM watchlist ORDER BY added_at DESC, symbol").fetchall()
    return _rows(rows)


def add_watchlist(symbol: str, note: str = "") -> Dict[str, Any]:
    init_db()
    symbol = symbol.upper().strip()
    now = _now()
    with _db() as conn:
        conn.execute(
            """INSERT INTO watchlist(symbol, note, status, added_at)
               VALUES(?, ?, 'ACTIVE', ?)
               ON CONFLICT(symbol) DO UPDATE SET note=excluded.note, status='ACTIVE'""",
            (symbol, note.strip(), now),
        )
        row = conn.execute("SELECT * FROM watchlist WHERE symbol=?", (symbol,)).fetchone()
    return dict(row) if row else {"symbol": symbol}


def remove_watchlist(symbol: str) -> bool:
    init_db()
    with _db() as conn:
        cur = conn.execute("DELETE FROM watchlist WHERE symbol=?", (symbol.upper().strip(),))
    return cur.rowcount > 0


# ---------- Portfolio ----------
def get_holdings() -> List[Dict[str, Any]]:
    """Return holdings enriched with the latest persisted market price when available.

    This shape is intentionally compatible with the legacy ``ai_routes`` portfolio
    loader, which looks for ``current_price`` and ``pl_percent``.
    """
    init_db()
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT h.*,
                   s.close AS current_price,
                   s.trade_date AS price_date
            FROM holdings h
            LEFT JOIN daily_snapshots s
              ON s.id = (
                SELECT s2.id FROM daily_snapshots s2
                WHERE s2.symbol = h.symbol
                ORDER BY s2.trade_date DESC, s2.id DESC LIMIT 1
              )
            ORDER BY h.symbol
            """
        ).fetchall()
    result = _rows(rows)
    for item in result:
        avg = item.get("avg_cost") or 0
        current = item.get("current_price")
        item["pl_percent"] = ((current / avg - 1) * 100) if current is not None and avg else None
    return result


def get_all_holdings() -> List[Dict[str, Any]]:
    return get_holdings()


def get_portfolio() -> List[Dict[str, Any]]:
    return get_holdings()


def upsert_holding(symbol: str, quantity: float, avg_cost: float, note: str = "") -> Dict[str, Any]:
    init_db()
    symbol = symbol.upper().strip()
    now = _now()
    with _db() as conn:
        conn.execute(
            """INSERT INTO holdings(symbol, quantity, avg_cost, note, created_at, updated_at)
               VALUES(?, ?, ?, ?, ?, ?)
               ON CONFLICT(symbol) DO UPDATE SET
                 quantity=excluded.quantity,
                 avg_cost=excluded.avg_cost,
                 note=excluded.note,
                 updated_at=excluded.updated_at""",
            (symbol, float(quantity), float(avg_cost), note.strip(), now, now),
        )
        row = conn.execute("SELECT * FROM holdings WHERE symbol=?", (symbol,)).fetchone()
    return dict(row) if row else {"symbol": symbol}


def remove_holding(symbol: str) -> bool:
    init_db()
    with _db() as conn:
        cur = conn.execute("DELETE FROM holdings WHERE symbol=?", (symbol.upper().strip(),))
    return cur.rowcount > 0


# ---------- Daily snapshots ----------
def upsert_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    init_db()
    fields = [
        "symbol", "trade_date", "open", "high", "low", "close", "volume",
        "rsi", "macd", "macd_signal", "ema20", "ema50", "ema200",
        "technical_score", "fundamental_score", "valuation_score", "risk_score", "final_score",
        "is_benchmark", "captured_at",
    ]
    values = [snapshot.get(k) for k in fields]
    placeholders = ",".join("?" for _ in fields)
    updates = ",".join(f"{k}=excluded.{k}" for k in fields[2:])
    with _db() as conn:
        conn.execute(
            f"""INSERT INTO daily_snapshots({','.join(fields)}) VALUES({placeholders})
                ON CONFLICT(symbol, trade_date) DO UPDATE SET {updates}""",
            values,
        )
        row = conn.execute(
            "SELECT * FROM daily_snapshots WHERE symbol=? AND trade_date=?",
            (snapshot.get("symbol"), snapshot.get("trade_date")),
        ).fetchone()
    return dict(row) if row else snapshot


def get_snapshots(symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
    init_db()
    with _db() as conn:
        rows = conn.execute(
            """SELECT * FROM daily_snapshots WHERE symbol=?
               ORDER BY trade_date DESC LIMIT ?""",
            (symbol.upper().strip(), int(limit)),
        ).fetchall()
    return list(reversed(_rows(rows)))


def get_latest_snapshot(symbol: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM daily_snapshots WHERE symbol=? ORDER BY trade_date DESC LIMIT 1",
            (symbol.upper().strip(),),
        ).fetchone()
    return dict(row) if row else None


# ---------- Recommendations ----------
def save_recommendation(payload: Dict[str, Any]) -> Dict[str, Any]:
    init_db()
    symbol = str(payload.get("symbol", "")).upper().strip()
    analysis_date = str(payload.get("analysis_date") or payload.get("end_date") or "")
    window = int(payload.get("window_sessions", 5))
    action = str(payload.get("system_action") or payload.get("action") or "WATCH")
    confidence = str(payload.get("confidence") or "LOW")
    now = _now()
    serialized = json.dumps(payload, ensure_ascii=False)
    with _db() as conn:
        conn.execute(
            """INSERT INTO recommendations(symbol, analysis_date, window_sessions, action, confidence, payload_json, created_at)
               VALUES(?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(symbol, analysis_date, window_sessions) DO UPDATE SET
                 action=excluded.action,
                 confidence=excluded.confidence,
                 payload_json=excluded.payload_json,
                 created_at=excluded.created_at""",
            (symbol, analysis_date, window, action, confidence, serialized, now),
        )
        row = conn.execute(
            """SELECT * FROM recommendations
               WHERE symbol=? AND analysis_date=? AND window_sessions=?""",
            (symbol, analysis_date, window),
        ).fetchone()
    result = dict(row) if row else {}
    result["payload"] = payload
    result.pop("payload_json", None)
    return result


def get_latest_recommendation(symbol: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM recommendations WHERE symbol=? ORDER BY analysis_date DESC, id DESC LIMIT 1",
            (symbol.upper().strip(),),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    try:
        result["payload"] = json.loads(result.pop("payload_json"))
    except Exception:
        result["payload"] = {}
    return result


def list_recommendations(limit: int = 50) -> List[Dict[str, Any]]:
    init_db()
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM recommendations ORDER BY analysis_date DESC, id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    results: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json"))
        except Exception:
            item["payload"] = {}
        results.append(item)
    return results


# ---------- Chat history ----------
def append_chat(role: str, content: str, page: str = "", symbol: str = "") -> None:
    init_db()
    with _db() as conn:
        conn.execute(
            "INSERT INTO chat_history(role, content, page, symbol, created_at) VALUES(?,?,?,?,?)",
            (role, content, page, symbol.upper().strip(), _now()),
        )


def get_recent_chat(limit: int = 8) -> List[Dict[str, Any]]:
    init_db()
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_history ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return list(reversed(_rows(rows)))
