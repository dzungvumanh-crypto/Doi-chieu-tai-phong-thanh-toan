"""Business logic Đối chiếu CITAD ↔ PaymentHub — Phòng QLTK Nostro, Vostro.

Song song với `doi_chieu_citad_service.py` (Phòng Thanh toán), KHÔNG sửa file
đó, KHÔNG import bất kỳ hàm nào từ đó nữa. Extension Chrome là gói RIÊNG
(`extension_citad_nv/`, không chung với `extension_citad/` của Phòng Thanh
toán) nên `build_extension_zip`/`get_extension_latest_version` đóng gói thư
mục riêng đó.

Mã kết nối Extension CŨNG đã tách RIÊNG hoàn toàn (bảng
`doi_chieu_citad_nostro_extension_tokens`, không còn dùng chung
`doi_chieu_citad_extension_tokens`) — bản đầu dùng chung 1 bảng theo
staff_id, hoá ra tạo mã mới ở module này (INSERT ... ON CONFLICT(staff_id)
DO UPDATE) sẽ ÂM THẦM THU HỒI mã module kia của cùng 1 người, gây 403 khi 1
người dùng song song cả 2 Extension (phát hiện thực tế lúc test). Từ nay 2
phòng tạo/thu hồi mã độc lập, không ảnh hưởng lẫn nhau.

Buffer CITAD/PaymentHub và bảng session/history đều là bản sao RIÊNG (khoá
theo `ky` — kỳ đối chiếu Từ ngày-Đến ngày, không phải `ngay` đơn — vì Phòng
QLTK Nostro, Vostro có thể chấm gộp nhiều ngày liên tiếp cùng lúc).

Công thức đối chiếu (khác hẳn Phòng Thanh toán — không có IH/IL, không có
chiều Đến, không có ngoại tệ, chỉ 1 nguồn HUB nên chỉ 1 cặp Chênh lệch):
  Tổng CITAD(gtt) = Σ cD[cong]["gtt"] qua 5 cổng; tương tự Tổng CITAD(gtc).
  Tổng HUB(gtt) = phD["gtt"]; Tổng HUB(gtc) = phD["gtc_truoc"] + phD["gtc_tu"].
  Chênh lệch(gtt|gtc) = Tổng CITAD − Tổng HUB.
"""
from __future__ import annotations

import calendar
import hashlib
import io
import json
import secrets
import threading
import sqlite3
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal

from backend.core.config import BASE_DIR
from backend.database import _vn_now
from backend.schemas.doi_chieu_citad_nostro import ExportIn, CONGS, CONG_LABEL, LOAI_CITAD

EXTENSION_DIR = BASE_DIR / "extension_citad_nv"


# ── Mã kết nối Extension — RIÊNG cho Phòng QLTK Nostro, Vostro (bảng
# doi_chieu_citad_nostro_extension_tokens, tách hẳn khỏi bảng của Phòng
# Thanh toán — xem docstring đầu file) ─────────────────────────────────────
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_extension_token(db: sqlite3.Connection, staff_id: int) -> str:
    """Tạo token mới cho staff_id, GHI ĐÈ token cũ nếu có (thu hồi tự động,
    CHỈ ảnh hưởng module N&V — không đụng token của Phòng Thanh toán vì
    khác bảng hoàn toàn). Trả về token PLAINTEXT — CHỈ lần này."""
    token = secrets.token_urlsafe(32)
    now = _vn_now()
    db.execute(
        """INSERT INTO doi_chieu_citad_nostro_extension_tokens (staff_id, token_hash, created_at, last_used_at)
           VALUES (?,?,?,NULL)
           ON CONFLICT(staff_id) DO UPDATE SET token_hash=excluded.token_hash,
                                                created_at=excluded.created_at,
                                                last_used_at=NULL""",
        (staff_id, _hash_token(token), now),
    )
    db.commit()
    return token


_LAST_USED_THROTTLE_SECONDS = 300


def resolve_extension_token(db: sqlite3.Connection, token: str) -> tuple[int, str] | None:
    """Token hợp lệ -> (staff_id, username). Token sai/rỗng/đã bị thu hồi ->
    None. Chỉ ghi lại last_used_at nếu đã "cũ" hơn _LAST_USED_THROTTLE_SECONDS
    (giảm ghi DB — cùng lý do với bản gốc của Phòng Thanh toán)."""
    if not token:
        return None
    row = db.execute(
        """SELECT t.staff_id, t.last_used_at, u.username FROM doi_chieu_citad_nostro_extension_tokens t
           JOIN user_tttt u ON u.id = t.staff_id AND u.is_active = 1
           WHERE t.token_hash = ?""",
        (_hash_token(token),),
    ).fetchone()
    if not row:
        return None
    now = _vn_now()
    last_used = row["last_used_at"]
    stale = last_used is None or (
        now - datetime.fromisoformat(str(last_used))
    ).total_seconds() >= _LAST_USED_THROTTLE_SECONDS
    if stale:
        db.execute(
            "UPDATE doi_chieu_citad_nostro_extension_tokens SET last_used_at=? WHERE staff_id=?",
            (now, row["staff_id"]),
        )
        db.commit()
    return row["staff_id"], row["username"]


def revoke_extension_token(db: sqlite3.Connection, staff_id: int) -> None:
    db.execute("DELETE FROM doi_chieu_citad_nostro_extension_tokens WHERE staff_id=?", (staff_id,))
    db.commit()


def get_extension_token_status(db: sqlite3.Connection, staff_id: int) -> dict:
    row = db.execute(
        "SELECT created_at, last_used_at FROM doi_chieu_citad_nostro_extension_tokens WHERE staff_id=?",
        (staff_id,),
    ).fetchone()
    if not row:
        return {"connected": False, "created_at": None, "last_used_at": None}
    return {
        "connected": True,
        "created_at": str(row["created_at"]) if row["created_at"] else None,
        "last_used_at": str(row["last_used_at"]) if row["last_used_at"] else None,
    }


def build_extension_zip() -> bytes:
    """Nén `extension_citad_nv/` — gói Extension RIÊNG của Phòng QLTK
    Nostro, Vostro (không chung `extension_citad/` của Phòng Thanh toán).
    Cùng nguyên tắc đóng gói với `doi_chieu_citad_service.build_extension_zip`
    (file nằm NGAY GỐC zip, không bọc thêm 1 lớp thư mục — xem docstring ở
    đó để biết lý do, tránh lỗi "Manifest file is missing" khi Load unpacked)."""
    if not EXTENSION_DIR.is_dir():
        raise FileNotFoundError(f"Không tìm thấy thư mục {EXTENSION_DIR}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(EXTENSION_DIR.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=path.relative_to(EXTENSION_DIR))
    return buf.getvalue()


def get_extension_latest_version() -> str:
    manifest_path = EXTENSION_DIR / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return data["version"]

# ── CITAD / PaymentHub buffer (in-memory) — tách theo owner (username) ────
# Bản sao RIÊNG của Phòng QLTK Nostro, Vostro — không dùng chung dict với
# `doi_chieu_citad_service._citad_buffer`/`_ph_buffer` (khác cấu trúc dữ
# liệu: không có cur/chieu, có loai="gtc_truoc"/"gtc_tu" bên HUB). Cùng lý do
# cần khoá (_buffer_lock) như bản gốc — nhiều thread FastAPI threadpool có
# thể đọc/ghi đồng thời (xem giải thích chi tiết trong doi_chieu_citad_service.py).
_buffer_lock = threading.Lock()
_citad_buffer: dict[str, dict] = {}
_ph_buffer: dict[str, dict] = {}


def buffer_save_citad(owner: str, data: dict) -> None:
    with _buffer_lock:
        _citad_buffer.setdefault(owner, {})[data["key"]] = data


def buffer_get_citad(owner: str) -> list:
    with _buffer_lock:
        return list(_citad_buffer.get(owner, {}).values())


def buffer_clear_citad(owner: str) -> None:
    with _buffer_lock:
        _citad_buffer.pop(owner, None)


def buffer_save_ph(owner: str, items: list) -> None:
    with _buffer_lock:
        bucket = _ph_buffer.setdefault(owner, {})
        for item in items:
            bucket[item["key"]] = item


def buffer_get_ph(owner: str) -> list:
    with _buffer_lock:
        return list(_ph_buffer.get(owner, {}).values())


def buffer_clear_ph(owner: str) -> None:
    with _buffer_lock:
        _ph_buffer.pop(owner, None)


# ── Session theo kỳ đối chiếu — NHIỀU bảng độc lập/kỳ, mỗi bảng 1 chủ
# (`created_by`), không ai ghi đè ai — mirror mô hình cuối của Phòng Thanh
# toán (`doi_chieu_citad_service.py`, xem migration rebuild
# `doi_chieu_citad_nostro_sessions` trong `backend/db/migrations.py` ngày
# 11/09/2026). KHÁC PTT: không có `status` draft/final — Nostro chưa có nhu
# cầu "chốt bản cuối"/khoá, nên bỏ hẳn khái niệm đó cho gọn (thêm sau không
# khó, đã có sẵn khung `session_id`). ─────────────────────────────────────
class SessionForbiddenError(Exception):
    """Không phải chủ bảng (created_by) nên không được sửa/xoá bảng này."""


class SessionNotFoundError(Exception):
    """Không có bảng nào khớp session_id — đã bị xoá hoặc id sai."""


def session_save(
    db: sqlite3.Connection, ky: str, staff_id: int, data: dict, session_id: int | None = None
) -> int:
    """`session_id=None` → LUÔN tạo bảng MỚI của `staff_id` (không đè lên bất
    kỳ bảng nào đã có, kể cả bảng KHÁC của chính họ cùng kỳ — 1 người có thể
    có nhiều bảng độc lập/kỳ, giống PTT). `session_id` có giá trị → đang lưu
    tiếp vào ĐÚNG bảng đó — CHỈ chủ bảng (`created_by`) mới sửa được (không
    có ngoại lệ "sửa vài field" như napas_only của PTT — Nostro không có
    nguồn góp riêng tương tự Napas/PSS-MDP).

    Trả về `session_id` THẬT SỰ đã lưu (mới tạo hoặc lưu tiếp) — frontend cần
    để gắn `view_state["session_id"]` cho lần lưu kế tiếp."""
    if session_id is None:
        owner = staff_id
    else:
        row = db.execute(
            "SELECT ky, created_by FROM doi_chieu_citad_nostro_sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise SessionNotFoundError("Không tìm thấy bảng để lưu tiếp — có thể đã bị xoá.")
        if row["ky"] != ky:
            raise ValueError("Kỳ đối chiếu không khớp với bảng đang lưu tiếp.")
        owner = row["created_by"]
        if owner != staff_id:
            raise SessionForbiddenError("Chỉ người lập bảng mới được sửa bảng này.")

    now = _vn_now()
    data_json = json.dumps(data)
    if session_id is None:
        cur = db.execute(
            """INSERT INTO doi_chieu_citad_nostro_sessions (ky, data, updated_at, updated_by, created_by)
               VALUES (?,?,?,?,?)""",
            (ky, data_json, now, staff_id, owner),
        )
        new_session_id = cur.lastrowid
    else:
        db.execute(
            "UPDATE doi_chieu_citad_nostro_sessions SET data=?, updated_at=?, updated_by=? WHERE id=?",
            (data_json, now, staff_id, session_id),
        )
        new_session_id = session_id

    # Gộp lưu liên tiếp vào CÙNG 1 dòng lịch sử — chỉ khi cùng người lưu liên
    # tiếp VÀO ĐÚNG bảng này (giống PTT) — tránh phình lịch sử khi bấm Lưu
    # nhiều lần liên tục mà không đổi bảng.
    last_hist = db.execute(
        "SELECT id, staff_id FROM doi_chieu_citad_nostro_history WHERE session_id=? ORDER BY id DESC LIMIT 1",
        (new_session_id,),
    ).fetchone()
    if last_hist and last_hist["staff_id"] == staff_id:
        db.execute(
            "UPDATE doi_chieu_citad_nostro_history SET data=?, created_at=? WHERE id=?",
            (data_json, now, last_hist["id"]),
        )
    else:
        db.execute(
            """INSERT INTO doi_chieu_citad_nostro_history (ky, session_id, staff_id, data, created_at)
               VALUES (?,?,?,?,?)""",
            (ky, new_session_id, staff_id, data_json, now),
        )
    db.commit()
    return new_session_id


def session_get(db: sqlite3.Connection, session_id: int) -> dict | None:
    """Đúng 1 bảng theo `session_id` — đọc được bởi BẤT KỲ ai có quyền vào
    menu (chia sẻ xem, giống PTT), chỉ sửa/xoá mới bị giới hạn theo chủ
    bảng."""
    row = db.execute(
        """SELECT s.data, s.created_by, u.username AS created_by_username
           FROM doi_chieu_citad_nostro_sessions s
           LEFT JOIN user_tttt u ON u.id = s.created_by
           WHERE s.id=?""",
        (session_id,),
    ).fetchone()
    if not row:
        return None
    data = json.loads(row["data"])
    data["_meta_session_id"] = session_id
    data["_meta_created_by"] = row["created_by"]
    data["_meta_created_by_username"] = row["created_by_username"]
    return data


def session_delete(db: sqlite3.Connection, session_id: int, staff_id: int, is_admin: bool) -> None:
    """Xoá ĐÚNG 1 bảng (`session_id`) — chủ bảng (`created_by == staff_id`)
    tự xoá được bảng của mình, HOẶC admin xoá được bảng của bất kỳ ai (khác
    PTT — PTT chỉ có chủ bảng tự xoá, không có nhánh admin riêng; Nostro
    chọn thêm nhánh admin theo xác nhận thực tế 11/09/2026). Không đụng
    được bảng người khác nếu không phải admin, dù cùng kỳ."""
    row = db.execute(
        "SELECT created_by FROM doi_chieu_citad_nostro_sessions WHERE id=?", (session_id,)
    ).fetchone()
    if row is None:
        raise SessionNotFoundError("Không tìm thấy bảng để xoá — có thể đã bị xoá trước đó.")
    if row["created_by"] != staff_id and not is_admin:
        raise SessionForbiddenError("Chỉ người lập bảng (hoặc Admin) mới được xoá bảng này.")
    db.execute("DELETE FROM doi_chieu_citad_nostro_sessions WHERE id=?", (session_id,))
    db.commit()


def session_list(db: sqlite3.Connection) -> list:
    """Sắp xếp bằng Python theo NGÀY BẮT ĐẦU của kỳ. `ORDER BY ky DESC` trong
    SQL là so sánh CHUỖI "dd/mm/yyyy-..." nên sai thứ tự thời gian
    ("01/12/2026" < "05/01/2026" theo chuỗi nhưng đến sau) — đúng lý do
    `_parse_ky_start()` tồn tại."""
    rows = db.execute(
        "SELECT ky, data FROM doi_chieu_citad_nostro_sessions",
    ).fetchall()
    parsed = [(_parse_ky_start(r["ky"]) or datetime.min, json.loads(r["data"])) for r in rows]
    parsed.sort(key=lambda t: t[0], reverse=True)
    return [data for _, data in parsed]


def _nv(v) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except Exception:
        return 0.0


def _dec(v) -> Decimal:
    """Chuyển sang Decimal CHÍNH XÁC TUYỆT ĐỐI — cùng cơ chế và cùng lý do
    với `_dec()` trong `frontend/pages/doi_chieu_citad.py`/`_status_dec()`
    trong `doi_chieu_citad_service.py` (module gốc Phòng Thanh toán): đi qua
    `str(v)` trước khi vào Decimal để tránh mở khai triển nhị phân của
    float (`Decimal(516.6)` ra `Decimal('516.5999...')`, còn
    `Decimal(str(516.6))` ra đúng `Decimal('516.6')`). Dùng cho phép CỘNG
    DỒN 5 cổng ở `compute_totals()` — cộng nhiều số thực có thể sinh dư nhị
    phân dù về bản chất đã khớp tuyệt đối (bug thật đã xảy ra ở module gốc
    25/08/2026: hiện "+0,0078125" dù CITAD gốc cộng đúng khớp PaymentHub).
    KHÔNG dùng để thay `_nv()` ở những chỗ chỉ hiển thị 1 giá trị nhập tay
    (không cộng dồn) — không có rủi ro dư nhị phân ở đó."""
    try:
        return Decimal(str(v)) if v not in (None, "") else Decimal(0)
    except Exception:
        return Decimal(0)


def compute_totals(sess: dict) -> tuple[dict, dict]:
    """Tổng CITAD (5 cổng) và Tổng HUB, riêng gtt/gtc — công thức duy nhất,
    dùng chung cho `is_reconciliation_matched()` và `build_xlsx_nostro()` để
    luôn khớp nhau (frontend tính lại y hệt ở `_compute_totals()` của
    `frontend/pages/doi_chieu_citad_nostro.py` — giữ đồng bộ 3 nơi vì
    frontend không gọi được thẳng service backend, khác tiến trình).

    Trả về Decimal (không phải float) — cộng bằng `_dec()` để so sánh khớp/
    lệch ở `is_reconciliation_matched()` chính xác tuyệt đối. Nơi cần số
    thực để ghi ra Excel/hiển thị thì tự `float()` hoá khi dùng."""
    cD = sess.get("cD", {}) or {}
    phD = sess.get("phD", {}) or {}
    ci = {loai: {"soMon": Decimal(0), "soTien": Decimal(0)} for loai in LOAI_CITAD}
    for cong in CONGS:
        cong_data = cD.get(cong, {}) or {}
        for loai in LOAI_CITAD:
            src = cong_data.get(loai, {}) or {}
            ci[loai]["soMon"] += _dec(src.get("soMon", 0))
            ci[loai]["soTien"] += _dec(src.get("soTien", 0))
    gtt_hub = phD.get("gtt", {}) or {}
    gtc_truoc = phD.get("gtc_truoc", {}) or {}
    gtc_tu = phD.get("gtc_tu", {}) or {}
    hub = {
        "gtt": {"soMon": _dec(gtt_hub.get("soMon", 0)), "soTien": _dec(gtt_hub.get("soTien", 0))},
        "gtc": {
            "soMon": _dec(gtc_truoc.get("soMon", 0)) + _dec(gtc_tu.get("soMon", 0)),
            "soTien": _dec(gtc_truoc.get("soTien", 0)) + _dec(gtc_tu.get("soTien", 0)),
        },
    }
    return ci, hub


def is_reconciliation_matched(sess: dict) -> bool:
    ci, hub = compute_totals(sess)
    return all(
        ci[loai]["soMon"] == hub[loai]["soMon"] and ci[loai]["soTien"] == hub[loai]["soTien"]
        for loai in LOAI_CITAD
    )


def get_reconciliation_status(db: sqlite3.Connection, ky: str) -> dict:
    """Hiện KHÔNG có nơi nào gọi hàm này (đã kiểm — khác PTT, nơi
    `so_truc_service.py` có gọi bản tương ứng) — vẫn sửa đúng theo mô hình
    nhiều bảng/kỳ để không để lại hàm hỏng ngầm (gọi `session_get(db, ky)`
    cũ sẽ lỗi vì `session_get()` giờ nhận `session_id`, không nhận `ky`).
    "matched" = CÓ ÍT NHẤT 1 bảng của kỳ này khớp — mirror ngữ nghĩa "any"
    của PTT, bỏ điều kiện status='final' vì Nostro không có khái niệm đó."""
    rows = db.execute(
        "SELECT id FROM doi_chieu_citad_nostro_sessions WHERE ky=?", (ky,)
    ).fetchall()
    sessions = [session_get(db, r["id"]) for r in rows]
    return {
        "exists": bool(sessions),
        "matched": any(is_reconciliation_matched(s) for s in sessions if s),
    }


def _parse_ky_start(ky: str) -> datetime | None:
    """`ky` = "dd/mm/yyyy-dd/mm/yyyy" — sắp xếp/lọc theo NGÀY BẮT ĐẦU (vế
    trước dấu '-'). Chuỗi text nên không so sánh được trực tiếp theo thứ tự
    thời gian, giống lý do `_parse_ngay()` trong doi_chieu_citad_service.py."""
    try:
        tu = ky.split("-", 1)[0].strip()
        return datetime.strptime(tu, "%d/%m/%Y")
    except Exception:
        return None


def _parse_ddmmyyyy(s: str) -> datetime | None:
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y")
    except Exception:
        return None


def _parse_ky_range(ky: str) -> tuple[datetime, datetime] | None:
    """"dd/mm/yyyy-dd/mm/yyyy" -> (ngày bắt đầu, ngày kết thúc). Ngày đơn
    (tu=den) hợp lệ như kỳ nhiều ngày bình thường."""
    parts = ky.split("-")
    if len(parts) != 2:
        return None
    start, end = _parse_ddmmyyyy(parts[0]), _parse_ddmmyyyy(parts[1])
    if not start or not end:
        return None
    return (start, end) if start <= end else (end, start)


def normalize_ky(ky: str) -> str:
    """Chuẩn hoá + kiểm tra `ky` trước khi lưu, ném ValueError nếu sai.

    Không kiểm thì ô ngày bị xoá trắng sẽ lưu thành `ky = "-"`: dòng đó
    VÔ HÌNH ở tab Lịch sử (`_parse_ky_start()` trả None nên bị `continue`)
    nhưng vẫn chiếm PRIMARY KEY trong bảng, và UI không còn đường nào xoá.
    Chuẩn hoá luôn thứ tự 2 vế để "05/08/2026-01/08/2026" và
    "01/08/2026-05/08/2026" không thành 2 bản ghi rời của cùng một kỳ."""
    rng = _parse_ky_range(ky or "")
    if not rng:
        raise ValueError(
            "Kỳ đối chiếu không hợp lệ — cần đủ Từ ngày và Đến ngày dạng dd/mm/yyyy."
        )
    return f"{rng[0].strftime('%d/%m/%Y')}-{rng[1].strftime('%d/%m/%Y')}"


def check_period_overlap(db: sqlite3.Connection, tu_ngay: str, den_ngay: str, exclude_ky: str | None = None) -> dict:
    """Kiểm tra kỳ [tu_ngay, den_ngay] SẮP lưu có CHỒNG lên kỳ nào đã lưu
    trước đó không, và có HỞ khoảng trống giữa kỳ liền trước gần nhất với kỳ
    này không — cả 2 đều là lỗi dễ mắc khi chấm gộp nhiều ngày (chồng =
    tính trùng, hở = bỏ sót ngày không ai chấm). Chỉ CẢNH BÁO, không chặn
    lưu — quyết định cuối vẫn ở người dùng (`exclude_ky`: bỏ qua chính kỳ
    đang sửa khi lưu đè lại kỳ cũ, tránh tự báo trùng với chính nó)."""
    new_start, new_end = _parse_ddmmyyyy(tu_ngay), _parse_ddmmyyyy(den_ngay)
    if not new_start or not new_end:
        return {"overlaps": [], "gap_before": None}
    if new_start > new_end:
        new_start, new_end = new_end, new_start

    # `ky` lưu trong DB LUÔN đã qua normalize_ky() (thứ tự start<=end, xem
    # session_save()/API save_session) — nhưng `exclude_ky` gọi tới đây lại
    # là do FRONTEND tự ghép "{tu_ngay_input.value}-{den_ngay_input.value}"
    # (xem do_save_session() ở frontend/pages/doi_chieu_citad_nostro.py),
    # CHƯA CHẮC cùng thứ tự. Nếu người dùng gõ tay 2 ô ngày đảo thứ tự so
    # với lúc lưu lần đầu, so `ky == exclude_ky` ở dưới bằng chuỗi thô sẽ
    # KHÔNG khớp — kỳ đang sửa tự báo "CHỒNG NGÀY" với chính nó. Chuẩn hoá
    # lại ở đây (không sửa phía frontend) để đúng bất kể client gửi thứ tự
    # nào — bỏ qua lỗi format thay vì raise, vì hàm này chỉ CẢNH BÁO, không
    # phải đường lưu chính (đã kiểm ở normalize_ky() khi thực sự lưu).
    if exclude_ky:
        try:
            exclude_ky = normalize_ky(exclude_ky)
        except ValueError:
            pass

    # DISTINCT: từ 11/09/2026 nhiều bảng có thể cùng `ky` (nhiều người chấm
    # kỳ giống hệt nhau) — không cần cảnh báo lặp lại cùng 1 kỳ nhiều lần.
    rows = db.execute("SELECT DISTINCT ky FROM doi_chieu_citad_nostro_sessions").fetchall()
    ranges = []
    for r in rows:
        ky = r["ky"]
        if exclude_ky and ky == exclude_ky:
            continue
        rng = _parse_ky_range(ky)
        if rng:
            ranges.append((ky, rng[0], rng[1]))

    overlaps = [ky for ky, s, e in ranges if s <= new_end and e >= new_start]

    gap_before = None
    prior_ends = [e for _, _, e in ranges if e < new_start]
    if prior_ends:
        latest_prior_end = max(prior_ends)
        gap_days = (new_start - latest_prior_end).days - 1
        if gap_days > 0:
            gap_before = {
                "tu_ngay": (latest_prior_end + timedelta(days=1)).strftime("%d/%m/%Y"),
                "den_ngay": (new_start - timedelta(days=1)).strftime("%d/%m/%Y"),
                "so_ngay": gap_days,
            }
    return {"overlaps": overlaps, "gap_before": gap_before}


def get_reconciliation_days(
    db: sqlite3.Connection,
    tu_ngay: str | None = None,
    den_ngay: str | None = None,
    nguoi_cham: str | None = None,
) -> list:
    """1 dòng/BẢNG (`session_id`) — từ 11/09/2026 mỗi kỳ có thể có NHIỀU bảng
    (nhiều người chấm riêng), nên không còn "1 dòng/kỳ" như trước. Trả về
    DẠNG PHẲNG (không tự gom nhóm) — frontend tự gom 2 tầng: Kỳ → từng bảng
    (`session_id`) của từng người, mirror `get_reconciliation_days()` của
    Phòng Thanh toán.

    Lọc/sắp xếp bằng Python vì `ky` lưu dạng text — so sánh chuỗi trong SQL
    sai thứ tự thời gian. Ngày lọc do người dùng GÕ TAY (ô lọc là input tự
    do) nên phải parse bằng `_parse_ddmmyyyy()` trả None, KHÔNG dùng thẳng
    `strptime` — gõ dở "01/08" mà ném ValueError là sập cả trang lịch sử."""
    rows = db.execute(
        """SELECT s.id AS session_id, s.ky, s.updated_at, s.created_by,
                  u.username AS created_by_username, u.full_name AS created_by_name,
                  (SELECT COUNT(*) FROM doi_chieu_citad_nostro_history h WHERE h.session_id = s.id) AS so_lan_luu
           FROM doi_chieu_citad_nostro_sessions s
           LEFT JOIN user_tttt u ON u.id = s.created_by"""
    ).fetchall()

    tu_dt = _parse_ddmmyyyy(tu_ngay) if tu_ngay else None
    den_dt = _parse_ddmmyyyy(den_ngay) if den_ngay else None
    nguoi_kw = nguoi_cham.strip().lower() if nguoi_cham else None

    parsed = []
    for r in rows:
        d = _parse_ky_start(r["ky"])
        if d is None:
            continue
        if tu_dt and d < tu_dt:
            continue
        if den_dt and d > den_dt:
            continue
        if nguoi_kw:
            hay = f"{r['created_by_username'] or ''} {r['created_by_name'] or ''}".lower()
            if nguoi_kw not in hay:
                continue
        parsed.append((d, r["created_by_name"] or r["created_by_username"] or "", {
            "session_id": r["session_id"],
            "ky": r["ky"],
            "created_by": r["created_by"],
            "created_by_username": r["created_by_username"],
            "created_by_name": r["created_by_name"],
            "updated_at": str(r["updated_at"]) if r["updated_at"] else None,
            "so_lan_luu": r["so_lan_luu"],
        }))
    # Sắp theo kỳ (mới nhất trước), rồi theo `created_by` (không chỉ tên hiển
    # thị — 2 người trùng tên nhưng khác id không được lẫn nhóm), mirror PTT.
    parsed.sort(key=lambda t: (t[0], t[1], t[2]["created_by"] or 0), reverse=True)
    return [item for _, _, item in parsed]


def get_reconciliation_history(db: sqlite3.Connection, session_id: int) -> list:
    """Lịch sử từng lần lưu của ĐÚNG 1 bảng cụ thể (`session_id`) — trước
    11/09/2026 gộp theo `ky` (khi mỗi kỳ chỉ có 1 bảng); giờ nhiều bảng/kỳ
    nên phải lọc đúng bảng, không thì lẫn lịch sử của người khác."""
    rows = db.execute(
        """SELECT h.id, h.staff_id, u.username, h.created_at
           FROM doi_chieu_citad_nostro_history h
           JOIN user_tttt u ON u.id = h.staff_id
           WHERE h.session_id = ?
           ORDER BY h.created_at ASC, h.id ASC""",
        (session_id,),
    ).fetchall()
    return [
        {"id": r["id"], "staff_id": r["staff_id"], "username": r["username"], "created_at": str(r["created_at"])}
        for r in rows
    ]


def get_history_entry_data(db: sqlite3.Connection, history_id: int) -> dict | None:
    row = db.execute(
        "SELECT data FROM doi_chieu_citad_nostro_history WHERE id=?", (history_id,)
    ).fetchone()
    return json.loads(row["data"]) if row else None


# ── Tổng hợp tháng — cộng dồn NHIỀU bảng (nhiều kỳ/nhiều người) thành 1 báo
# cáo tháng, người dùng tự chọn bảng nào tính vào tổng (tự tick, tránh tính
# trùng khi có bảng chồng ngày — xác nhận yêu cầu thực tế 11/09/2026: file
# Excel mẫu cũ của phòng có dòng "Cả tháng" = cộng dồn các dòng theo NGÀY;
# công cụ mới không chấm theo ngày mà theo "kỳ" tự do nên "Cả tháng" ở đây =
# cộng dồn các BẢNG (kỳ) người dùng chọn, không phải cộng theo ngày) ────────
def _month_range(nam: int, thang: int) -> tuple[datetime, datetime]:
    last_day = calendar.monthrange(nam, thang)[1]
    return datetime(nam, thang, 1), datetime(nam, thang, last_day)


def get_sessions_for_month(db: sqlite3.Connection, nam: int, thang: int) -> list[dict]:
    """Mọi bảng có kỳ GIAO (dù chỉ 1 phần) với tháng nam-thang — dùng cho
    màn "Tổng hợp tháng" chọn bảng tính vào tổng. Trả phẳng, sắp theo ngày
    bắt đầu kỳ, y hệt cách sắp của `get_reconciliation_days()`."""
    thang_start, thang_end = _month_range(nam, thang)
    rows = db.execute(
        """SELECT s.id AS session_id, s.ky, s.created_by,
                  u.username AS created_by_username, u.full_name AS created_by_name
           FROM doi_chieu_citad_nostro_sessions s
           LEFT JOIN user_tttt u ON u.id = s.created_by"""
    ).fetchall()
    out = []
    for r in rows:
        rng = _parse_ky_range(r["ky"])
        if not rng:
            continue
        s, e = rng
        if s > thang_end or e < thang_start:
            continue  # kỳ nằm ngoài tháng, không liên quan
        out.append({
            "session_id": r["session_id"],
            "ky": r["ky"],
            "created_by": r["created_by"],
            "created_by_username": r["created_by_username"],
            "created_by_name": r["created_by_name"],
        })
    out.sort(key=lambda d: _parse_ky_start(d["ky"]) or datetime.min)
    return out


def get_month_missing_days(db: sqlite3.Connection, nam: int, thang: int) -> list[str]:
    """Những ngày trong tháng CHƯA có bảng nào (bất kỳ ai) phủ tới — để
    nhắc chấm bù. Tính trên TẤT CẢ bảng đang có của tháng (không phụ thuộc
    bảng nào được tick vào tổng ở màn hình — mục đích khác nhau: đây là hỏi
    "ngày nào chưa ai chấm", không phải "ngày nào đang được cộng vào tổng")."""
    thang_start, thang_end = _month_range(nam, thang)
    covered: set[datetime] = set()
    for sess in get_sessions_for_month(db, nam, thang):
        rng = _parse_ky_range(sess["ky"])
        if not rng:
            continue
        s, e = max(rng[0], thang_start), min(rng[1], thang_end)
        d = s
        while d <= e:
            covered.add(d)
            d += timedelta(days=1)
    missing = []
    d = thang_start
    while d <= thang_end:
        if d not in covered:
            missing.append(d.strftime("%d/%m/%Y"))
        d += timedelta(days=1)
    return missing


def combine_sessions_cD_phD(db: sqlite3.Connection, session_ids: list[int]) -> tuple[dict, dict]:
    """Cộng dồn cD/phD (bằng Decimal, xem `_dec()`) của các bảng được người
    dùng tick chọn — kết quả có CÙNG cấu trúc với cD/phD của 1 bảng đơn, nên
    dùng thẳng lại được `build_xlsx_nostro()` (chỉ khác tu_ngay/den_ngay
    truyền vào là cả tháng thay vì 1 kỳ) mà không cần viết hàm xuất Excel
    riêng cho báo cáo tháng."""
    dec_cD = {c: {l: {"soMon": Decimal(0), "soTien": Decimal(0)} for l in LOAI_CITAD} for c in CONGS}
    dec_phD = {r: {"soMon": Decimal(0), "soTien": Decimal(0)} for r in ("gtt", "gtc_truoc", "gtc_tu")}
    for sid in session_ids:
        sess = session_get(db, sid)
        if not sess:
            continue
        cD = sess.get("cD") or {}
        for c in CONGS:
            cd = cD.get(c, {}) or {}
            for l in LOAI_CITAD:
                src = cd.get(l, {}) or {}
                for fld in ("soMon", "soTien"):
                    dec_cD[c][l][fld] += _dec(src.get(fld, 0))
        phD = sess.get("phD") or {}
        for r in ("gtt", "gtc_truoc", "gtc_tu"):
            src = phD.get(r, {}) or {}
            for fld in ("soMon", "soTien"):
                dec_phD[r][fld] += _dec(src.get(fld, 0))
    cD_out = {c: {l: {fld: float(dec_cD[c][l][fld]) for fld in ("soMon", "soTien")} for l in LOAI_CITAD} for c in CONGS}
    phD_out = {r: {fld: float(dec_phD[r][fld]) for fld in ("soMon", "soTien")} for r in ("gtt", "gtc_truoc", "gtc_tu")}
    return cD_out, phD_out


# ── Xuất Excel ──────────────────────────────────────────────────────────
def build_xlsx_nostro(data: ExportIn) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    import re

    TNR = "Times New Roman"

    def F(bold=False, size=13, color="000000"):
        return Font(name=TNR, bold=bold, size=size, color=color)

    def AL(h="center", v="center", wrap=False):
        return Alignment(horizontal=h, vertical=v, wrap_text=wrap)

    def Bdr(w="thin"):
        s = Side(style=w)
        return Border(top=s, bottom=s, left=s, right=s)

    def Fill(h):
        return PatternFill("solid", fgColor=h)

    sess = {"cD": data.cD, "phD": data.phD}
    ci, hub = compute_totals(sess)

    wb = Workbook()
    ws = wb.active
    safe_sheet_name = re.sub(r'[:\\/?*\[\]]', '_', data.sheet_name) or 'Sheet1'
    ws.title = safe_sheet_name[:31]
    NUM = '#,##0'
    BLU = '4472C4'
    for col, wd in zip('ABCDEF', [24, 20, 26, 20, 26, 20]):
        ws.column_dimensions[col].width = wd

    def hcell(r, c, val, fill=BLU, color='FFFFFF', bold=True):
        cell = ws.cell(r, c)
        cell.value = val
        cell.font = F(bold=bold, color=color)
        cell.alignment = AL(wrap=True)
        cell.fill = Fill(fill)
        cell.border = Bdr()
        return cell

    ws.merge_cells('A1:F1')
    ws['A1'] = 'BÁO CÁO ĐỐI CHIẾU CITAD - PAYMENTHUB — PHÒNG QLTK NOSTRO, VOSTRO'
    ws['A1'].font = F(bold=True, size=15)
    ws['A1'].alignment = AL()
    ws.row_dimensions[1].height = 22
    ws.merge_cells('A2:F2')
    ws['A2'] = f"Kỳ đối chiếu: {data.tu_ngay} - {data.den_ngay}"
    ws['A2'].font = F(bold=True)
    ws['A2'].alignment = AL()

    row = 4
    hcell(row, 1, 'Cổng CITAD')
    hcell(row, 2, 'GTT - Số món')
    hcell(row, 3, 'GTT - Số tiền')
    hcell(row, 4, 'GTC - Số món')
    hcell(row, 5, 'GTC - Số tiền')
    row += 1
    cD = data.cD or {}
    for cong in CONGS:
        c = cD.get(cong, {}) or {}
        gtt = c.get('gtt', {}) or {}
        gtc = c.get('gtc', {}) or {}
        vals = [CONG_LABEL.get(cong, f'Cổng {cong}'), _nv(gtt.get('soMon', 0)), _nv(gtt.get('soTien', 0)),
                _nv(gtc.get('soMon', 0)), _nv(gtc.get('soTien', 0))]
        for ci2, v in enumerate(vals, start=1):
            cell = ws.cell(row, ci2)
            cell.value = v
            cell.border = Bdr()
            cell.alignment = AL('left' if ci2 == 1 else 'right')
            if ci2 > 1:
                cell.number_format = NUM
        row += 1
    ws.cell(row, 1).value = 'Tổng cộng 5 cổng'
    ws.cell(row, 1).font = F(bold=True)
    ws.cell(row, 1).border = Bdr()
    for ci2, v in [(2, ci['gtt']['soMon']), (3, ci['gtt']['soTien']),
                   (4, ci['gtc']['soMon']), (5, ci['gtc']['soTien'])]:
        cell = ws.cell(row, ci2)
        cell.value = float(v)
        cell.number_format = NUM
        cell.font = F(bold=True)
        cell.alignment = AL('right')
        cell.border = Bdr()
        cell.fill = Fill('DCE6F1')
    row += 2

    hcell(row, 1, 'HUB (PaymentHub)')
    hcell(row, 2, 'GTT - Số món')
    hcell(row, 3, 'GTT - Số tiền')
    hcell(row, 4, 'GTC - Số món')
    hcell(row, 5, 'GTC - Số tiền')
    row += 1
    phD = data.phD or {}
    gtt_h = phD.get('gtt', {}) or {}
    gtc_truoc = phD.get('gtc_truoc', {}) or {}
    gtc_tu = phD.get('gtc_tu', {}) or {}
    ws.cell(row, 1).value = 'GTT'
    ws.cell(row, 1).border = Bdr()
    ws.cell(row, 2).value = _nv(gtt_h.get('soMon', 0))
    ws.cell(row, 3).value = _nv(gtt_h.get('soTien', 0))
    ws.cell(row, 4).value = None
    ws.cell(row, 5).value = None
    for ci2 in (2, 3):
        ws.cell(row, ci2).number_format = NUM
        ws.cell(row, ci2).border = Bdr()
        ws.cell(row, ci2).alignment = AL('right')
    ws.cell(row, 4).border = Bdr()
    ws.cell(row, 5).border = Bdr()
    row += 1
    ws.cell(row, 1).value = 'GTC — Trước 15h30'
    ws.cell(row, 1).border = Bdr()
    ws.cell(row, 4).value = _nv(gtc_truoc.get('soMon', 0))
    ws.cell(row, 5).value = _nv(gtc_truoc.get('soTien', 0))
    for ci2 in (1, 2, 3, 4, 5):
        ws.cell(row, ci2).border = Bdr()
    ws.cell(row, 4).number_format = NUM
    ws.cell(row, 5).number_format = NUM
    ws.cell(row, 4).alignment = AL('right')
    ws.cell(row, 5).alignment = AL('right')
    row += 1
    ws.cell(row, 1).value = 'GTC — Từ 15h30'
    ws.cell(row, 4).value = _nv(gtc_tu.get('soMon', 0))
    ws.cell(row, 5).value = _nv(gtc_tu.get('soTien', 0))
    for ci2 in (1, 2, 3, 4, 5):
        ws.cell(row, ci2).border = Bdr()
    ws.cell(row, 4).number_format = NUM
    ws.cell(row, 5).number_format = NUM
    ws.cell(row, 4).alignment = AL('right')
    ws.cell(row, 5).alignment = AL('right')
    row += 1
    ws.cell(row, 1).value = 'Tổng HUB'
    ws.cell(row, 1).font = F(bold=True)
    for ci2, v in [(2, hub['gtt']['soMon']), (3, hub['gtt']['soTien']),
                   (4, hub['gtc']['soMon']), (5, hub['gtc']['soTien'])]:
        cell = ws.cell(row, ci2)
        cell.value = float(v)
        cell.number_format = NUM
        cell.font = F(bold=True)
        cell.alignment = AL('right')
        cell.fill = Fill('DCE6F1')
        cell.border = Bdr()
    ws.cell(row, 1).border = Bdr()
    ws.cell(row, 1).fill = Fill('DCE6F1')
    row += 2

    diff_gtt_mon = ci['gtt']['soMon'] - hub['gtt']['soMon']
    diff_gtt_tien = ci['gtt']['soTien'] - hub['gtt']['soTien']
    diff_gtc_mon = ci['gtc']['soMon'] - hub['gtc']['soMon']
    diff_gtc_tien = ci['gtc']['soTien'] - hub['gtc']['soTien']
    hcell(row, 1, 'Chênh lệch (CITAD − HUB)', fill='FFE699', color='7F0000')
    hcell(row, 2, 'GTT - Số món', fill='FFE699', color='7F0000')
    hcell(row, 3, 'GTT - Số tiền', fill='FFE699', color='7F0000')
    hcell(row, 4, 'GTC - Số món', fill='FFE699', color='7F0000')
    hcell(row, 5, 'GTC - Số tiền', fill='FFE699', color='7F0000')
    row += 1
    ws.cell(row, 1).value = ''
    ws.cell(row, 1).fill = Fill('FFE699')
    ws.cell(row, 1).border = Bdr()
    for ci2, v in [(2, diff_gtt_mon), (3, diff_gtt_tien), (4, diff_gtc_mon), (5, diff_gtc_tien)]:
        cell = ws.cell(row, ci2)
        # v là Decimal (ci/hub cộng dồn bằng _dec()) nên CHÍNH XÁC TUYỆT ĐỐI —
        # khớp thật mới ra đúng 0, không có dư nhị phân nào phải làm tròn/che
        # đi. Luôn ghi giá trị thật (không còn `v if v else 0`) — cùng lý do
        # đã sửa ở build_xlsx() gốc Phòng Thanh toán.
        cell.value = float(v)
        cell.number_format = NUM
        cell.font = F(bold=True, color='006100' if v == 0 else 'FF0000')
        cell.alignment = AL('right')
        cell.fill = Fill('FFE699')
        cell.border = Bdr()
    row += 2

    ws.merge_cells(f'A{row}:C{row}')
    ws.cell(row, 1).value = '                  LẬP BẢNG'
    ws.cell(row, 1).font = F(bold=True)
    ws.cell(row, 1).alignment = AL()
    ws.merge_cells(f'D{row}:F{row}')
    ws.cell(row, 4).value = 'KIỂM SOÁT'
    ws.cell(row, 4).font = F(bold=True)
    ws.cell(row, 4).alignment = AL()
    row += 4
    ws.cell(row, 2).value = data.lb
    ws.cell(row, 2).font = F(bold=True)
    ws.cell(row, 2).alignment = AL()
    ws.merge_cells(f'D{row}:F{row}')
    ws.cell(row, 4).value = data.ks
    ws.cell(row, 4).font = F(bold=True)
    ws.cell(row, 4).alignment = AL()

    ws.print_area = f'A1:F{row}'
    from openpyxl.worksheet.page import PageMargins
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins = PageMargins(left=0.3, right=0.3, top=0.3, bottom=0.3, header=0.1, footer=0.1)
    # Cân bảng vào giữa trang (ngang lẫn dọc) thay vì dồn về góc trên-trái —
    # bảng ngắn hơn nhiều so với khổ A4 ngang nên để mặc định sẽ trông lệch,
    # trống hẳn nửa dưới/nửa phải trang in. Cùng convention với
    # duty_export_service.py::build_xlsx_week.
    ws.print_options.horizontalCentered = True
    ws.print_options.verticalCentered = True

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
