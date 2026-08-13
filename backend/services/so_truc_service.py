"""Business logic Sổ trực cuối ngày — Phòng Thanh toán.

Mỗi ngày trực có 2 GDV + 1 KSV (không lấy dữ liệu từ module Phân lịch trực ở
bản này — GDV1/GDV2 CHỌN từ danh sách nhân viên Phòng Thanh toán qua
`list_gdv_candidates()`, lưu bằng `gdv1_id`/`gdv2_id`). Luồng duyệt 2 bước:

    draft -> pending_gdv_confirm -> pending_ksv -> approved
                                                  -> draft (từ chối để sửa)
                                                  -> cancelled (từ chối để huỷ — NGÕ CỤT)

1. Một trong 2 GDV điền ghi chú + chọn KSV rồi bấm "Chuyển KSV xác nhận"
   (forward_to_ksv) -> pending_gdv_confirm. Đây cũng là lúc "khoá" bản ghi:
   kể từ khi gdv1_id/gdv2_id được set lần đầu, CHỈ 2 tài khoản đó được sửa
   tiếp (save_draft/forward_to_ksv/gdv_confirm) — xem `_is_locked()`.
2. GDV CÒN LẠI (đúng 1 trong 2 người đã khoá, khác người khởi tạo) phải tự
   mở lại đúng sổ ngày đó, thấy rõ nội dung + tên KSV người kia chọn, rồi
   bấm "Đồng ý xác nhận" (gdv_confirm) -> pending_ksv. Không có xác nhận
   song song — bước 2 LUÔN cần đúng người còn lại xem qua.
3. KSV — CHỈ đúng tài khoản `ksv_id` đã được chọn mới xác nhận/từ chối được
   (kiểm tra ở đây, KHÔNG chỉ dựa vào feature `so_truc.ksv_confirm` — feature
   đó chỉ xác định AI ĐƯỢC PHÉP xuất hiện trong danh sách chọn KSV, không có
   nghĩa mọi người trong nhóm đều thao tác thay nhau được). Có 2 lựa chọn:
   - "Từ chối để sửa" (ksv_reject) -> quay lại "draft", GIỮ NGUYÊN gdv1_id/
     gdv2_id/ksv_id/ghi_chu — 2 GDV sửa nội dung rồi đẩy lại. Khi đẩy lại,
     forward_to_ksv() BẮT BUỘC giữ nguyên đúng `ksv_id` cũ (không cho đổi
     sang KSV khác — xem check trong forward_to_ksv()).
   - "Từ chối để huỷ" (ksv_cancel) -> "cancelled", NGÕ CỤT — dòng này đóng
     vĩnh viễn (không tự quay lại draft). Ai đó phải tạo 1 PHIÊN TRỰC MỚI
     (dòng mới) cho đúng ngày đó nếu cần làm lại — xem get_active_by_date().

Tranh chấp 2 GDV bấm "Chuyển KSV xác nhận" gần như cùng lúc TRÊN 1 NGÀY CHƯA
CÓ DÒNG NÀO: `so_truc_records` có UNIQUE INDEX một phần
`ux_so_truc_active_date (truc_date) WHERE status != 'cancelled'` (xem
migrations.py) — chỉ 1 trong 2 câu INSERT thành công, câu kia bắt
IntegrityError rồi đọc lại đúng dòng của người thắng. Sau đó cả 2 cùng chạy
tiếp UPDATE ... WHERE id=? AND status='draft' — chỉ 1 request thắng
(rowcount=1), người thua (rowcount=0) được coi là đã "xem" bản ghi vừa được
người kia tạo, trả về y hệt dữ liệu hiện tại (KHÔNG báo lỗi) để frontend tự
chuyển sang màn hình "Đồng ý xác nhận" — trải nghiệm liền mạch.

KHÔNG tách bảng lịch sử riêng như doi_chieu_citad — bảng này tự thân là lịch
sử (tab "Lịch sử" liệt kê lại các dòng, MỘT ngày có thể có NHIỀU dòng nếu đã
từng bị "huỷ" rồi mở phiên mới). `get_active_by_date()` luôn trả về dòng
CHƯA 'cancelled' MỚI NHẤT của 1 ngày — là dòng "đang làm việc" hiện tại;
None nghĩa là chưa có dòng nào, hoặc mọi dòng cũ đều đã 'cancelled' (ngày đó
coi như trống, ai có quyền cũng tạo phiên mới được).
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from backend.database import _vn_now


class NotAllowedError(Exception):
    """Vi phạm ràng buộc nghiệp vụ 'đúng người mới được thao tác' (GDV/KSV
    không thuộc bản ghi) — API map sang HTTP 403, khác `ValueError` (400)."""


def _row_to_dict(db: sqlite3.Connection, row: sqlite3.Row) -> dict:
    d = dict(row)

    def _name(uid):
        if not uid:
            return None
        r = db.execute("SELECT full_name FROM user_tttt WHERE id=?", (uid,)).fetchone()
        return r["full_name"] if r else None

    # gdv1_name/gdv2_name luôn tính LẠI từ gdv1_id/gdv2_id (nguồn sự thật) —
    # 2 cột TEXT cùng tên trong bảng là tàn dư bản cũ, không đọc nữa.
    d["gdv1_name"] = _name(d.get("gdv1_id"))
    d["gdv2_name"] = _name(d.get("gdv2_id"))
    d["initiated_by_name"] = _name(d.get("initiated_by"))
    d["ksv_name"] = _name(d.get("ksv_id"))
    d["confirmed_by_name"] = _name(d.get("confirmed_by"))
    d["ksv_decided_by_name"] = _name(d.get("ksv_decided_by"))
    for k in ("initiated_at", "confirmed_at", "ksv_decided_at", "created_at", "updated_at"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    return d


def _is_locked(rec: Optional[dict]) -> bool:
    return bool(rec) and bool(rec.get("gdv1_id") or rec.get("gdv2_id"))


def get_active_by_date(db: sqlite3.Connection, truc_date: str) -> Optional[dict]:
    """Dòng CHƯA 'cancelled' mới nhất của 1 ngày — phiên trực đang làm việc."""
    row = db.execute(
        "SELECT * FROM so_truc_records WHERE truc_date=? AND status != 'cancelled' ORDER BY id DESC LIMIT 1",
        (truc_date,),
    ).fetchone()
    return _row_to_dict(db, row) if row else None


def _get_by_id(db: sqlite3.Connection, record_id: int) -> Optional[dict]:
    row = db.execute("SELECT * FROM so_truc_records WHERE id=?", (record_id,)).fetchone()
    return _row_to_dict(db, row) if row else None


def _insert_new_draft(db: sqlite3.Connection, truc_date: str, gdv1_id, gdv2_id, ghi_chu: str, now: str) -> Optional[dict]:
    """Tạo dòng mới cho ngày chưa có phiên trực đang hoạt động nào (chưa có
    dòng nào, hoặc mọi dòng cũ đã 'cancelled'). An toàn khi 2 người cùng bấm
    gần như đồng thời nhờ UNIQUE INDEX một phần `ux_so_truc_active_date` —
    ai thua tranh chấp bắt IntegrityError rồi đọc lại đúng dòng người thắng."""
    try:
        db.execute(
            """INSERT INTO so_truc_records
               (truc_date, gdv1_id, gdv2_id, ghi_chu, status, created_at, updated_at)
               VALUES (?,?,?,?,'draft',?,?)""",
            (truc_date, gdv1_id, gdv2_id, ghi_chu, now, now),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
    return get_active_by_date(db, truc_date)


def save_draft(
    db: sqlite3.Connection, truc_date: str, staff_id: int, gdv1_id, gdv2_id, ghi_chu: str,
) -> dict:
    """Lưu tạm khi đang ở draft (hoặc chưa có phiên nào đang hoạt động — tạo
    phiên mới). Không cho sửa khi đã qua draft (đang chờ người khác xác
    nhận/KSV duyệt) — phải chờ luồng tự nhiên (KSV từ chối/huỷ) mới sửa lại
    được. Một khi phiên đã có gdv1_id/gdv2_id (đã khoá), chỉ 2 người đó
    được sửa tiếp."""
    now = _vn_now()
    rec = get_active_by_date(db, truc_date)
    if rec is None:
        return _insert_new_draft(db, truc_date, gdv1_id, gdv2_id, ghi_chu, now)
    if rec["status"] != "draft":
        raise ValueError(f"Sổ trực ngày {truc_date} đang ở trạng thái '{rec['status']}', không thể sửa trực tiếp")
    if _is_locked(rec) and staff_id not in (rec.get("gdv1_id"), rec.get("gdv2_id")):
        raise NotAllowedError("Chỉ 2 GDV được phân trực ngày này mới được sửa")
    db.execute(
        "UPDATE so_truc_records SET gdv1_id=?, gdv2_id=?, ghi_chu=?, updated_at=? WHERE id=?",
        (gdv1_id, gdv2_id, ghi_chu, now, rec["id"]),
    )
    db.commit()
    return get_active_by_date(db, truc_date)


def forward_to_ksv(
    db: sqlite3.Connection, truc_date: str, staff_id: int,
    gdv1_id, gdv2_id, ghi_chu: str, ksv_id: int,
) -> dict:
    """1 GDV bấm "Chuyển KSV xác nhận". Nếu chưa có phiên nào đang hoạt động
    cho ngày này, tự tạo trước rồi mới chuyển — gộp làm 1 thao tác cho gọn
    (không bắt buộc phải bấm "Lưu nháp" trước)."""
    now = _vn_now()
    rec = get_active_by_date(db, truc_date)
    if rec is None:
        rec = _insert_new_draft(db, truc_date, gdv1_id, gdv2_id, ghi_chu, now)

    if _is_locked(rec) and staff_id not in (rec.get("gdv1_id"), rec.get("gdv2_id")):
        raise NotAllowedError("Chỉ 2 GDV được phân trực ngày này mới được thao tác")
    if not gdv1_id or not gdv2_id:
        raise ValueError("Phải chọn đủ 2 GDV trực trước khi chuyển KSV xác nhận")
    if gdv1_id == gdv2_id:
        raise ValueError("GDV 1 và GDV 2 không được trùng nhau")
    if rec.get("ksv_id") is not None and rec["ksv_id"] != ksv_id:
        raise ValueError(
            f"Không được đổi KSV đã chọn ban đầu ({rec.get('ksv_name') or ''}) "
            "— phải giữ nguyên đúng người đó xác nhận lại"
        )
    # KSV phải thực sự nằm trong danh sách được phép xác nhận — chọn xong mà
    # mất quyền (rời nhóm/deactivate) trước khi khoá sẽ kẹt bản ghi vĩnh viễn
    # vì ksv_id không đổi được nữa sau bước này.
    valid_ksv_ids = {c["id"] for c in list_ksv_candidates(db)}
    if ksv_id not in valid_ksv_ids:
        raise ValueError("KSV được chọn không còn quyền xác nhận sổ trực — chọn lại người khác")

    # Tranh chấp: chỉ request nào khớp đúng WHERE id=? AND status='draft' mới thắng.
    db.execute(
        """UPDATE so_truc_records
           SET status='pending_gdv_confirm', gdv1_id=?, gdv2_id=?, ghi_chu=?,
               initiated_by=?, initiated_at=?, ksv_id=?, updated_at=?
           WHERE id=? AND status='draft'""",
        (gdv1_id, gdv2_id, ghi_chu, staff_id, now, ksv_id, now, rec["id"]),
    )
    db.commit()
    # rowcount==0: thua tranh chấp (người khác vừa initiate) HOẶC phiên này đã
    # qua draft từ trước — cả 2 trường hợp đều trả về bản ghi HIỆN TẠI, không
    # báo lỗi, để frontend tự hiển thị đúng màn hình theo status thật.
    return get_active_by_date(db, truc_date)


def gdv_confirm(db: sqlite3.Connection, truc_date: str, staff_id: int) -> dict:
    """GDV còn lại đồng ý xác nhận nội dung + KSV mà người kia đã chọn."""
    rec = get_active_by_date(db, truc_date)
    if rec is None or rec["status"] != "pending_gdv_confirm":
        raise ValueError("Sổ trực không ở trạng thái chờ xác nhận")
    if staff_id not in (rec.get("gdv1_id"), rec.get("gdv2_id")):
        raise NotAllowedError("Chỉ 2 GDV được phân trực ngày này mới được xác nhận")
    if rec["initiated_by"] == staff_id:
        raise ValueError("Chính bạn là người đã chuyển KSV xác nhận — cần người trực còn lại đồng ý")
    now = _vn_now()
    # AND status='pending_gdv_confirm' + kiểm tra rowcount: chặn race condition
    # (vd 2 tab cùng bấm, hoặc KSV vừa từ chối/huỷ đúng lúc GDV bấm) — không có
    # điều kiện này thì request chạy sau sẽ âm thầm ghi đè mà không báo lỗi.
    cur = db.execute(
        "UPDATE so_truc_records SET status='pending_ksv', confirmed_by=?, confirmed_at=?, updated_at=? "
        "WHERE id=? AND status='pending_gdv_confirm'",
        (staff_id, now, now, rec["id"]),
    )
    db.commit()
    if cur.rowcount == 0:
        raise ValueError("Sổ trực vừa được xử lý bởi yêu cầu khác — tải lại trang để xem trạng thái mới nhất")
    return get_active_by_date(db, truc_date)


def ksv_confirm(db: sqlite3.Connection, truc_date: str, staff_id: int) -> dict:
    rec = get_active_by_date(db, truc_date)
    if rec is None or rec["status"] != "pending_ksv":
        raise ValueError("Sổ trực không ở trạng thái chờ KSV xác nhận")
    if staff_id != rec.get("ksv_id"):
        raise NotAllowedError("Chỉ đúng KSV được chọn cho ngày này mới được xác nhận")
    now = _vn_now()
    cur = db.execute(
        "UPDATE so_truc_records SET status='approved', ksv_decided_by=?, ksv_decided_at=?, reject_reason=NULL, updated_at=? "
        "WHERE id=? AND status='pending_ksv'",
        (staff_id, now, now, rec["id"]),
    )
    db.commit()
    if cur.rowcount == 0:
        raise ValueError("Sổ trực vừa được xử lý bởi yêu cầu khác — tải lại trang để xem trạng thái mới nhất")
    return get_active_by_date(db, truc_date)


def ksv_reject(db: sqlite3.Connection, truc_date: str, staff_id: int, reason: str) -> dict:
    """"Từ chối để sửa" — quay lại draft, GIỮ NGUYÊN gdv1_id/gdv2_id/ksv_id
    để 2 GDV sửa nội dung rồi đẩy lại ĐÚNG KSV này (ép ở forward_to_ksv)."""
    rec = get_active_by_date(db, truc_date)
    if rec is None or rec["status"] != "pending_ksv":
        raise ValueError("Sổ trực không ở trạng thái chờ KSV xác nhận")
    if staff_id != rec.get("ksv_id"):
        raise NotAllowedError("Chỉ đúng KSV được chọn cho ngày này mới được từ chối")
    now = _vn_now()
    cur = db.execute(
        """UPDATE so_truc_records
           SET status='draft', ksv_decided_by=?, ksv_decided_at=?, reject_reason=?,
               initiated_by=NULL, initiated_at=NULL, confirmed_by=NULL, confirmed_at=NULL, updated_at=?
           WHERE id=? AND status='pending_ksv'""",
        (staff_id, now, reason, now, rec["id"]),
    )
    db.commit()
    if cur.rowcount == 0:
        raise ValueError("Sổ trực vừa được xử lý bởi yêu cầu khác — tải lại trang để xem trạng thái mới nhất")
    return get_active_by_date(db, truc_date)


def ksv_cancel(db: sqlite3.Connection, truc_date: str, staff_id: int, reason: str) -> dict:
    """"Từ chối để huỷ" — NGÕ CỤT: phiên này đóng vĩnh viễn ở 'cancelled',
    KHÔNG tự quay lại draft. Muốn làm lại phải tạo phiên trực MỚI cho đúng
    ngày đó (save_draft/forward_to_ksv sẽ tự tạo dòng mới vì get_active_by_date
    không còn thấy dòng này là "đang hoạt động")."""
    rec = get_active_by_date(db, truc_date)
    if rec is None or rec["status"] != "pending_ksv":
        raise ValueError("Sổ trực không ở trạng thái chờ KSV xác nhận")
    if staff_id != rec.get("ksv_id"):
        raise NotAllowedError("Chỉ đúng KSV được chọn cho ngày này mới được huỷ")
    now = _vn_now()
    cur = db.execute(
        """UPDATE so_truc_records
           SET status='cancelled', ksv_decided_by=?, ksv_decided_at=?, reject_reason=?, updated_at=?
           WHERE id=? AND status='pending_ksv'""",
        (staff_id, now, reason, now, rec["id"]),
    )
    db.commit()
    if cur.rowcount == 0:
        raise ValueError("Sổ trực vừa được xử lý bởi yêu cầu khác — tải lại trang để xem trạng thái mới nhất")
    return _get_by_id(db, rec["id"])


def list_gdv_candidates(db: sqlite3.Connection) -> list:
    """Danh sách nhân viên đang hoạt động thuộc Phòng Thanh toán (department
    code 'PAYMENT') để chọn làm GDV1/GDV2 — không giới hạn theo role như
    duty_staff_service.py (bất kỳ ai trong phòng cũng có thể trực), chỉ lọc
    theo phòng ban để không hiện tên người phòng khác."""
    rows = db.execute(
        """SELECT u.id, u.full_name
           FROM user_tttt u
           JOIN departments d ON u.department_id = d.id
           WHERE u.is_active = 1 AND u.is_deleted = 0 AND d.code = 'PAYMENT'
           ORDER BY u.full_name"""
    ).fetchall()
    return [dict(r) for r in rows]


def list_ksv_candidates(db: sqlite3.Connection, feature_code: str = "so_truc.ksv_confirm") -> list:
    """Danh sách người ĐƯỢC PHÉP XUẤT HIỆN trong dropdown chọn KSV — thành
    viên của BẤT KỲ nhóm quyền nào đã được gán feature_code này (không
    hardcode tên nhóm — admin tự gán qua trang Phân quyền theo nhóm), cộng
    thêm mọi Quản trị viên. Chỉ quyết định ai ĐƯỢC CHỌN, không quyết định ai
    được xác nhận/từ chối — sau khi 1 người cụ thể được chọn (`ksv_id`), CHỈ
    đúng người đó mới thao tác được (xem ksv_confirm/ksv_reject/ksv_cancel)."""
    rows = db.execute(
        """SELECT DISTINCT u.id, u.full_name
           FROM user_tttt u
           WHERE u.is_active = 1 AND (
               u.role = 'admin'
               OR u.id IN (
                   SELECT gm.staff_id FROM group_features gf
                   JOIN group_members gm ON gm.group_id = gf.group_id
                   JOIN user_groups g ON g.id = gm.group_id AND g.is_active = 1
                   WHERE gf.feature_code = ?
               )
           )
           ORDER BY u.full_name""",
        (feature_code,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_history(db: sqlite3.Connection, tu_ngay: Optional[str] = None, den_ngay: Optional[str] = None) -> list:
    """Danh sách sổ trực theo khoảng ngày (YYYY-MM-DD, so sánh chuỗi ĐÚNG
    thứ tự thời gian vì định dạng ISO — khác doi_chieu_citad phải parse
    bằng Python do lưu dd/mm/yyyy). 1 ngày có thể có NHIỀU dòng nếu đã từng
    bị huỷ rồi mở phiên mới — sắp `id DESC` phụ để dòng mới nhất lên trước
    trong cùng 1 ngày.

    KHÔNG lọc gì (tu_ngay/den_ngay đều trống) → chỉ trả về ĐÚNG 1 dòng gần
    nhất (yêu cầu người dùng: mặc định chỉ hiện phiên chấm gần nhất, bấm lọc
    theo ngày mới hiện đầy đủ lịch sử) — cùng tinh thần LIMIT-khi-không-lọc
    đã dùng ở doi_soat_citad/history_service.py::list_recon_history."""
    no_filter = not (tu_ngay or den_ngay)
    sql = "SELECT * FROM so_truc_records WHERE 1=1"
    params: list = []
    if tu_ngay:
        sql += " AND truc_date >= ?"
        params.append(tu_ngay)
    if den_ngay:
        sql += " AND truc_date <= ?"
        params.append(den_ngay)
    sql += " ORDER BY truc_date DESC, id DESC"
    if no_filter:
        sql += " LIMIT 1"
    rows = db.execute(sql, params).fetchall()
    return [_row_to_dict(db, r) for r in rows]
