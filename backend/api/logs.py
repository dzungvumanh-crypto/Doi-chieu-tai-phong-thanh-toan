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
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.core.config import settings
from backend.core.deps import require_admin, require_admin_or_gd

router = APIRouter()

_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "logs", "app.log",
)

# Format: "2025-05-09 14:23:45 INFO     backend.api.auth — message"
_LOG_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\w+)\s+(\S+)\s+—\s+(.*)$"
)


def _parse_log_file(level_filter: str = "", limit: int = 200, offset: int = 0):
    if not os.path.exists(_LOG_PATH):
        return [], 0

    with open(_LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    # Parse forward, gom multi-line (traceback) vào entry trước đó
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

    # Mới nhất trước
    parsed.reverse()

    if level_filter and level_filter.upper() not in ("ALL", ""):
        parsed = [e for e in parsed if e["level"] == level_filter.upper()]

    total = len(parsed)
    return parsed[offset: offset + limit], total


@router.get("/backup")
def backup_db(_: object = Depends(require_admin_or_gd)):
    """Tạo bản sao DB an toàn (SQLite online backup API) và trả về file tải về."""
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
    limit:   int  = Query(200, ge=1, le=1000),
    offset:  int  = Query(0, ge=0),
    success: str  = Query("", description="'' | 'true' | 'false'"),
    _: object = Depends(require_admin_or_gd),
    db: Session = Depends(get_db),
):
    """Xem lịch sử đăng nhập / đăng nhập thất bại."""
    from backend.models import LoginLog

    q = db.query(LoginLog).order_by(LoginLog.created_at.desc())
    if success == "true":
        q = q.filter(LoginLog.success == True)
    elif success == "false":
        q = q.filter(LoginLog.success == False)
    total = q.count()
    logs  = q.offset(offset).limit(limit).all()
    return {
        "entries": [
            {
                "id":         log.id,
                "username":   log.username,
                "full_name":  log.staff.full_name if log.staff else None,
                "ip_address": log.ip_address,
                "success":    log.success,
                "detail":     log.detail,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
        "total": total, "limit": limit, "offset": offset,
    }


@router.get("/")
def get_logs(
    level: str = Query("", description="Lọc: ERROR | WARNING | INFO | DEBUG | ALL"),
    limit: int = Query(300, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    _: object = Depends(require_admin_or_gd),
):
    entries, total = _parse_log_file(level, limit, offset)
    return {"entries": entries, "total": total, "limit": limit, "offset": offset}
