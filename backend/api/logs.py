"""Log viewer API — chỉ dành cho Admin"""
import io
import os
import re
import sqlite3
import tempfile
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from backend.database import get_db, write_audit, _vn_now
from backend.core.config import settings
from backend.core.deps import require_feature
from backend.core.net import client_ip as _client_ip
from backend.core.rate_limit import MAX_FAILURES

router = APIRouter()

_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "logs", "app.log",
)

_LOG_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\w+)\s+(\S+)\s+—\s+(.*)$"
)

PAGE_SIZE = 50
# Thời hạn lưu nhật ký + việc dọn nằm ở backend/services/log_cleanup_service.py
# (chạy nền theo lịch, không dọn trong request xem nhật ký nữa)


def _parse_log_file(level_filter: str = "", page: int = 1, q: str = "",
                    tu_ngay: str = "", den_ngay: str = ""):
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
    # ts dạng "YYYY-MM-DD HH:MM:SS" — so chuỗi là so thời gian
    if _NGAY_RE.match(tu_ngay or ""):
        parsed = [e for e in parsed if e["ts"] >= tu_ngay]
    if _NGAY_RE.match(den_ngay or ""):
        moc = _ngay_ke_tiep(den_ngay)
        parsed = [e for e in parsed if e["ts"] < moc]
    if q.strip():
        k = q.strip().lower()
        parsed = [e for e in parsed if k in e["msg"].lower() or k in e["logger"].lower()]

    total = len(parsed)
    offset = (page - 1) * PAGE_SIZE
    return parsed[offset: offset + PAGE_SIZE], total


@router.get("/backup-info")
def get_backup_info(_: dict = Depends(require_feature("menu.logs"))):
    from backend.services.backup_service import last_backup_info
    return last_backup_info()


@router.get("/backup")
def backup_db(
    request: Request,
    current: dict = Depends(require_feature("menu.logs")),
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
        except OSError:
            pass        # file đã bị xoá / đang bị giữ — bản tải về đã gửi xong rồi

    # Ghi vào audit_logs, KHÔNG phải login_logs: tải backup không phải sự kiện
    # đăng nhập. Dòng cũ nằm trong login_logs với success=1 làm mọi thống kê
    # "số lượt đăng nhập" đếm dôi, và đẩy nhật ký đăng nhập thật ra khỏi trang
    # đầu. Đây là GET nên AuditMiddleware không đụng tới — phải tự ghi.
    # _client_ip(): frontend gọi backend qua loopback nên request.client.host
    # luôn là 127.0.0.1; IP thật của trình duyệt nằm ở X-Client-IP.
    stamp = _vn_now().strftime("%Y%m%d_%H%M%S")
    write_audit(db, current["id"], "db_backup_download", "system", None,
                f"Tải bản sao cơ sở dữ liệu ({stamp}) — file chứa TOÀN BỘ dữ liệu, gồm cả mã băm mật khẩu",
                _client_ip(request))
    db.commit()

    filename = f"ksnb_backup_{stamp}.db"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/logins/export")
def export_login_logs(
    success:  str = Query(""),
    q:        str = Query(""),
    tu_ngay:  str = Query(""),
    den_ngay: str = Query(""),
    _: dict = Depends(require_feature("menu.logs")),
    db: sqlite3.Connection = Depends(get_db),
):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    where, params = _login_where(success, q, tu_ngay, den_ngay)

    rows = db.execute(
        f"""SELECT ll.*, ks.full_name
            FROM login_logs ll
            {_JOIN_NGUOI}
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


# Lượt SAI MẬT KHẨU = success=0 và staff_id rỗng (auth.py chỉ gắn staff_id khi mật
# khẩu đã đúng mà bị chặn vì tài khoản đang mở ở máy khác — không phải dò mật khẩu).
# Cùng loại lượt mà rate_limit đếm để khoá tài khoản.
_SQL_SAI_MK = "success = 0 AND staff_id IS NULL"

# Số lần nhập sai trong CÙNG một ngày của một tài khoản để bị tô "nghi dò mật khẩu".
# Lấy đúng ngưỡng khoá tài khoản: mọi lượt bị khoá đều hiện ra; thấp hơn thì một
# người quên mật khẩu gõ lại vài lần cũng bị tô đỏ, người xem sẽ quen bỏ qua màu đỏ.
NGUONG_NGHI_VAN = MAX_FAILURES


# Lượt sai mật khẩu không có staff_id → nối thêm theo tên đăng nhập đã gõ. Không có
# nhánh này thì gõ họ tên vào ô tìm KHÔNG ra các lần người đó bị gõ sai mật khẩu —
# đúng loại dòng người giám sát cần tìm nhất.
_JOIN_NGUOI = ("LEFT JOIN user_tttt ks ON ks.id = ll.staff_id"
               " OR (ll.staff_id IS NULL AND ks.username = ll.username)")


def _login_where(success: str, q: str = "", tu_ngay: str = "", den_ngay: str = ""):
    clauses, params = [], []
    if success == "true":
        clauses.append("ll.success = 1")
    elif success == "false":
        clauses.append("ll.success = 0")
    if q.strip():
        like = f"%{q.strip()}%"
        clauses.append("(ll.username LIKE ? OR ks.full_name LIKE ? OR ll.ip_address LIKE ?)")
        params += [like, like, like]
    if _NGAY_RE.match(tu_ngay or ""):
        clauses.append("ll.created_at >= ?")
        params.append(tu_ngay)
    if _NGAY_RE.match(den_ngay or ""):
        clauses.append("ll.created_at < ?")
        params.append(_ngay_ke_tiep(den_ngay))
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


@router.get("/logins")
def get_login_logs(
    page:     int = Query(1, ge=1),
    success:  str = Query(""),
    q:        str = Query(""),
    tu_ngay:  str = Query(""),
    den_ngay: str = Query(""),
    _: dict = Depends(require_feature("menu.logs")),
    db: sqlite3.Connection = Depends(get_db),
):
    where, params = _login_where(success, q, tu_ngay, den_ngay)

    total = db.execute(
        f"SELECT COUNT(*) FROM login_logs ll {_JOIN_NGUOI} {where}",
        params,
    ).fetchone()[0]

    offset = (page - 1) * PAGE_SIZE
    # so_sai_ngay: tổng lượt sai mật khẩu của tài khoản đó trong cùng ngày — đếm trên CẢ
    # bảng, không theo bộ lọc, để lọc "Thất bại" hay tìm theo IP vẫn thấy đúng cờ nghi vấn.
    rows = db.execute(
        f"""SELECT ll.*, ks.full_name,
                   (SELECT COUNT(*) FROM login_logs x
                     WHERE x.username = ll.username AND x.success = 0 AND x.staff_id IS NULL
                       AND substr(x.created_at, 1, 10) = substr(ll.created_at, 1, 10)
                   ) AS so_sai_ngay
            FROM login_logs ll
            {_JOIN_NGUOI}
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
                "staff_id":   r["staff_id"],
                "full_name":  r["full_name"],
                "ip_address": r["ip_address"],
                "success":    bool(r["success"]),
                "detail":     r["detail"],
                "created_at": r["created_at"],
                "so_sai_ngay": r["so_sai_ngay"],
                "nghi_van":   (not r["success"]) and r["staff_id"] is None
                              and r["so_sai_ngay"] >= NGUONG_NGHI_VAN,
            }
            for r in rows
        ],
        "total":     total,
        "page":      page,
        "page_size": PAGE_SIZE,
        "pages":     max(1, -(-total // PAGE_SIZE)),  # ceiling division
    }


def _ngay_ke_tiep(s: str) -> str:
    """'2026-09-03' → '2026-09-04'. Lọc tới-ngày bằng `< hôm sau` chứ không
    `<= hôm nay`: created_at có cả giờ phút nên `<=` sẽ cắt mất chính ngày đó."""
    from datetime import date, timedelta
    y, m, d = (int(x) for x in s.split("-"))
    return (date(y, m, d) + timedelta(days=1)).isoformat()


_NGAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# Cùng quy tắc với audit_labels.result_ok(), viết bằng SQL để lọc + đếm được trên
# cả bảng: dòng ngữ nghĩa (write_audit) luôn là thành công; dòng middleware thành
# công khi mã HTTP 2xx. Dòng middleware mang mô tả tự viết (token Extension sai —
# xem doi_chieu_citad.py) không có "HTTP 2" nên rơi vào thất bại, đúng như màn hình tô.
_SQL_THAT_BAI = ("(al.action IN ('POST','PUT','PATCH','DELETE')"
                 " AND COALESCE(al.detail, '') NOT LIKE 'HTTP 2%')")


def _audit_where(method: str, q: str, tu_ngay: str = "", den_ngay: str = "",
                 actor_id: int = 0, module: str = "", ket_qua: str = "",
                 doi_tuong: str = ""):
    clauses, params = [], []
    m = (method or "").upper()
    # "Sửa" trên màn hình là cả PUT lẫn PATCH — lọc riêng PUT thì mọi thao tác
    # PATCH (huỷ đơn, sửa lưu trữ, sửa ngày vào ngành…) biến mất khỏi nút "Sửa".
    if m in ("PUT", "PATCH"):
        clauses.append("al.action IN ('PUT','PATCH')")
    elif m in ("POST", "DELETE"):
        clauses.append("al.action = ?")
        params.append(m)
    if ket_qua == "loi":
        clauses.append(_SQL_THAT_BAI)
    elif ket_qua == "ok":
        clauses.append("NOT " + _SQL_THAT_BAI)
    # Lịch sử một hồ sơ: đúng đường đó hoặc đường con của nó. Không dùng LIKE
    # 'khoa%' trần — '/api/leaves/12%' dính cả đơn 120, 1234.
    if doi_tuong:
        clauses.append("(al.target_type = ? OR al.target_type LIKE ?)")
        params += [doi_tuong, doi_tuong + "/%"]
    if q.strip():
        like = f"%{q.strip()}%"
        clauses.append("(al.target_type LIKE ? OR al.detail LIKE ? OR ks.full_name LIKE ? OR ks.username LIKE ?)")
        params += [like, like, like, like]
    # Ngày sai định dạng thì BỎ QUA bộ lọc thay vì ném lỗi: người dùng gõ dở
    # trong ô ngày không đáng làm cả trang nhật ký trắng xoá.
    if _NGAY_RE.match(tu_ngay or ""):
        clauses.append("al.created_at >= ?")
        params.append(tu_ngay)
    if _NGAY_RE.match(den_ngay or ""):
        clauses.append("al.created_at < ?")
        params.append(_ngay_ke_tiep(den_ngay))
    if actor_id:
        clauses.append("al.actor_id = ?")
        params.append(actor_id)
    if module:
        clauses.append("al.target_type LIKE ?")
        params.append(f"{module}%")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


@router.get("/audit/filters")
def get_audit_filters(
    _: dict = Depends(require_feature("menu.logs")),
    db: sqlite3.Connection = Depends(get_db),
):
    """Dữ liệu đổ vào 2 ô chọn của bộ lọc: người thao tác và module.

    Chỉ liệt kê người ĐÃ có dòng trong nhật ký — danh sách toàn bộ nhân sự dài
    gấp nhiều lần mà phần lớn chọn vào sẽ ra bảng rỗng.
    """
    from backend.services.audit_labels import MODULES
    rows = db.execute(
        """SELECT ks.id, ks.full_name, ks.username, COUNT(*) AS n
           FROM audit_logs al JOIN user_tttt ks ON al.actor_id = ks.id
           GROUP BY ks.id ORDER BY ks.full_name COLLATE NOCASE"""
    ).fetchall()
    return {
        "actors": [
            {"id": r["id"], "label": f"{r['full_name'] or r['username']} ({r['n']})"}
            for r in rows
        ],
        "modules": [{"prefix": p, "label": lbl} for p, lbl in MODULES],
    }


def _dong_audit(r) -> dict:
    from backend.services.audit_labels import (describe_work, describe_result, describe_detail,
                                               describe_target, result_ok)
    return {
        "id":          r["id"],
        "created_at":  r["created_at"],
        "work":        describe_work(r["action"], r["target_type"]),
        "result":      describe_result(r["detail"], r["action"]),
        "result_ok":   result_ok(r["detail"], r["action"]),
        "detail":      describe_detail(r["detail"]),
        "doi_tuong":   describe_target(r["target_type"]),
        "target_type": r["target_type"],   # path thô — cho tooltip tra cứu
        "action":      r["action"],        # METHOD hoặc mã ngữ nghĩa
        "raw_detail":  r["detail"],        # nguyên văn — hộp thoại chi tiết
        "ip_address":  r["ip_address"],
        "actor_id":    r["actor_id"],
        "username":    r["username"],
        "full_name":   r["full_name"],
    }


@router.get("/audit/{audit_id}/lan-can")
def get_audit_lan_can(
    audit_id: int,
    phut: int = Query(10, ge=1, le=120),
    _: dict = Depends(require_feature("menu.logs")),
    db: sqlite3.Connection = Depends(get_db),
):
    """Các thao tác khác của CÙNG người trong ±`phut` phút quanh một dòng — trả lời
    "ngay trước/sau đó họ đã làm gì" mà không phải tự đặt bộ lọc giờ."""
    goc = db.execute("SELECT actor_id, created_at FROM audit_logs WHERE id = ?",
                     (audit_id,)).fetchone()
    if not goc or goc["actor_id"] is None:
        return {"entries": []}
    rows = db.execute(
        f"""SELECT al.*, ks.full_name, ks.username
            FROM audit_logs al LEFT JOIN user_tttt ks ON al.actor_id = ks.id
            WHERE al.actor_id = ? AND al.id != ?
              AND al.created_at BETWEEN datetime(?, '-{phut} minutes')
                                    AND datetime(?, '+{phut} minutes')
            ORDER BY al.created_at, al.id LIMIT 30""",
        (goc["actor_id"], audit_id, str(goc["created_at"]), str(goc["created_at"])),
    ).fetchall()
    return {"entries": [_dong_audit(r) for r in rows]}


@router.get("/audit")
def get_audit_logs(
    page:     int = Query(1, ge=1),
    method:   str = Query(""),
    q:        str = Query(""),
    tu_ngay:  str = Query(""),
    den_ngay: str = Query(""),
    actor_id: int = Query(0),
    module:   str = Query(""),
    ket_qua:  str = Query(""),
    doi_tuong: str = Query(""),
    _: dict = Depends(require_feature("menu.logs")),
    db: sqlite3.Connection = Depends(get_db),
):
    where, params = _audit_where(method, q, tu_ngay, den_ngay, actor_id, module,
                                 ket_qua, doi_tuong)
    base = f"""FROM audit_logs al
               LEFT JOIN user_tttt ks ON al.actor_id = ks.id
               {where}"""

    total = db.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    offset = (page - 1) * PAGE_SIZE
    rows = db.execute(
        f"""SELECT al.*, ks.full_name, ks.username {base}
            ORDER BY al.created_at DESC, al.id DESC
            LIMIT ? OFFSET ?""",
        params + [PAGE_SIZE, offset],
    ).fetchall()

    return {
        "entries": [_dong_audit(r) for r in rows],
        "total":     total,
        "page":      page,
        "page_size": PAGE_SIZE,
        "pages":     max(1, -(-total // PAGE_SIZE)),
    }


@router.get("/audit/export")
def export_audit_logs(
    method:   str = Query(""),
    q:        str = Query(""),
    tu_ngay:  str = Query(""),
    den_ngay: str = Query(""),
    actor_id: int = Query(0),
    module:   str = Query(""),
    ket_qua:  str = Query(""),
    doi_tuong: str = Query(""),
    _: dict = Depends(require_feature("menu.logs")),
    db: sqlite3.Connection = Depends(get_db),
):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from datetime import date
    from backend.services.audit_labels import describe_work, describe_result, describe_detail

    where, params = _audit_where(method, q, tu_ngay, den_ngay, actor_id, module,
                                 ket_qua, doi_tuong)
    rows = db.execute(
        f"""SELECT al.*, ks.full_name, ks.username
            FROM audit_logs al
            LEFT JOIN user_tttt ks ON al.actor_id = ks.id
            {where}
            ORDER BY al.created_at DESC, al.id DESC""",
        params,
    ).fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Nhật ký hệ thống"
    hdr_fill = PatternFill("solid", fgColor="37474F")
    hdr_font = Font(bold=True, color="FFFFFF")
    headers = ["STT", "Thời gian", "Người thao tác", "Username", "Công việc", "Chi tiết", "Kết quả", "IP", "Đường dẫn kỹ thuật"]
    widths  = [6, 18, 26, 18, 40, 70, 20, 18, 40]
    ws.append(headers)
    for cell, w in zip(ws[1], widths):
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = w

    for idx, r in enumerate(rows, 1):
        ts = (r["created_at"] or "")[:19].replace("T", " ")
        ws.append([
            idx, ts,
            r["full_name"] or "", r["username"] or "",
            describe_work(r["action"], r["target_type"]),
            describe_detail(r["detail"]),
            describe_result(r["detail"], r["action"]),
            r["ip_address"] or "", r["target_type"] or "",
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"nhat_ky_he_thong_{date.today().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"},
    )


@router.get("/time-sync")
def get_time_sync(_: dict = Depends(require_feature("menu.logs"))):
    """Trạng thái lệch giờ máy chủ so với nguồn NTP + giờ máy hiện tại."""
    from backend.services.time_sync import check_drift
    r = check_drift()
    r["server_time"] = _vn_now().strftime("%Y-%m-%d %H:%M:%S")
    return r


@router.get("/")
def get_logs(
    level:    str = Query(""),
    page:     int = Query(1, ge=1),
    q:        str = Query(""),
    tu_ngay:  str = Query(""),
    den_ngay: str = Query(""),
    _: dict = Depends(require_feature("menu.logs")),
):
    entries, total = _parse_log_file(level, page, q, tu_ngay, den_ngay)
    return {
        "entries":   entries,
        "total":     total,
        "page":      page,
        "page_size": PAGE_SIZE,
        "pages":     max(1, -(-total // PAGE_SIZE)),
    }


# ── Tổng quan: "trong khoảng này có gì bất thường?" ──────────────────────────
# Chỉ phần của NHẬT KÝ. Sức khoẻ máy (RAM, đĩa, CSDL, sao lưu) đã có ở màn Giám sát
# hệ thống — vẽ lại ở đây là hai nơi hai ngưỡng. Mỗi mục "cần chú ý" kèm sẵn bộ lọc
# (`tab` + `loc`) để frontend bấm vào là mở đúng danh sách, không tự dựng lại.
_SO_MUC_CHU_Y = 5


def _nhom_thao_tac_loi(db, tu: str) -> list[dict]:
    from backend.services.audit_labels import MODULES, describe_result, describe_work
    rows = db.execute(
        f"""SELECT al.action, al.target_type, al.detail, al.actor_id, al.created_at,
                   ks.full_name, ks.username
            FROM audit_logs al LEFT JOIN user_tttt ks ON al.actor_id = ks.id
            WHERE al.created_at >= ? AND {_SQL_THAT_BAI}
            ORDER BY al.created_at DESC LIMIT 2000""",
        (tu,),
    ).fetchall()
    nhom: dict[tuple, dict] = {}
    for r in rows:
        viec = describe_work(r["action"], r["target_type"])
        g = nhom.get((viec, r["actor_id"]))
        if g is None:
            ket_qua = describe_result(r["detail"], r["action"])
            module = next((p for p, _ in MODULES if (r["target_type"] or "").startswith(p)), "")
            loc = {"ket_qua": "loi", "tu_ngay": tu}
            if r["actor_id"]:
                loc["actor_id"] = r["actor_id"]
            if module:
                loc["module"] = module
            g = nhom[(viec, r["actor_id"])] = {
                "viec": viec, "nguoi": r["full_name"] or r["username"] or "không rõ người",
                "ket_qua": ket_qua, "lan": 0, "cuoi": str(r["created_at"])[:16],
                "nghiem_trong": ket_qua == "Lỗi hệ thống", "loc": loc,
            }
        g["lan"] += 1
    ds = sorted(nhom.values(), key=lambda g: (not g["nghiem_trong"], -g["lan"]))
    return [{
        "muc": "loi" if g["nghiem_trong"] else "canh_bao",
        "noi_dung": f"\"{g['viec']}\" — {g['ket_qua'].lower()} {g['lan']} lần · {g['nguoi']}",
        "thoi_gian": g["cuoi"], "tab": "thao-tac", "loc": g["loc"],
    } for g in ds[:_SO_MUC_CHU_Y]]


def _nhom_dang_nhap_sai(db, tu: str) -> list[dict]:
    from backend.core.rate_limit import MAX_FAILURES_IP
    ds = []
    for r in db.execute(
        f"""SELECT username, COUNT(*) AS n, MIN(created_at) AS dau, MAX(created_at) AS cuoi
           FROM login_logs WHERE {_SQL_SAI_MK} AND created_at >= ?
           GROUP BY username HAVING n >= ? ORDER BY n DESC LIMIT ?""",
        (tu, NGUONG_NGHI_VAN, _SO_MUC_CHU_Y),
    ):
        ds.append({
            "muc": "loi",
            "noi_dung": f"Tài khoản \"{r['username']}\" nhập sai mật khẩu {r['n']} lần",
            "thoi_gian": str(r["cuoi"])[:16], "tab": "dang-nhap",
            "loc": {"success": "false", "q": r["username"], "tu_ngay": tu},
        })
    # Một máy thử nhiều tài khoản khác nhau — từng tài khoản có thể dưới ngưỡng
    for r in db.execute(
        f"""SELECT ip_address, COUNT(*) AS n, COUNT(DISTINCT username) AS so_tk,
                  MAX(created_at) AS cuoi
           FROM login_logs WHERE {_SQL_SAI_MK} AND created_at >= ? AND ip_address IS NOT NULL
           GROUP BY ip_address HAVING n >= ? ORDER BY n DESC LIMIT ?""",
        (tu, MAX_FAILURES_IP, _SO_MUC_CHU_Y),
    ):
        ds.append({
            "muc": "loi",
            "noi_dung": f"Máy {r['ip_address']} đăng nhập sai {r['n']} lần vào {r['so_tk']} tài khoản",
            "thoi_gian": str(r["cuoi"])[:16], "tab": "dang-nhap",
            "loc": {"success": "false", "q": r["ip_address"], "tu_ngay": tu},
        })
    return ds


_SO_TRONG_MSG = re.compile(r"\d+")


def _nhom_loi_he_thong(loi: list[dict], tu: str) -> list[dict]:
    """Gộp lỗi trùng: cùng nguồn + cùng câu (bỏ số — id, thời lượng khác nhau vẫn là
    một lỗi). 50 dòng cùng một lỗi hiện thành 1 mục "xảy ra 50 lần"."""
    nhom: dict[tuple, dict] = {}
    for e in loi:                         # đã xếp mới nhất trước
        khoa = (e["nguon"], _SO_TRONG_MSG.sub("#", e["msg"])[:120])
        g = nhom.get(khoa)
        if g is None:
            g = nhom[khoa] = {"e": e, "lan": 0}
        g["lan"] += 1
    ds = sorted(nhom.values(), key=lambda g: -g["lan"])[:_SO_MUC_CHU_Y]
    return [{
        "muc": "loi",
        "noi_dung": g["e"]["msg"][:160] + (f" — {g['lan']} lần" if g["lan"] > 1 else ""),
        "thoi_gian": g["e"]["ts"][:16], "tab": "loi",
        # Tìm theo đoạn đầu câu (trước số đầu tiên) để khớp mọi lần lặp của lỗi này
        "loc": {"level": "ERROR", "tu_ngay": tu,
                "q": _SO_TRONG_MSG.split(g["e"]["msg"])[0].strip()[:60]},
    } for g in ds]


@router.get("/tong-quan")
def get_tong_quan(
    so_ngay: int = Query(1, ge=1, le=30),
    _: dict = Depends(require_feature("menu.logs")),
    db: sqlite3.Connection = Depends(get_db),
):
    # `def` chứ không `async def`: quét app.log tới vài MB, phải nằm trong bể luồng
    from datetime import datetime, timedelta
    from pathlib import Path
    from backend.api.monitor import _file_log, _quet_log

    tu = (_vn_now() - timedelta(days=so_ngay - 1)).strftime("%Y-%m-%d")

    def dem(sql: str) -> int:
        return db.execute(sql, (tu,)).fetchone()[0]

    # Giờ trong app.log là giờ máy (formatter logging), không phải _vn_now()
    moc = datetime.strptime(tu, "%Y-%m-%d")
    nk = _quet_log(_file_log(Path(_LOG_PATH), moc), moc, so_loi_gan=2000)
    return {
        "tu_ngay": tu,
        "so": {
            "thao_tac":      dem("SELECT COUNT(*) FROM audit_logs WHERE created_at >= ?"),
            "that_bai":      dem(f"SELECT COUNT(*) FROM audit_logs al WHERE al.created_at >= ? AND {_SQL_THAT_BAI}"),
            "dang_nhap":     dem("SELECT COUNT(*) FROM login_logs WHERE success = 1 AND created_at >= ?"),
            "dang_nhap_sai": dem("SELECT COUNT(*) FROM login_logs WHERE success = 0 AND created_at >= ?"),
            "loi_he_thong":  nk["loi"],
            "canh_bao":      nk["canh_bao"],
        },
        "chu_y": _nhom_dang_nhap_sai(db, tu) + _nhom_thao_tac_loi(db, tu)
                 + _nhom_loi_he_thong(nk["loi_gan"], tu),
    }
