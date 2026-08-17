"""Business logic Sổ trực cuối ngày — Phòng Thanh toán.

Mỗi ngày trực có 2 GDV + 1 KSV (không lấy dữ liệu từ module Phân lịch trực ở
bản này — GDV1/GDV2 CHỌN từ danh sách nhân viên Phòng Thanh toán qua
`list_gdv_candidates()`, lưu bằng `gdv1_id`/`gdv2_id`). Luồng duyệt:

    draft -> pending_ksv -> approved
                          -> draft (KSV từ chối — để sửa HAY để huỷ đều chỉ
                             ĐỀ NGHỊ, quay về draft như nhau, xem ksv_reject()/
                             ksv_cancel(); GDV mới là người quyết sửa tiếp hay
                             bấm "Huỷ phiên trực")
                          -> cancelled (CHỈ GDV tự huỷ qua draft_cancel() —
                             NGÕ CỤT, không tự quay lại draft)

CHỈ 1 GDV là đủ để đẩy sang KSV (không cần GDV còn lại đồng ý trước — đã bỏ
theo yêu cầu nghiệp vụ, KHÁC bản đầu có bước "pending_gdv_confirm" chặn giữa
draft và pending_ksv). Cụ thể:

1. Một trong 2 GDV điền ghi chú + chọn KSV rồi bấm "Chuyển KSV xác nhận"
   (forward_to_ksv) -> ĐI THẲNG "pending_ksv". Đây cũng là lúc "khoá" bản
   ghi: kể từ khi gdv1_id/gdv2_id được set lần đầu, CHỈ 2 tài khoản đó được
   sửa tiếp (save_draft/forward_to_ksv/draft_cancel) — xem `_is_locked()`.
2. GDV còn lại KHÔNG bị chặn/không cần làm gì — nhưng có thể bấm "Xác nhận
   đã xem" (gdv_ack) BẤT KỲ LÚC NÀO (trước hay sau khi người kia đã chuyển
   KSV đều được, kể cả sau khi đã approved) để ghi nhận đã xem qua, hiện dấu
   tick ✓ cạnh tên khi xem lại (`confirmed_by`/`confirmed_at`) — THUẦN GHI
   NHẬN, không chặn/không đổi trạng thái phiên trực. Người bấm "Chuyển KSV
   xác nhận" cũng tự động có dấu tick riêng qua `initiated_by`, không cần
   bấm thêm gdv_ack.
3. KSV — CHỈ đúng tài khoản `ksv_id` đã được chọn mới xác nhận/từ chối được
   (kiểm tra ở đây, KHÔNG chỉ dựa vào feature `so_truc.ksv_confirm` — feature
   đó chỉ xác định AI ĐƯỢC PHÉP xuất hiện trong danh sách chọn KSV, không có
   nghĩa mọi người trong nhóm đều thao tác thay nhau được). Có 2 lựa chọn:
   - "Từ chối để sửa" (ksv_reject) -> quay lại "draft", GIỮ NGUYÊN gdv1_id/
     gdv2_id/ksv_id/ghi_chu — 2 GDV sửa nội dung rồi đẩy lại. Khi đẩy lại,
     forward_to_ksv() BẮT BUỘC giữ nguyên đúng `ksv_id` cũ (không cho đổi
     sang KSV khác — xem check trong forward_to_ksv()).
   - "Từ chối để huỷ" (ksv_cancel) -> CŨNG quay lại "draft" (giống hệt SQL
     của ksv_reject) — chỉ là ĐỀ NGHỊ, KSV không tự đóng phiên được. Khác
     "để sửa" ở chỗ frontend khoá hẳn form sửa khi thấy `ksv_decision=
     'reject_cancel'`, CHỈ còn nút "Huỷ phiên trực" cho GDV — không được
     sửa nội dung rồi đẩy KSV lại như trường hợp "để sửa".
   Cả 2 trường hợp đều ghi `ksv_decision` ('reject_fix'/'reject_cancel') để
   phân biệt (status='draft' giống nhau, không suy ra được cái nào) —
   forward_to_ksv() reset cột này về NULL khi đẩy lại thành công.

GDV cũng tự huỷ được ngay từ draft (không cần đợi KSV, và LÀ CÁCH DUY NHẤT
để 1 phiên thật sự thành 'cancelled') qua `draft_cancel()` — NGÕ CỤT, dùng
2 cột `gdv_decided_by`/`gdv_decided_at` để ghi ai/lúc nào đã huỷ.

4. Sau khi đã 'approved' ("Hoàn thành"), 1 trong 2 GDV HOẶC đúng KSV của
   phiên vẫn mở lại sửa được qua `request_edit()` (chỉ hiện nút "Yêu cầu
   chỉnh sửa" ở tab Lịch sử — xem frontend). Quay về 'draft', nhưng 2 nhánh
   khác hẳn nhau tuỳ ai mở:
   - GDV mở: y hệt ksv_reject cũ — phải sửa rồi "Chuyển KSV xác nhận" lại
     từ đầu, đúng KSV cũ duyệt lại.
   - KSV mở: `ksv_decision='self_edit'` — CHÍNH KSV được tự sửa form rồi tự
     bấm thẳng "Lưu & Hoàn thành" (`ksv_finalize_edit()`) thành 'approved'
     lại luôn, KHÔNG qua vòng GDV đẩy/KSV xác nhận — vì chính KSV là người
     duyệt cuối nên tự sửa + tự chốt được ngay. 2 GDV vẫn có thể bấm "Xác
     nhận phiên trực" (gdv_ack, xem mục 2) sau khi KSV chốt xong để đồng ý
     — THUẦN THÔNG BÁO, không phải phê duyệt.

Tranh chấp 2 GDV bấm "Chuyển KSV xác nhận" gần như cùng lúc TRÊN 1 NGÀY CHƯA
CÓ DÒNG NÀO: `so_truc_records` có UNIQUE INDEX một phần
`ux_so_truc_active_date (truc_date) WHERE status != 'cancelled'` (xem
migrations.py) — chỉ 1 trong 2 câu INSERT thành công, câu kia bắt
IntegrityError rồi đọc lại đúng dòng của người thắng, sau đó cả 2 cùng chạy
tiếp UPDATE ... WHERE id=? AND status='draft' — chỉ 1 request thắng
(rowcount=1), người thua (rowcount=0) được coi là đã "xem" bản ghi vừa được
người kia tạo, trả về y hệt dữ liệu hiện tại (KHÔNG báo lỗi) để frontend tự
hiển thị đúng trạng thái mới nhất — trải nghiệm liền mạch.

KHÔNG tách bảng lịch sử riêng như doi_chieu_citad — bảng này tự thân là lịch
sử (tab "Lịch sử" liệt kê lại các dòng, MỘT ngày có thể có NHIỀU dòng nếu đã
từng bị "huỷ" rồi mở phiên mới). `get_active_by_date()` luôn trả về dòng
CHƯA 'cancelled' MỚI NHẤT của 1 ngày — là dòng "đang làm việc" hiện tại;
None nghĩa là chưa có dòng nào, hoặc mọi dòng cũ đều đã 'cancelled' (ngày đó
coi như trống, ai có quyền cũng tạo phiên mới được).
"""
from __future__ import annotations

import datetime
import json
import sqlite3
from typing import Optional

from backend.database import _vn_now
from backend.services import doi_chieu_citad_service


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
    d["gdv_decided_by_name"] = _name(d.get("gdv_decided_by"))
    # Trực phụ — CHỈ liệt kê để biết, không tham gia luồng duyệt/khoá nào —
    # lưu dạng JSON list id trong 1 cột TEXT (không tách bảng riêng vì không
    # cần tra cứu/join gì thêm ngoài hiện tên). Tên tính lại từ id mỗi lần
    # đọc, giống gdv1_name/gdv2_name — không lưu tên cứng để tránh lệch khi
    # đổi full_name sau này.
    try:
        truc_phu_ids = json.loads(d.get("truc_phu_ids") or "[]")
    except (TypeError, ValueError):
        truc_phu_ids = []
    d["truc_phu_ids"] = truc_phu_ids
    d["truc_phu_names"] = [n for uid in truc_phu_ids if (n := _name(uid))]
    for k in ("initiated_at", "confirmed_at", "ksv_decided_at", "gdv_decided_at", "created_at", "updated_at"):
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


def _insert_new_draft(
    db: sqlite3.Connection, truc_date: str, gdv1_id, gdv2_id, ghi_chu: str, now: str,
    truc_phu_ids: Optional[list] = None,
) -> Optional[dict]:
    """Tạo dòng mới cho ngày chưa có phiên trực đang hoạt động nào (chưa có
    dòng nào, hoặc mọi dòng cũ đã 'cancelled'). An toàn khi 2 người cùng bấm
    gần như đồng thời nhờ UNIQUE INDEX một phần `ux_so_truc_active_date` —
    ai thua tranh chấp bắt IntegrityError rồi đọc lại đúng dòng người thắng."""
    try:
        db.execute(
            """INSERT INTO so_truc_records
               (truc_date, gdv1_id, gdv2_id, ghi_chu, truc_phu_ids, status, created_at, updated_at)
               VALUES (?,?,?,?,?,'draft',?,?)""",
            (truc_date, gdv1_id, gdv2_id, ghi_chu, json.dumps(truc_phu_ids or []), now, now),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
    return get_active_by_date(db, truc_date)


def save_draft(
    db: sqlite3.Connection, truc_date: str, staff_id: int, gdv1_id, gdv2_id, ghi_chu: str,
    truc_phu_ids: Optional[list] = None,
) -> dict:
    """Lưu tạm khi đang ở draft (hoặc chưa có phiên nào đang hoạt động — tạo
    phiên mới). Không cho sửa khi đã qua draft (đang chờ người khác xác
    nhận/KSV duyệt) — phải chờ luồng tự nhiên (KSV từ chối/huỷ) mới sửa lại
    được. Một khi phiên đã có gdv1_id/gdv2_id (đã khoá), chỉ 2 người đó
    được sửa tiếp — `truc_phu_ids` đi theo cùng vòng đời (chỉ liệt kê, không
    có quyền/xác nhận riêng nên không cần khoá tách biệt). KSV vừa "từ chối
    để huỷ" (`ksv_decision='reject_cancel'`) thì KHÔNG được sửa nữa — chỉ
    còn `draft_cancel()`, xem docstring ksv_cancel(). KSV đang TỰ sửa
    (`ksv_decision='self_edit'`, xem request_edit()) cũng chặn GDV sửa qua
    đường này — trong lúc đó form thuộc về KSV, dùng `ksv_finalize_edit()`
    riêng, GDV không được chen vào."""
    now = _vn_now()
    rec = get_active_by_date(db, truc_date)
    if rec is None:
        return _insert_new_draft(db, truc_date, gdv1_id, gdv2_id, ghi_chu, now, truc_phu_ids)
    if rec["status"] != "draft":
        raise ValueError(f"Sổ trực ngày {truc_date} đang ở trạng thái '{rec['status']}', không thể sửa trực tiếp")
    if rec.get("ksv_decision") == "reject_cancel":
        raise ValueError("KSV đã yêu cầu huỷ phiên này — chỉ có thể bấm \"Huỷ phiên trực\", không sửa được nữa")
    if rec.get("ksv_decision") == "self_edit":
        raise ValueError("KSV đang tự chỉnh sửa phiên này — chờ KSV lưu xong")
    if _is_locked(rec) and staff_id not in (rec.get("gdv1_id"), rec.get("gdv2_id")):
        raise NotAllowedError("Chỉ 2 GDV được phân trực ngày này mới được sửa")
    db.execute(
        "UPDATE so_truc_records SET gdv1_id=?, gdv2_id=?, ghi_chu=?, truc_phu_ids=?, updated_at=? WHERE id=?",
        (gdv1_id, gdv2_id, ghi_chu, json.dumps(truc_phu_ids or []), now, rec["id"]),
    )
    db.commit()
    return get_active_by_date(db, truc_date)


def draft_cancel(db: sqlite3.Connection, truc_date: str, staff_id: int, reason: str) -> dict:
    """GDV huỷ hẳn phiên trực đang ở draft (không muốn tiếp tục nữa thì huỷ
    luôn, không cần đợi ai) — NGÕ CỤT giống hệt `ksv_cancel()`: 'cancelled'
    không tự quay lại draft, ai cần làm lại phải để `save_draft`/
    `forward_to_ksv` tự tạo dòng MỚI cho đúng ngày đó (xem
    `get_active_by_date()` — dòng 'cancelled' không còn được coi là "đang
    hoạt động"). Chỉ áp dụng khi đã KHOÁ (có gdv1_id/gdv2_id) — draft trống
    (chưa ai chọn gì) thì không có gì để "huỷ", cứ để trống là được. KSV
    đang TỰ sửa (`ksv_decision='self_edit'`) cũng chặn GDV huỷ qua đây —
    form thuộc về KSV lúc này."""
    rec = get_active_by_date(db, truc_date)
    if rec is None or rec["status"] != "draft":
        raise ValueError(f"Sổ trực ngày {truc_date} không ở trạng thái đang lập")
    if not _is_locked(rec):
        raise ValueError("Chưa có nội dung nào để huỷ")
    if rec.get("ksv_decision") == "self_edit":
        raise ValueError("KSV đang tự chỉnh sửa phiên này — chờ KSV lưu xong")
    if staff_id not in (rec.get("gdv1_id"), rec.get("gdv2_id")):
        raise NotAllowedError("Chỉ 2 GDV được phân trực ngày này mới được huỷ")
    now = _vn_now()
    cur = db.execute(
        """UPDATE so_truc_records
           SET status='cancelled', gdv_decided_by=?, gdv_decided_at=?, reject_reason=?, updated_at=?
           WHERE id=? AND status='draft'""",
        (staff_id, now, reason, now, rec["id"]),
    )
    db.commit()
    if cur.rowcount == 0:
        raise ValueError("Sổ trực vừa được xử lý bởi yêu cầu khác — tải lại trang để xem trạng thái mới nhất")
    return _get_by_id(db, rec["id"])


def forward_to_ksv(
    db: sqlite3.Connection, truc_date: str, staff_id: int,
    gdv1_id, gdv2_id, ghi_chu: str, ksv_id: int,
    truc_phu_ids: Optional[list] = None,
) -> dict:
    """1 GDV bấm "Chuyển KSV xác nhận". Nếu chưa có phiên nào đang hoạt động
    cho ngày này, tự tạo trước rồi mới chuyển — gộp làm 1 thao tác cho gọn
    (không bắt buộc phải bấm "Lưu nháp" trước)."""
    now = _vn_now()
    rec = get_active_by_date(db, truc_date)
    if rec is None:
        rec = _insert_new_draft(db, truc_date, gdv1_id, gdv2_id, ghi_chu, now, truc_phu_ids)

    if rec.get("ksv_decision") == "reject_cancel":
        raise ValueError("KSV đã yêu cầu huỷ phiên này — chỉ có thể bấm \"Huỷ phiên trực\", không đẩy lại được nữa")
    if rec.get("ksv_decision") == "self_edit":
        raise ValueError("KSV đang tự chỉnh sửa phiên này — chờ KSV lưu xong")
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
    # ĐI THẲNG "pending_ksv" — không còn bước chờ GDV còn lại đồng ý (bỏ theo
    # yêu cầu nghiệp vụ: 1 GDV là đủ để đẩy sang KSV).
    db.execute(
        """UPDATE so_truc_records
           SET status='pending_ksv', gdv1_id=?, gdv2_id=?, ghi_chu=?, truc_phu_ids=?,
               initiated_by=?, initiated_at=?, ksv_id=?, ksv_decision=NULL, updated_at=?
           WHERE id=? AND status='draft'""",
        (gdv1_id, gdv2_id, ghi_chu, json.dumps(truc_phu_ids or []), staff_id, now, ksv_id, now, rec["id"]),
    )
    db.commit()
    # rowcount==0: thua tranh chấp (người khác vừa initiate) HOẶC phiên này đã
    # qua draft từ trước — cả 2 trường hợp đều trả về bản ghi HIỆN TẠI, không
    # báo lỗi, để frontend tự hiển thị đúng màn hình theo status thật.
    return get_active_by_date(db, truc_date)


def gdv_ack(db: sqlite3.Connection, truc_date: str, staff_id: int) -> dict:
    """GDV còn lại (không phải người đã bấm "Chuyển KSV xác nhận") bấm "Xác
    nhận đã xem" — THUẦN GHI NHẬN cho biết ai đã xem qua nội dung, hiện dấu
    tick ✓ cạnh tên khi xem lại (`confirmed_by`/`confirmed_at`). KHÔNG chặn/
    không đổi trạng thái phiên trực gì cả — bấm được bất kỳ lúc nào (trước
    hay sau khi đã chuyển KSV đều được, kể cả sau khi đã approved), miễn là
    phiên đã tồn tại (không phải draft trống chưa ai lập gì)."""
    rec = get_active_by_date(db, truc_date)
    if rec is None:
        raise ValueError(f"Chưa có sổ trực nào cho ngày {truc_date}")
    if staff_id not in (rec.get("gdv1_id"), rec.get("gdv2_id")):
        raise NotAllowedError("Chỉ 2 GDV được phân trực ngày này mới xác nhận được")
    now = _vn_now()
    db.execute(
        "UPDATE so_truc_records SET confirmed_by=?, confirmed_at=? WHERE id=?",
        (staff_id, now, rec["id"]),
    )
    db.commit()
    return get_active_by_date(db, truc_date)


def check_citad_status(db: sqlite3.Connection, truc_date: str) -> dict:
    """Đối chiếu CITAD của đúng ngày trực này đã có bản lưu khớp (hết chênh
    lệch) chưa — dùng để CẢNH BÁO (không chặn cứng) GDV/KSV trước khi họ bấm
    xác nhận, vì phiên trực và đối chiếu CITAD là 2 module tách biệt, không
    có gì tự động đảm bảo đối chiếu đã xong trước khi ai đó xác nhận sổ trực.
    `truc_date` (YYYY-MM-DD) → `ngay` (dd/mm/yyyy, định dạng cột lưu ở
    doi_chieu_citad_sessions) rồi tái dùng
    `doi_chieu_citad_service.get_reconciliation_status()` — không tính lại
    logic chênh lệch riêng ở đây, tránh 2 nơi tính ra 2 kết quả khác nhau."""
    ngay = datetime.date.fromisoformat(truc_date).strftime("%d/%m/%Y")
    return doi_chieu_citad_service.get_reconciliation_status(db, ngay)


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
    để 2 GDV sửa nội dung rồi đẩy lại ĐÚNG KSV này (ép ở forward_to_ksv).
    ksv_decision='reject_fix' — frontend dựa vào đây để biết vẫn cho sửa +
    đẩy lại (khác 'reject_cancel', xem ksv_cancel())."""
    rec = get_active_by_date(db, truc_date)
    if rec is None or rec["status"] != "pending_ksv":
        raise ValueError("Sổ trực không ở trạng thái chờ KSV xác nhận")
    if staff_id != rec.get("ksv_id"):
        raise NotAllowedError("Chỉ đúng KSV được chọn cho ngày này mới được từ chối")
    now = _vn_now()
    cur = db.execute(
        """UPDATE so_truc_records
           SET status='draft', ksv_decided_by=?, ksv_decided_at=?, reject_reason=?,
               ksv_decision='reject_fix',
               initiated_by=NULL, initiated_at=NULL, confirmed_by=NULL, confirmed_at=NULL, updated_at=?
           WHERE id=? AND status='pending_ksv'""",
        (staff_id, now, reason, now, rec["id"]),
    )
    db.commit()
    if cur.rowcount == 0:
        raise ValueError("Sổ trực vừa được xử lý bởi yêu cầu khác — tải lại trang để xem trạng thái mới nhất")
    return get_active_by_date(db, truc_date)


def ksv_cancel(db: sqlite3.Connection, truc_date: str, staff_id: int, reason: str) -> dict:
    """"Từ chối để huỷ" — KSV KHÔNG tự huỷ thẳng được, chỉ YÊU CẦU huỷ: quay
    lại 'draft' y hệt ksv_reject() (giữ nguyên gdv1_id/gdv2_id/ksv_id, reset
    initiated_by/confirmed_by), để 1 TRONG 2 GDV được phân trực tự bấm "Huỷ
    phiên trực" (draft_cancel()) thật sự đóng phiên — quyền huỷ luôn thuộc
    về GDV, KSV chỉ đề nghị. `ksv_decision='reject_cancel'` (khác 'reject_fix'
    của ksv_reject()) — frontend dựa vào đây để KHOÁ HẲN form sửa, GDV KHÔNG
    được sửa nội dung rồi đẩy KSV lại như trường hợp "để sửa", chỉ còn nút
    "Huỷ phiên trực"."""
    rec = get_active_by_date(db, truc_date)
    if rec is None or rec["status"] != "pending_ksv":
        raise ValueError("Sổ trực không ở trạng thái chờ KSV xác nhận")
    if staff_id != rec.get("ksv_id"):
        raise NotAllowedError("Chỉ đúng KSV được chọn cho ngày này mới được yêu cầu huỷ")
    now = _vn_now()
    cur = db.execute(
        """UPDATE so_truc_records
           SET status='draft', ksv_decided_by=?, ksv_decided_at=?, reject_reason=?,
               ksv_decision='reject_cancel',
               initiated_by=NULL, initiated_at=NULL, confirmed_by=NULL, confirmed_at=NULL, updated_at=?
           WHERE id=? AND status='pending_ksv'""",
        (staff_id, now, reason, now, rec["id"]),
    )
    db.commit()
    if cur.rowcount == 0:
        raise ValueError("Sổ trực vừa được xử lý bởi yêu cầu khác — tải lại trang để xem trạng thái mới nhất")
    return get_active_by_date(db, truc_date)


def request_edit(db: sqlite3.Connection, truc_date: str, staff_id: int, reason: str) -> dict:
    """1 trong 2 GDV chính HOẶC đúng KSV của phiên đã "Hoàn thành" (approved)
    mở lại để sửa — CHỈ dùng được từ `status='approved'` (khác ksv_reject/
    ksv_cancel dùng cho pending_ksv). Quay lại 'draft', GIỮ NGUYÊN gdv1_id/
    gdv2_id/ksv_id, reset initiated_by/confirmed_by (chu kỳ mới).

    2 nhánh khác hẳn nhau tuỳ AI mở lại:
    - GDV (gdv1_id/gdv2_id) mở lại: y hệt luồng ksv_reject cũ — phải SỬA rồi
      "Chuyển KSV xác nhận" lại từ đầu, đúng KSV cũ duyệt lại (ép ở
      forward_to_ksv). Ghi vào gdv_decided_by/at (khác ksv_decided_by/at —
      không phải KSV quyết định). Xoá sạch ksv_decided_by/at/ksv_decision
      cũ (nếu còn sót từ chu kỳ trước) để không lẫn với thông tin GDV vừa
      ghi — tránh _so_truc_filter() ở dashboard.py hiểu nhầm đây là "KSV vừa
      từ chối" (điều kiện đó cần ksv_decided_by IS NOT NULL).
    - KSV (ksv_id) mở lại: `ksv_decision='self_edit'` — ĐƯỢC TỰ SỬA form
      (xem `_render_draft_form()` frontend, nhánh is_ksv_self_edit) rồi TỰ
      bấm thẳng thành 'approved' qua `ksv_finalize_edit()`, KHÔNG cần GDV
      đẩy/KSV xác nhận lại vòng nữa (khác ksv_reject/ksv_cancel bình
      thường). Ghi ksv_decided_by/at + reject_reason (đúng field đang
      dùng chung để hiện banner + để _so_truc_filter() TỰ ĐỘNG báo cho cả
      2 GDV qua badge "Sổ trực chờ xử lý" — không cần thêm code báo riêng,
      khớp nhánh thứ 3 đã có sẵn ở dashboard.py). Xoá sạch gdv_decided_by/at
      cũ cùng lý do đối xứng."""
    rec = get_active_by_date(db, truc_date)
    if rec is None or rec["status"] != "approved":
        raise ValueError("Chỉ mở lại sửa được phiên trực đã Hoàn thành")
    now = _vn_now()
    if staff_id == rec.get("ksv_id"):
        cur = db.execute(
            """UPDATE so_truc_records
               SET status='draft', reject_reason=?,
                   ksv_decided_by=?, ksv_decided_at=?, ksv_decision='self_edit',
                   gdv_decided_by=NULL, gdv_decided_at=NULL,
                   initiated_by=NULL, initiated_at=NULL, confirmed_by=NULL, confirmed_at=NULL,
                   updated_at=?
               WHERE id=? AND status='approved'""",
            (reason, staff_id, now, now, rec["id"]),
        )
    elif staff_id in (rec.get("gdv1_id"), rec.get("gdv2_id")):
        cur = db.execute(
            """UPDATE so_truc_records
               SET status='draft', reject_reason=?,
                   gdv_decided_by=?, gdv_decided_at=?,
                   ksv_decided_by=NULL, ksv_decided_at=NULL, ksv_decision=NULL,
                   initiated_by=NULL, initiated_at=NULL, confirmed_by=NULL, confirmed_at=NULL,
                   updated_at=?
               WHERE id=? AND status='approved'""",
            (reason, staff_id, now, now, rec["id"]),
        )
    else:
        raise NotAllowedError("Chỉ 2 GDV hoặc đúng KSV của phiên này mới được yêu cầu chỉnh sửa")
    db.commit()
    if cur.rowcount == 0:
        raise ValueError("Sổ trực vừa được xử lý bởi yêu cầu khác — tải lại trang để xem trạng thái mới nhất")
    return get_active_by_date(db, truc_date)


def ksv_finalize_edit(
    db: sqlite3.Connection, truc_date: str, staff_id: int,
    gdv1_id, gdv2_id, ghi_chu: str, truc_phu_ids: Optional[list] = None,
) -> dict:
    """KSV tự sửa xong (sau `request_edit()` của chính họ, `ksv_decision=
    'self_edit'`) — bấm thẳng thành 'approved', KHÔNG qua forward_to_ksv/
    ksv_confirm lại. Chỉ đúng KSV đã tự mở phiên này mới gọi được — GDV
    không dùng hàm này (họ có save_draft/forward_to_ksv riêng)."""
    rec = get_active_by_date(db, truc_date)
    if rec is None or rec["status"] != "draft" or rec.get("ksv_decision") != "self_edit":
        raise ValueError("Phiên này không ở trạng thái KSV đang tự chỉnh sửa")
    if staff_id != rec.get("ksv_id"):
        raise NotAllowedError("Chỉ đúng KSV đã mở phiên này mới được lưu")
    if not gdv1_id or not gdv2_id:
        raise ValueError("Phải chọn đủ 2 GDV trực")
    if gdv1_id == gdv2_id:
        raise ValueError("GDV 1 và GDV 2 không được trùng nhau")
    now = _vn_now()
    cur = db.execute(
        """UPDATE so_truc_records
           SET status='approved', gdv1_id=?, gdv2_id=?, ghi_chu=?, truc_phu_ids=?,
               ksv_decided_by=?, ksv_decided_at=?, ksv_decision=NULL, reject_reason=NULL,
               updated_at=?
           WHERE id=? AND status='draft'""",
        (gdv1_id, gdv2_id, ghi_chu, json.dumps(truc_phu_ids or []), staff_id, now, now, rec["id"]),
    )
    db.commit()
    if cur.rowcount == 0:
        raise ValueError("Sổ trực vừa được xử lý bởi yêu cầu khác — tải lại trang để xem trạng thái mới nhất")
    return get_active_by_date(db, truc_date)


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
