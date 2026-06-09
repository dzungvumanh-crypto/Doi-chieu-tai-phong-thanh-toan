"""Log viewer API — chỉ dành cho Admin"""
import io
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from backend.database import get_db, _vn_now
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

PAGE_SIZE = 50
LOG_RETENTION_DAYS = 30


def _parse_log_file(level_filter: str = "", page: int = 1):
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
    offset = (page - 1) * PAGE_SIZE
    return parsed[offset: offset + PAGE_SIZE], total


def _cleanup_login_logs(db: sqlite3.Connection) -> None:
    """Xóa login_logs cũ hơn LOG_RETENTION_DAYS ngày."""
    cutoff = (datetime.utcnow() - timedelta(days=LOG_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("DELETE FROM login_logs WHERE created_at < ?", (cutoff,))
    db.commit()


@router.get("/backup-info")
def get_backup_info(_: dict = Depends(require_admin_or_gd)):
    from backend.services.backup_service import last_backup_info
    return last_backup_info()


@router.get("/backup")
def backup_db(
    request: Request,
    current: dict = Depends(require_admin_or_gd),
    db: sqlite3.Connection = Depends(get_db),
):
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

    client_ip = request.client.host if request.client else "unknown"
    stamp = _vn_now().strftime("%Y%m%d_%H%M%S")
    db.execute(
        "INSERT INTO login_logs (username, staff_id, ip_address, success, detail, created_at) VALUES (?,?,?,?,?,?)",
        (current["username"], current["id"], client_ip, 1, f"backup_download:{stamp}", _vn_now()),
    )
    db.commit()

    filename = f"ksnb_backup_{stamp}.db"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/logins/export")
def export_login_logs(
    success: str = Query(""),
    _: dict = Depends(require_admin_or_gd),
    db: sqlite3.Connection = Depends(get_db),
):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    clauses = []
    params: list = []
    if success == "true":
        clauses.append("ll.success = 1")
    elif success == "false":
        clauses.append("ll.success = 0")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""

    rows = db.execute(
        f"""SELECT ll.*, ks.full_name
            FROM login_logs ll
            LEFT JOIN user_tttt ks ON ll.staff_id = ks.id
            {where}
            ORDER BY ll.created_at DESC""",
        params,
    ).fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Nhật ký đăng nhập"

    hdr_fill = PatternFill("solid", fgColor="37474F")
    hdr_font = Font(bold=True, color="FFFFFF")
    headers = ["STT", "Thời gian", "Kết quả", "Username", "Họ và tên", "IP", "Chi tiết"]
    widths  = [6, 18, 12, 20, 28, 18, 40]
    ws.append(headers)
    for cell, w in zip(ws[1], widths):
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = w

    for idx, r in enumerate(rows, 1):
        ts = (r["created_at"] or "")[:16].replace("T", " ")
        ws.append([
            idx,
            ts,
            "Thành công" if r["success"] else "Thất bại",
            r["username"] or "",
            r["full_name"] or "",
            r["ip_address"] or "",
            r["detail"] or "",
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    from datetime import date
    fname = f"nhat_ky_dang_nhap_{date.today().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"},
    )


@router.get("/logins")
def get_login_logs(
    page:    int = Query(1, ge=1),
    success: str = Query(""),
    _: dict = Depends(require_admin_or_gd),
    db: sqlite3.Connection = Depends(get_db),
):
    _cleanup_login_logs(db)

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

    offset = (page - 1) * PAGE_SIZE
    rows = db.execute(
        f"""SELECT ll.*, ks.full_name
            FROM login_logs ll
            LEFT JOIN user_tttt ks ON ll.staff_id = ks.id
            {where}
            ORDER BY ll.created_at DESC
            LIMIT ? OFFSET ?""",
        params + [PAGE_SIZE, offset],
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
        "total":     total,
        "page":      page,
        "page_size": PAGE_SIZE,
        "pages":     max(1, -(-total // PAGE_SIZE)),  # ceiling division
    }


@router.get("/")
def get_logs(
    level: str = Query(""),
    page:  int  = Query(1, ge=1),
    _: dict = Depends(require_admin_or_gd),
):
    entries, total = _parse_log_file(level, page)
    return {
        "entries":   entries,
        "total":     total,
        "page":      page,
        "page_size": PAGE_SIZE,
        "pages":     max(1, -(-total // PAGE_SIZE)),
    }
