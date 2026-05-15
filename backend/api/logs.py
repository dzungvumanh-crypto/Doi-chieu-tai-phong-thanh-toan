"""Log viewer API — chỉ dành cho Admin"""
import io
import os
import re
import sqlite3
import tempfile
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from backend.database import get_db
from backend.core.config import settings
from backend.core.deps import require_admin, require_admin_or_gd

router = APIRouter()

_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "logs", "app.log",
)

_LOG_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\w+)\s+(\S+)\s+—\s+(.*)$"
)


def _parse_log_file(level_filter: str = "", limit: int = 200, offset: int = 0):
    if not os.path.exists(_LOG_PATH):
        return [], 0

    with open(_LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    parsed = []
    current = None
    for line in lines:
        m = _LOG_RE.match(line.rstrip())
        if m:
            if current:
                parsed.append(current)
            ts, level, logger, msg = m.groups()
            current = {"ts": ts, "level": level.upper(), "logger": logger, "msg": msg}
        else:
            stripped = line.strip()
            if current and stripped:
                current["msg"] += "\n" + stripped

    if current:
        parsed.append(current)

    parsed.reverse()

    if level_filter and level_filter.upper() not in ("ALL", ""):
        parsed = [e for e in parsed if e["level"] == level_filter.upper()]

    total = len(parsed)
    return parsed[offset: offset + limit], total


@router.get("/backup-info")
def get_backup_info(_: dict = Depends(require_admin_or_gd)):
    from backend.services.backup_service import last_backup_info
    return last_backup_info()


@router.get("/backup")
def backup_db(_: dict = Depends(require_admin_or_gd)):
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    if not os.path.exists(db_path):
        from fastapi import HTTPException
        raise HTTPException(404, "Không tìm thấy file database")

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(tmp_fd)
    try:
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(tmp_path)
        src.backup(dst)
        dst.close()
        src.close()
        with open(tmp_path, "rb") as f:
            data = f.read()
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ksnb_backup_{stamp}.db"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/logins")
def get_login_logs(
    limit:   int = Query(200, ge=1, le=1000),
    offset:  int = Query(0, ge=0),
    success: str = Query(""),
    _: dict = Depends(require_admin_or_gd),
    db: sqlite3.Connection = Depends(get_db),
):
    clauses = []
    params: list = []
    if success == "true":
        clauses.append("ll.success = 1")
    elif success == "false":
        clauses.append("ll.success = 0")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""

    total = db.execute(
        f"SELECT COUNT(*) FROM login_logs ll {where}", params
    ).fetchone()[0]

    rows = db.execute(
        f"""SELECT ll.*, ks.full_name
            FROM login_logs ll
            LEFT JOIN ksnb_staff ks ON ll.staff_id = ks.id
            {where}
            ORDER BY ll.created_at DESC
            LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()

    return {
        "entries": [
            {
                "id":         r["id"],
                "username":   r["username"],
                "full_name":  r["full_name"],
                "ip_address": r["ip_address"],
                "success":    bool(r["success"]),
                "detail":     r["detail"],
                "created_at": r["created_at"],
            }
            for r in rows
        ],
        "total": total, "limit": limit, "offset": offset,
    }


@router.get("/")
def get_logs(
    level: str = Query(""),
    limit: int = Query(300, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    _: dict = Depends(require_admin_or_gd),
):
    entries, total = _parse_log_file(level, limit, offset)
    return {"entries": entries, "total": total, "limit": limit, "offset": offset}
