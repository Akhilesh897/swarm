import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.config import get_config


@dataclass
class LeaveResult:
    request_id: int
    approval_required: bool


def _get_conn() -> sqlite3.Connection:
    config = get_config()
    Path(config.app_db_path).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(config.app_db_path)


def init_db() -> None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS leaves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            start_date TEXT,
            end_date TEXT,
            status TEXT,
            reason TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            issue_type TEXT,
            priority TEXT,
            status TEXT,
            assigned_engineer TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_type TEXT,
            request_id INTEGER,
            status TEXT,
            approver_id TEXT,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reimbursements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            amount REAL,
            status TEXT,
            category TEXT,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            asset_type TEXT,
            status TEXT,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            session_id TEXT,
            content TEXT,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            event_type TEXT,
            detail TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def apply_leave(user_id: str, start_date: str, end_date: str, reason: str) -> LeaveResult:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO leaves (user_id, start_date, end_date, status, reason) VALUES (?, ?, ?, ?, ?)",
        (user_id, start_date, end_date, "pending", reason),
    )
    request_id = cur.lastrowid
    conn.commit()
    conn.close()

    approval_required = _leave_days(start_date, end_date) > 2
    if approval_required:
        create_approval("leave", request_id, approver_id="")

    return LeaveResult(request_id=request_id, approval_required=approval_required)


def list_leaves(user_id: str) -> list[dict]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, start_date, end_date, status, reason FROM leaves WHERE user_id = ?",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "start_date": row[1],
            "end_date": row[2],
            "status": row[3],
            "reason": row[4],
        }
        for row in rows
    ]


def get_leave_balance(user_id: str) -> int:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT start_date, end_date FROM leaves WHERE user_id = ? AND status = 'approved'",
        (user_id,),
    )
    used = sum(_leave_days(row[0], row[1]) for row in cur.fetchall())
    conn.close()
    return max(0, 12 - used)


def create_ticket(user_id: str, issue_type: str, priority: str) -> int:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tickets (user_id, issue_type, priority, status, assigned_engineer) VALUES (?, ?, ?, ?, ?)",
        (user_id, issue_type, priority, "open", ""),
    )
    ticket_id = cur.lastrowid
    conn.commit()
    conn.close()
    return ticket_id


def request_asset(user_id: str, asset_type: str) -> int:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO assets (user_id, asset_type, status, created_at) VALUES (?, ?, ?, ?)",
        (user_id, asset_type, "pending", _now()),
    )
    asset_id = cur.lastrowid
    conn.commit()
    conn.close()
    create_approval("asset", asset_id, approver_id="")
    return asset_id


def submit_reimbursement(user_id: str, amount: float, category: str) -> int:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reimbursements (user_id, amount, status, category, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, "pending", category, _now()),
    )
    reimb_id = cur.lastrowid
    conn.commit()
    conn.close()
    if amount > 5000:
        create_approval("reimbursement", reimb_id, approver_id="")
    return reimb_id


def create_approval(request_type: str, request_id: int, approver_id: str) -> int:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO approvals (request_type, request_id, status, approver_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (request_type, request_id, "pending", approver_id, _now()),
    )
    approval_id = cur.lastrowid
    conn.commit()
    conn.close()
    return approval_id


def approve_request(approval_id: int, approver_id: str, status: str) -> None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE approvals SET status = ?, approver_id = ? WHERE id = ?",
        (status, approver_id, approval_id),
    )
    conn.commit()
    conn.close()


def get_approval_status(request_type: str, request_id: int) -> str:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT status FROM approvals WHERE request_type = ? AND request_id = ? ORDER BY id DESC LIMIT 1",
        (request_type, request_id),
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else "none"


def save_memory(user_id: str, session_id: str, content: str) -> None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO memory (user_id, session_id, content, created_at) VALUES (?, ?, ?, ?)",
        (user_id, session_id, content, _now()),
    )
    conn.commit()
    conn.close()


def load_memory(user_id: str, limit: int = 10) -> list[str]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT content FROM memory WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return [row[0] for row in rows]


def log_event(user_id: str, event_type: str, detail: str) -> None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO logs (user_id, event_type, detail, created_at) VALUES (?, ?, ?, ?)",
        (user_id, event_type, detail, _now()),
    )
    conn.commit()
    conn.close()


def _leave_days(start_date: str, end_date: str) -> int:
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    return (end - start).days + 1


def _now() -> str:
    return datetime.utcnow().isoformat()
