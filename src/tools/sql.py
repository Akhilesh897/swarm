import logging
import sqlite3
import hashlib
import secrets
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from src.config import get_config

logger = logging.getLogger(__name__)
PASSWORD_HASH_ITERATIONS = 260_000


@dataclass
class LeaveResult:
    request_id: int
    approval_required: bool
    status: str
    detail: str | None = None


@dataclass
class TicketResult:
    ticket_id: int | None
    status: str
    detail: str
    matched_record: dict | None = None


@dataclass
class AssetRequestResult:
    asset_id: int
    approval_id: int
    status: str
    approval_stage: str


@dataclass
class AssetApprovalUpdate:
    asset_id: int
    approval_id: int
    status: str
    approval_stage: str
    next_stage: str | None
    next_approval_id: int | None = None
    detail: str | None = None


ASSET_APPROVAL_STAGES = [
    "manager_approval",
    "it_lead_approval",
    "inventory_validation",
    "fulfillment",
]


def _get_conn() -> sqlite3.Connection: 
    config = get_config()
    Path(config.app_db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.app_db_path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn



def init_db() -> None:
    conn = _get_conn()
    
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL,
            department TEXT,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS leaves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            leave_type TEXT,
            start_date TEXT,
            end_date TEXT,
            status TEXT,
            reason TEXT,
            created_at TEXT
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
            assigned_engineer TEXT,
            detail TEXT,
            created_at TEXT,
            resolved_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS maintenance_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_type TEXT,
            title TEXT,
            starts_at TEXT,
            ends_at TEXT,
            status TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS known_outages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_type TEXT,
            title TEXT,
            status TEXT,
            started_at TEXT,
            updated_at TEXT
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
            approval_stage TEXT,
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
            created_at TEXT,
            approval_stage TEXT,
            fulfilled_by TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_type TEXT,
            quantity INTEGER,
            updated_at TEXT
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
    _migrate_approvals(cur)
    _ensure_approval_columns(cur)
    _ensure_leave_columns(cur)
    _ensure_ticket_columns(cur)
    _ensure_asset_columns(cur)
    _seed_default_users(cur)
    _seed_it_reference_data(cur)
    conn.commit()
    conn.close()


def get_user_by_email(email: str) -> dict | None:
    normalized = email.lower().strip()
    if not normalized:
        return None
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT user_id, email, role, department, password_hash
        FROM users
        WHERE email = ?
        LIMIT 1
        """,
        (normalized,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "user_id": row[0],
        "email": row[1],
        "role": row[2],
        "department": row[3],
        "password_hash": row[4],
    }


def create_user(user_id: str, email: str, role: str, password: str, department: str | None = None) -> dict:
    normalized_email = email.lower().strip()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (user_id, email, role, department, password_hash, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, normalized_email, role, department, _hash_password(password), _now()),
    )
    conn.commit()
    conn.close()
    return {
        "user_id": user_id,
        "email": normalized_email,
        "role": role,
        "department": department,
    }


def apply_leave(user_id: str, start_date: str, end_date: str, reason: str, leave_type: str = "general") -> LeaveResult:
    conn = _get_conn()
    cur = conn.cursor()
    status, detail = _validate_leave_dates(cur, user_id, start_date, end_date)
    created_at = _now()
    cur.execute(
        "INSERT INTO leaves (user_id, leave_type, start_date, end_date, status, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, leave_type, start_date, end_date, status, reason, created_at),
    )
    request_id = cur.lastrowid
    conn.commit()
    conn.close()

    approval_required = status == "pending"
    if approval_required:
        create_approval("leave", request_id, approver_id="")

    return LeaveResult(
        request_id=request_id,
        approval_required=approval_required,
        status=status,
        detail=detail,
    )


def list_leaves(user_id: str, status: str | None = None) -> list[dict]:
    conn = _get_conn()
    cur = conn.cursor()
    if status:
        cur.execute(
            "SELECT id, leave_type, start_date, end_date, status, reason FROM leaves WHERE user_id = ? AND status = ?",
            (user_id, status),
        )
    else:
        cur.execute(
            "SELECT id, leave_type, start_date, end_date, status, reason FROM leaves WHERE user_id = ?",
            (user_id,),
        )
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "leave_type": row[1],
            "start_date": row[2],
            "end_date": row[3],
            "status": row[4],
            "reason": row[5],
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


def cancel_leave(user_id: str, request_id: int) -> str:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT status FROM leaves WHERE id = ? AND user_id = ?",
        (request_id, user_id),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return "not_found"
    status = row[0]
    if status not in {"pending", "approved"}:
        conn.close()
        return status
    cur.execute(
        "UPDATE leaves SET status = 'canceled' WHERE id = ? AND user_id = ?",
        (request_id, user_id),
    )
    conn.commit()
    conn.close()
    return "canceled"


def create_ticket(user_id: str, issue_type: str, priority: str, detail: str = "") -> int:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO tickets (user_id, issue_type, priority, status, assigned_engineer, detail, created_at, resolved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, issue_type, priority, "open", "", detail, _now(), ""),
    )
    ticket_id = cur.lastrowid
    conn.commit()
    conn.close()
    return ticket_id


def create_it_ticket_with_checks(user_id: str, issue_type: str, priority: str, detail: str = "") -> TicketResult:
    duplicate = find_duplicate_open_ticket(user_id, issue_type)
    if duplicate:
        return TicketResult(
            ticket_id=duplicate["id"],
            status="duplicate",
            detail=f"You already have open ticket {duplicate['id']} for {issue_type}.",
            matched_record=duplicate,
        )

    outage = find_known_outage(issue_type)
    if outage:
        return TicketResult(
            ticket_id=None,
            status="known_outage",
            detail=f"This looks related to a known outage: {outage['title']}. IT is already working on it.",
            matched_record=outage,
        )

    maintenance = find_active_maintenance(issue_type)
    if maintenance:
        return TicketResult(
            ticket_id=None,
            status="planned_maintenance",
            detail=f"This may be due to planned maintenance: {maintenance['title']} until {maintenance['ends_at']}.",
            matched_record=maintenance,
        )

    ticket_id = create_ticket(user_id, issue_type, priority, detail=detail)
    return TicketResult(ticket_id=ticket_id, status="created", detail=f"Ticket {ticket_id} created for {issue_type}.")


def find_duplicate_open_ticket(user_id: str, issue_type: str) -> dict | None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, user_id, issue_type, priority, status, assigned_engineer, detail
        FROM tickets
        WHERE user_id = ? AND issue_type = ? AND status IN ('open', 'assigned')
        ORDER BY id DESC LIMIT 1
        """,
        (user_id, issue_type),
    )
    row = cur.fetchone()
    conn.close()
    return _ticket_row(row) if row else None


def find_known_outage(issue_type: str) -> dict | None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, issue_type, title, status, started_at, updated_at
        FROM known_outages
        WHERE issue_type = ? AND status = 'active'
        ORDER BY id DESC LIMIT 1
        """,
        (issue_type,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "issue_type": row[1], "title": row[2], "status": row[3], "started_at": row[4], "updated_at": row[5]}


def find_active_maintenance(issue_type: str) -> dict | None:
    now = _now()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, issue_type, title, starts_at, ends_at, status
        FROM maintenance_windows
        WHERE issue_type = ? AND status = 'active' AND starts_at <= ? AND ends_at >= ?
        ORDER BY id DESC LIMIT 1
        """,
        (issue_type, now, now),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "issue_type": row[1], "title": row[2], "starts_at": row[3], "ends_at": row[4], "status": row[5]}


def list_tickets(user_id: str, role: str, status: str | None = None) -> list[dict]:
    conn = _get_conn()
    cur = conn.cursor()
    params: list[str] = []
    where = []
    if role not in {"manager", "it", "it_lead", "admin"}:
        where.append("user_id = ?")
        params.append(user_id)
    if status:
        where.append("status = ?")
        params.append(status)
    query = "SELECT id, user_id, issue_type, priority, status, assigned_engineer, detail FROM tickets"
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY id DESC"
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return [_ticket_row(row) for row in rows]


def assign_ticket(ticket_id: int, engineer_id: str) -> str:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM tickets WHERE id = ?", (ticket_id,))
    if not cur.fetchone():
        conn.close()
        return "not_found"
    cur.execute(
        "UPDATE tickets SET assigned_engineer = ?, status = 'assigned' WHERE id = ?",
        (engineer_id, ticket_id),
    )
    conn.commit()
    conn.close()
    return "assigned"


def resolve_ticket(ticket_id: int, engineer_id: str) -> str:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM tickets WHERE id = ?", (ticket_id,))
    if not cur.fetchone():
        conn.close()
        return "not_found"
    cur.execute(
        "UPDATE tickets SET assigned_engineer = COALESCE(NULLIF(assigned_engineer, ''), ?), status = 'resolved', resolved_at = ? WHERE id = ?",
        (engineer_id, _now(), ticket_id),
    )
    conn.commit()
    conn.close()
    return "resolved"


def request_asset(user_id: str, asset_type: str) -> AssetRequestResult:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO assets (user_id, asset_type, status, created_at, approval_stage, fulfilled_by) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, asset_type, "pending_manager_approval", _now(), "manager_approval", ""),
    )
    asset_id = cur.lastrowid
    conn.commit()
    conn.close()
    approval_id = create_approval("asset", asset_id, approver_id="", approval_stage="manager_approval")
    return AssetRequestResult(
        asset_id=asset_id,
        approval_id=approval_id,
        status="pending_manager_approval",
        approval_stage="manager_approval",
    )


def list_assets(user_id: str, role: str) -> list[dict]:
    conn = _get_conn()
    cur = conn.cursor()
    if role in {"manager", "it", "it_lead", "admin"}:
        cur.execute("SELECT id, user_id, asset_type, status, approval_stage, fulfilled_by FROM assets ORDER BY id DESC")
    else:
        cur.execute(
            "SELECT id, user_id, asset_type, status, approval_stage, fulfilled_by FROM assets WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "user_id": row[1],
            "asset_type": row[2],
            "status": row[3],
            "approval_stage": row[4],
            "fulfilled_by": row[5],
        }
        for row in rows
    ]


def get_inventory() -> list[dict]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT asset_type, quantity, updated_at FROM inventory ORDER BY asset_type")
    rows = cur.fetchall()
    conn.close()
    return [{"asset_type": row[0], "quantity": row[1], "updated_at": row[2]} for row in rows]


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


def create_approval(request_type: str, request_id: int, approver_id: str, approval_stage: str = "") -> int:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO approvals (request_type, request_id, status, approver_id, approval_stage, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (request_type, request_id, "pending", approver_id, approval_stage, _now()),
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
    cur.execute(
        "SELECT request_type, request_id FROM approvals WHERE id = ?",
        (approval_id,),
    )
    row = cur.fetchone()
    if row and row[0] == "leave":
        cur.execute(
            "UPDATE leaves SET status = ? WHERE id = ?",
            ("approved" if status == "approved" else "rejected", row[1]),
        )
    conn.commit()
    conn.close()


def update_asset_approval(
    approval_id: int,
    asset_id: int,
    approval_stage: str,
    approver_id: str,
    status: str,
    fulfilled_by: str | None = None,
) -> AssetApprovalUpdate:
    normalized_status = "approved" if status == "approved" else "rejected"
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT request_type, request_id, status, approver_id, approval_stage FROM approvals WHERE id = ?",
        (approval_id,),
    )
    approval_row = cur.fetchone()
    if not approval_row:
        conn.close()
        return AssetApprovalUpdate(
            asset_id=asset_id,
            approval_id=approval_id,
            status="invalid",
            approval_stage=approval_stage,
            next_stage=None,
            next_approval_id=None,
            detail="approval_not_found",
        )
    request_type, request_id, approval_status, existing_approver, stored_stage = approval_row
    if request_type != "asset" or request_id != asset_id:
        conn.close()
        return AssetApprovalUpdate(
            asset_id=asset_id,
            approval_id=approval_id,
            status="invalid",
            approval_stage=approval_stage,
            next_stage=None,
            next_approval_id=None,
            detail="approval_asset_mismatch",
        )
    if approval_status != "pending":
        conn.close()
        return AssetApprovalUpdate(
            asset_id=asset_id,
            approval_id=approval_id,
            status=approval_status,
            approval_stage=approval_stage,
            next_stage=None,
            next_approval_id=None,
            detail="approval_not_pending",
        )
    if stored_stage and stored_stage != approval_stage:
        conn.close()
        return AssetApprovalUpdate(
            asset_id=asset_id,
            approval_id=approval_id,
            status="invalid",
            approval_stage=approval_stage,
            next_stage=None,
            next_approval_id=None,
            detail="approval_stage_mismatch",
        )
    if existing_approver:
        conn.close()
        return AssetApprovalUpdate(
            asset_id=asset_id,
            approval_id=approval_id,
            status="invalid",
            approval_stage=approval_stage,
            next_stage=None,
            next_approval_id=None,
            detail="approval_already_actioned",
        )
    cur.execute(
        "SELECT asset_type, approval_stage FROM assets WHERE id = ?",
        (asset_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return AssetApprovalUpdate(
            asset_id=asset_id,
            approval_id=approval_id,
            status=normalized_status,
            approval_stage=approval_stage,
            next_stage=None,
            next_approval_id=None,
            detail="asset_not_found",
        )

    asset_type, current_stage = row[0], row[1]
    if current_stage and current_stage != approval_stage:
        conn.close()
        return AssetApprovalUpdate(
            asset_id=asset_id,
            approval_id=approval_id,
            status="invalid",
            approval_stage=approval_stage,
            next_stage=None,
            next_approval_id=None,
            detail="asset_stage_mismatch",
        )
    cur.execute(
        "UPDATE approvals SET status = ?, approver_id = ? WHERE id = ?",
        (normalized_status, approver_id, approval_id),
    )
    if normalized_status != "approved":
        cur.execute(
            "UPDATE assets SET status = 'rejected', approval_stage = 'rejected' WHERE id = ?",
            (asset_id,),
        )
        conn.commit()
        conn.close()
        return AssetApprovalUpdate(
            asset_id=asset_id,
            approval_id=approval_id,
            status=normalized_status,
            approval_stage=approval_stage,
            next_stage=None,
            next_approval_id=None,
            detail="rejected",
        )

    next_stage = _next_asset_stage(approval_stage)
    if approval_stage == "inventory_validation":
        if not _inventory_available(cur, asset_type):
            cur.execute(
                "UPDATE assets SET status = 'blocked_inventory', approval_stage = ? WHERE id = ?",
                (approval_stage, asset_id),
            )
            conn.commit()
            conn.close()
            return AssetApprovalUpdate(
                asset_id=asset_id,
                approval_id=approval_id,
                status=normalized_status,
                approval_stage=approval_stage,
                next_stage=None,
                next_approval_id=None,
                detail="inventory_unavailable",
            )

    if next_stage:
        cur.execute(
            "UPDATE assets SET status = ?, approval_stage = ? WHERE id = ?",
            (_asset_status_for_stage(next_stage), next_stage, asset_id),
        )
        conn.commit()
        conn.close()
        next_approval_id = create_approval("asset", asset_id, approver_id="", approval_stage=next_stage)
        if approval_stage == "it_lead_approval" and next_stage == "inventory_validation":
            auto_detail = _auto_inventory_validation(asset_id, next_approval_id)
            return AssetApprovalUpdate(
                asset_id=asset_id,
                approval_id=approval_id,
                status=normalized_status,
                approval_stage=current_stage,
                next_stage=next_stage,
                next_approval_id=next_approval_id,
                detail=auto_detail,
            )
        return AssetApprovalUpdate(
            asset_id=asset_id,
            approval_id=approval_id,
            status=normalized_status,
            approval_stage=current_stage,
            next_stage=next_stage,
            next_approval_id=next_approval_id,
            detail="advanced",
        )

    fulfilled_by_value = fulfilled_by or approver_id
    cur.execute(
        "UPDATE assets SET status = 'fulfilled', approval_stage = 'fulfilled', fulfilled_by = ? WHERE id = ?",
        (fulfilled_by_value, asset_id),
    )
    _decrement_inventory(cur, asset_type, 1)
    conn.commit()
    conn.close()
    return AssetApprovalUpdate(
        asset_id=asset_id,
        approval_id=approval_id,
        status=normalized_status,
        approval_stage="fulfilled",
        next_stage=None,
        next_approval_id=None,
        detail="fulfilled",
    )


def update_leave_status(request_id: int, approver_id: str, status: str) -> None:
    normalized_status = "approved" if status == "approved" else "rejected"
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE leaves SET status = ? WHERE id = ?",
        (normalized_status, request_id),
    )
    cur.execute(
        """
        UPDATE approvals
        SET status = ?, approver_id = ?
        WHERE id = (
            SELECT id FROM approvals
            WHERE request_type = 'leave' AND request_id = ?
            ORDER BY id DESC
            LIMIT 1
        )
        """,
        (normalized_status, approver_id, request_id),
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


def _leave_days(start_date: str, end_date: str) -> int:
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    return (end - start).days + 1


def _validate_leave_dates(cur: sqlite3.Cursor, user_id: str, start_date: str, end_date: str) -> tuple[str, str | None]:
    import logging
    try:
        start = datetime.fromisoformat(start_date).date()
        end = datetime.fromisoformat(end_date).date()
    except ValueError:
        return "rejected", "Invalid date format."

    if start > end:
        return "rejected", "Start date must be before end date."
    if start < date.today():
        return "rejected", "Start date cannot be in the past."

    cur.execute(
        "SELECT start_date, end_date, status FROM leaves WHERE user_id = ? AND status IN ('pending', 'approved')",
        (user_id,),
    )
    for row in cur.fetchall():
        existing_start = datetime.fromisoformat(row[0]).date()
        existing_end = datetime.fromisoformat(row[1]).date()
        if _ranges_overlap(start, end, existing_start, existing_end):
            logging.info(f"[OVERLAP VALIDATION] Found overlap between requested {start}-{end} and existing {existing_start}-{existing_end}")
            return "rejected", "Leave dates overlap an existing request."

    logging.info(f"[OVERLAP VALIDATION] Dates {start}-{end} are clean. No overlaps found.")
    return "pending", None


def _ranges_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end


def _migrate_approvals(cur: sqlite3.Cursor) -> None:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='approvlals'")
    if not cur.fetchone():
        return
    cur.execute("SELECT COUNT(*) FROM approvals")
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO approvals (request_type, request_id, status, approver_id, created_at) "
            "SELECT request_type, request_id, status, approver_id, created_at FROM approvlals"
        )


def _ensure_approval_columns(cur: sqlite3.Cursor) -> None:
    cur.execute("PRAGMA table_info(approvals)")
    columns = {row[1] for row in cur.fetchall()}
    if "approval_stage" not in columns:
        cur.execute("ALTER TABLE approvals ADD COLUMN approval_stage TEXT")


def _ensure_leave_columns(cur: sqlite3.Cursor) -> None:
    cur.execute("PRAGMA table_info(leaves)")
    columns = {row[1] for row in cur.fetchall()}
    if "leave_type" not in columns:
        cur.execute("ALTER TABLE leaves ADD COLUMN leave_type TEXT")
    if "created_at" not in columns:
        cur.execute("ALTER TABLE leaves ADD COLUMN created_at TEXT")


def _ensure_ticket_columns(cur: sqlite3.Cursor) -> None:
    cur.execute("PRAGMA table_info(tickets)")
    columns = {row[1] for row in cur.fetchall()}
    if "detail" not in columns:
        cur.execute("ALTER TABLE tickets ADD COLUMN detail TEXT")
    if "created_at" not in columns:
        cur.execute("ALTER TABLE tickets ADD COLUMN created_at TEXT")
    if "resolved_at" not in columns:
        cur.execute("ALTER TABLE tickets ADD COLUMN resolved_at TEXT")


def _ensure_asset_columns(cur: sqlite3.Cursor) -> None:
    cur.execute("PRAGMA table_info(assets)")
    columns = {row[1] for row in cur.fetchall()}
    if "approval_stage" not in columns:
        cur.execute("ALTER TABLE assets ADD COLUMN approval_stage TEXT")
    if "fulfilled_by" not in columns:
        cur.execute("ALTER TABLE assets ADD COLUMN fulfilled_by TEXT")


def _next_asset_stage(stage: str) -> str | None:
    if stage not in ASSET_APPROVAL_STAGES:
        return None
    index = ASSET_APPROVAL_STAGES.index(stage) + 1
    if index >= len(ASSET_APPROVAL_STAGES):
        return None
    return ASSET_APPROVAL_STAGES[index]


def _asset_status_for_stage(stage: str) -> str:
    return f"pending_{stage}"


def _inventory_available(cur: sqlite3.Cursor, asset_type: str) -> bool:
    min_stock = get_config().inventory_min_stock
    cur.execute("SELECT quantity FROM inventory WHERE asset_type = ?", (asset_type,))
    row = cur.fetchone()
    return bool(row and row[0] >= min_stock)


def _decrement_inventory(cur: sqlite3.Cursor, asset_type: str, amount: int) -> None:
    cur.execute("SELECT quantity FROM inventory WHERE asset_type = ?", (asset_type,))
    row = cur.fetchone()
    if not row:
        return
    quantity = max(0, row[0] - amount)
    cur.execute(
        "UPDATE inventory SET quantity = ?, updated_at = ? WHERE asset_type = ?",
        (quantity, _now(), asset_type),
    )


def _auto_inventory_validation(asset_id: int, approval_id: int) -> str:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT asset_type FROM assets WHERE id = ?", (asset_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return "auto_inventory_asset_not_found"
    asset_type = row[0]
    stock_ok = _inventory_available(cur, asset_type)
    conn.close()

    logger.info("[Inventory] asset=%s type=%s stock_ok=%s", asset_id, asset_type, stock_ok)
    status = "approved" if stock_ok else "rejected"
    result = update_asset_approval(
        approval_id=approval_id,
        asset_id=asset_id,
        approval_stage="inventory_validation",
        approver_id="system",
        status=status,
    )
    if status == "approved" and result.next_stage == "fulfillment" and result.next_approval_id:
        update_asset_approval(
            approval_id=result.next_approval_id,
            asset_id=asset_id,
            approval_stage="fulfillment",
            approver_id="system",
            status="approved",
            fulfilled_by="IT_TEAM",
        )
        return "auto_inventory_fulfilled"
    if status == "approved":
        return "auto_inventory_approved"
    return "auto_inventory_rejected"


def _seed_it_reference_data(cur: sqlite3.Cursor) -> None:
    cur.execute("SELECT COUNT(*) FROM maintenance_windows")
    if cur.fetchone()[0] == 0:
        cur.execute(
            """
            INSERT INTO maintenance_windows (issue_type, title, starts_at, ends_at, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("vpn", "VPN gateway maintenance", "2026-01-01T00:00:00", "2026-01-01T02:00:00", "completed"),
        )

    cur.execute("SELECT COUNT(*) FROM known_outages")
    if cur.fetchone()[0] == 0:
        cur.execute(
            """
            INSERT INTO known_outages (issue_type, title, status, started_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("email", "Outlook delayed delivery advisory", "resolved", _now(), _now()),
        )

    cur.execute("SELECT COUNT(*) FROM inventory")
    if cur.fetchone()[0] == 0:
        now = _now()
        for asset_type, quantity in [
            ("laptop", 5),
            ("monitor", 8),
            ("keyboard", 12),
            ("mouse", 12),
            ("vpn token", 4),
            ("software license", 10),
        ]:
            cur.execute(
                "INSERT INTO inventory (asset_type, quantity, updated_at) VALUES (?, ?, ?)",
                (asset_type, quantity, now),
            )


def _seed_default_users(cur: sqlite3.Cursor) -> None:
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] > 0:
        return

    now = _now()
    users = [
        ("emp001", "employee@company.com", "employee", "hr", "ChangeMe123!"),
        ("mgr001", "manager@company.com", "manager", "operations", "ChangeMe123!"),
        ("it001", "itlead@company.com", "it_lead", "it", "ChangeMe123!"),
    ]
    for user_id, email, role, department, plain_password in users:
        cur.execute(
            """
            INSERT INTO users (user_id, email, role, department, password_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, email, role, department, _hash_password(plain_password), now),
        )


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_HASH_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${digest}"


def _ticket_row(row: tuple) -> dict:
    return {
        "id": row[0],
        "user_id": row[1],
        "issue_type": row[2],
        "priority": row[3],
        "status": row[4],
        "assigned_engineer": row[5],
        "detail": row[6],
    }


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


def _now() -> str:
    return datetime.utcnow().isoformat()
