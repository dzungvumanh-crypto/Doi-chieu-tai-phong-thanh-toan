"""SQLite connection factory — raw SQL, no ORM."""
import logging
import os
import queue
import sqlite3
import threading
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from backend.core.config import settings

_log = logging.getLogger(__name__)

DB_PATH = settings.DATABASE_URL.replace("sqlite:///", "")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

_VN_TZ = timezone(timedelta(hours=7))


def _vn_now() -> datetime:
    return datetime.now(_VN_TZ).replace(tzinfo=None)


def write_audit(
    db: sqlite3.Connection,
    actor_id: int,
    action: str,
    target_type: str = None,
    target_id: int = None,
    detail: str = None,
    ip: str = None,
) -> None:
    # Không truyền ip → lấy IP thật đã lưu lúc đăng nhập (khớp Nhật ký đăng nhập)
    if ip is None and actor_id:
        try:
            from backend.core.sessions import get_session_ip
            ip = get_session_ip(db, actor_id)
        except Exception:
            pass
    db.execute(
        "INSERT INTO audit_logs (actor_id, action, target_type, target_id, detail, ip_address, created_at) VALUES (?,?,?,?,?,?,?)",
        (actor_id, action, target_type, target_id, detail, ip, _vn_now()),
    )


def compute_annual_leave(join_date_str, year: int = None) -> int:
    """Tính số ngày phép năm: 12 ngày + 1 ngày mỗi 5 năm vào ngành (đúng Điều 113
    Bộ luật Lao động — đối chiếu báo cáo thật 2026 khớp 67/72 người theo mốc 5
    năm, so với chỉ 12/72 nếu tính theo 4 năm).

    Ví dụ: vào ngành 2007, năm 2012 → 13 ngày; năm 2017 → 14 ngày.
    Trả về 12 nếu join_date_str là None hoặc không hợp lệ.
    """
    if not join_date_str:
        return 12
    from datetime import date
    try:
        join_date = join_date_str if isinstance(join_date_str, date) else date.fromisoformat(str(join_date_str))
        ref_year = year or _vn_now().date().year
        years = ref_year - join_date.year
        return 12 + max(0, years // 5)
    except Exception:
        return 12


def compute_carry_over(staff_id: int, year: int, db,
                       effective: bool = True, ref_date=None) -> float:
    """Số ngày phép năm (year-1) chưa dùng được mang sang Q1/year.

    effective=True : chỉ trả giá trị nếu ref_date (hoặc hôm nay) còn trong Q1.
    effective=False: luôn trả số ngày thực tế, dùng để hiển thị / in phiếu.
    ref_date       : ngày tham chiếu thay cho _vn_now().date() khi check Q1
                     (dùng khi tạo đơn nghỉ trong tương lai).
    """
    from datetime import date as _date, timedelta
    import json
    if effective:
        check_date = ref_date if ref_date else _vn_now().date()
        if check_date > _date(year, 3, 31):
            return 0.0
    prev_year = year - 1
    q = db.execute(
        "SELECT quota_days FROM leave_quotas WHERE staff_id=? AND year=?", (staff_id, prev_year)
    ).fetchone()
    staff = db.execute("SELECT join_industry_date FROM user_tttt WHERE id=?", (staff_id,)).fetchone()
    prev_quota = float(q["quota_days"]) if q else float(
        compute_annual_leave(staff["join_industry_date"] if staff else None, prev_year)
    )
    rows = db.execute(
        """SELECT start_date, end_date, spread_dates, borrow_next_year_days FROM leave_records
           WHERE staff_id=? AND status='approved'
             AND leave_type NOT IN ('thai_san','bao_hiem','khong_luong','hop_cong_tac')
             AND NOT (leave_type='other' AND other_deduct_quota=0)
             AND start_date <= ? AND end_date >= ?""",
        (staff_id, f"{prev_year}-12-31", f"{prev_year}-01-01"),
    ).fetchall()
    # Import muộn: lich_lam_viec không kéo theo gì từ database.py, nhưng đặt ở
    # đầu file thì mọi module import database.py đều phải nạp theo — giữ nguyên
    # kiểu import cục bộ mà hàm này đang dùng cho date/json.
    from backend.services.lich_lam_viec import la_ngay_lam_viec, tai_lich
    used = 0.0
    _lich = None
    for row in rows:
        # Phần đã "ứng" sang năm sau (borrow_next_year_days, xem
        # backend/api/leaves.py::_check_quota_or_borrow) không tính là đã dùng
        # của prev_year — nếu không carry-over sẽ bị tính hụt. CHỈ trừ borrow ở
        # đúng năm GỐC của đơn (năm chứa start_date) — đơn vắt ranh giới năm
        # (vd 29/12→02/01) có thể khớp overlap ở đây dù start_date KHÔNG phải
        # prev_year (vd đơn bắt đầu từ prev_year-1); trừ nhầm borrow của đơn đó
        # vào prev_year sẽ làm hụt used y hệt bug đã sửa ở _calc_used_days.
        borrow = row["borrow_next_year_days"] or 0.0
        row_start_year = _date.fromisoformat(row["start_date"]).year
        own_borrow = borrow if row_start_year == prev_year else 0.0
        if row["spread_dates"]:
            used += len([d for d in json.loads(row["spread_dates"]) if d.startswith(str(prev_year))]) - own_borrow
        else:
            if _lich is None:
                _lich = tai_lich(db, _date(prev_year, 1, 1), _date(prev_year, 12, 31))
            d = _date.fromisoformat(row["start_date"])
            end = _date.fromisoformat(row["end_date"])
            yr_count = 0
            while d <= end:
                if d.year == prev_year and la_ngay_lam_viec(d, _lich):
                    yr_count += 1
                d += timedelta(days=1)
            used += yr_count - own_borrow
    return max(0.0, prev_quota - used)


# ── Bể kết nối ───────────────────────────────────────────────────────────────
# Đo trên máy chủ 10/09/2026: mở file CSDL tốn 1,55 ms mỗi request, trong khi một
# truy vấn trên kết nối có sẵn chỉ 0,0057 ms — **đắt gấp 270 lần**. Kiểm riêng:
# bỏ hết 4 câu PRAGMA đi vẫn tốn 1,52 ms, nên chi phí nằm ở việc MỞ FILE (db +
# WAL + shm), không phải ở PRAGMA. Vì vậy cách sửa là dùng lại kết nối, KHÔNG
# phải cắt PRAGMA — cắt thì mất an toàn dữ liệu mà không nhanh lên chút nào.
#
# Mượn–trả từng request, KHÔNG dùng `threading.local()`. `get_db()` là generator
# đồng bộ nên FastAPI chạy nó trong threadpool, còn thân hàm `async def` lại chạy
# trên luồng event loop: kết nối gắn theo luồng sẽ bị dùng chéo luồng và trộn
# trạng thái giao dịch giữa hai request khác nhau.
#
# `journal_mode` KHÔNG đặt ở đây: nó ghi cố định trong file CSDL, đặt một lần lúc
# khởi động là đủ (xem `khoi_tao_pool()`). `foreign_keys` và `synchronous` thì
# theo từng kết nối nên phải đặt lúc tạo.
def _doc_so(ten_bien: str, mac_dinh: int) -> int:
    """Đọc số từ .env, không để cấu hình sai giết hệ thống không dấu vết.

    `int(os.getenv(...))` trần có hai cách chết: ô để trống hoặc gõ nhầm chữ thì
    ném ValueError ngay lúc import (backend không lên, lỗi không nhắc gì tới
    .env); số ÂM thì `_da_tao < _POOL_MAX` luôn sai nên bể không bao giờ tạo
    thêm kết nối — cả hệ thống dùng đúng một kết nối rồi mọi request đồng thời
    chờ hết giờ và ăn 500. Cùng cách `backend/core/phien_doi_chieu.py` làm.
    """
    tho = (os.getenv(ten_bien) or "").strip()
    try:
        return max(1, int(tho)) if tho else mac_dinh
    except ValueError:
        _log.warning("%s=%r không phải số — dùng mặc định %d", ten_bien, tho, mac_dinh)
        return mac_dinh


# Mặc định 48, KHÔNG phải 16: endpoint khai `def` chạy trong bể 40 token của
# anyio và mỗi cái giữ một kết nối suốt thời gian xử lý. Trần nhỏ hơn 40 thì
# phần dư chờ hết giờ rồi nhận 500 — nặng hơn hẳn bản cũ (chỉ chậm, không lỗi).
# Cộng thêm các đường giữ kết nối rất lâu: `do_reconcile` giữ suốt lượt đối
# soát, xem trước đơn nghỉ phép tới 150 giây. Chừa dư cho endpoint `async def`.
_POOL_MAX = _doc_so("DB_POOL_SIZE", 48)
_POOL_CHO_GIAY = 30.0

_pool: "queue.LifoQueue[sqlite3.Connection]" = queue.LifoQueue()
_pool_lock = threading.Lock()
_da_tao = 0


def _tao_ket_noi() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _muon() -> sqlite3.Connection:
    global _da_tao
    try:
        return _pool.get_nowait()
    except queue.Empty:
        pass
    with _pool_lock:
        if _da_tao < _POOL_MAX:
            _da_tao += 1
            tu_tao = True
        else:
            tu_tao = False
    if tu_tao:
        try:
            return _tao_ket_noi()
        except Exception:
            with _pool_lock:
                _da_tao -= 1      # tạo hỏng thì trả lại suất, không thì bể teo dần
            raise
    # Bể đầy: chờ người khác trả. Chờ từng nhịp ngắn rồi ngó lại sổ, thay vì một
    # lần `get(timeout=30)`: khi `_tra()` vứt bỏ một kết nối hỏng thì suất trống
    # ra nhưng KHÔNG có gì được đưa vào hàng đợi, nên luồng đang chờ sẽ nằm đủ
    # 30 giây rồi ăn lỗi "bể đều đang bận" trong khi suất đã trống — thông báo
    # sai hướng, người vận hành đi nâng DB_POOL_SIZE vô ích.
    het_han = time.monotonic() + _POOL_CHO_GIAY
    while True:
        con_lai = het_han - time.monotonic()
        if con_lai <= 0:
            break
        try:
            return _pool.get(timeout=min(0.5, con_lai))
        except queue.Empty:
            pass
        with _pool_lock:
            if _da_tao < _POOL_MAX:
                _da_tao += 1
                tu_tao = True
            else:
                tu_tao = False
        if tu_tao:
            try:
                return _tao_ket_noi()
            except Exception:
                with _pool_lock:
                    _da_tao -= 1
                raise
    # Hết giờ chờ là báo thẳng thay vì treo vô hạn — request treo im lặng khó
    # lần hơn nhiều so với một lỗi nói rõ nguyên nhân.
    raise RuntimeError(
        f"Hết kết nối CSDL sau {_POOL_CHO_GIAY:.0f} giây chờ "
        f"(bể {_POOL_MAX} kết nối đều đang bận). Nếu lặp lại thường xuyên, "
        f"nâng DB_POOL_SIZE trong .env."
    )


def _tra(conn: sqlite3.Connection) -> None:
    """Trả kết nối về bể. Kết nối hỏng thì bỏ hẳn, không đưa lại cho request sau."""
    global _da_tao
    try:
        # Bắt buộc: request có thể kết thúc khi còn giao dịch dở. Bản cũ đóng kết
        # nối nên SQLite tự huỷ giao dịch đó; nay kết nối sống tiếp, không rollback
        # là phần ghi dở rò sang request kế tiếp.
        conn.rollback()
    except sqlite3.Error as exc:
        # Không nuốt: ổ đĩa đầy hay CSDL hỏng thì hệ thống âm thầm quay vòng kết
        # nối mà không để lại dấu vết nào. Xem docs/SKILL.md.
        _log.warning("Kết nối CSDL hỏng lúc trả về bể (%s) — bỏ kết nối này", exc)
        try:
            conn.close()
        except sqlite3.Error:
            pass
        with _pool_lock:
            _da_tao -= 1
        return
    _pool.put(conn)


def khoi_tao_pool() -> None:
    """Đặt `journal_mode=WAL` một lần cho cả file CSDL. Gọi lúc khởi động.

    `journal_mode` ghi cố định vào file CSDL nên không cần lặp ở mỗi kết nối —
    bản cũ chạy nó 266 lần mỗi vòng request mà kết quả luôn y nhau.
    """
    global _da_tao
    conn = _tao_ket_noi()
    with _pool_lock:
        _da_tao += 1          # tính suất TRƯỚC khi đưa vào bể, để `_tra` cân đúng sổ
    try:
        che_do = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(che_do).lower() != "wal":
            # RAISE chứ không chỉ log. Bản cũ chạy PRAGMA này ở MỌI kết nối nên
            # một lần trượt (khoá tạm thời) tự lành ở request sau. Nay chỉ có
            # đúng một lượt lúc khởi động: trượt phát nào là cả tiến trình chạy
            # ở chế độ rollback-journal với 48 kết nối sống lâu — writer khoá
            # sạch reader, hệ thống chậm bí ẩn mà không ai biết vì sao.
            # Cùng nguyên tắc với mục Schema Migrations trong docs/DESIGN.md.
            raise RuntimeError(
                f"Không bật được chế độ WAL cho {DB_PATH} — journal_mode đang là "
                f"{che_do!r}. Thường do file CSDL đang bị tiến trình khác giữ "
                f"(công cụ xem DB đang mở?). Đóng nó rồi khởi động lại."
            )
    finally:
        _tra(conn)


def dong_pool() -> None:
    """Đóng mọi kết nối rảnh. Gọi lúc tắt ứng dụng."""
    global _da_tao
    while True:
        try:
            conn = _pool.get_nowait()
        except queue.Empty:
            break
        try:
            conn.close()
        except sqlite3.Error:
            pass
        with _pool_lock:
            _da_tao -= 1


def pool_stats() -> dict:
    """Trạng thái bể — để chẩn đoán khi hệ thống có vẻ chậm."""
    with _pool_lock:
        da_tao = _da_tao
    ranh = _pool.qsize()
    return {"toi_da": _POOL_MAX, "da_tao": da_tao, "ranh": ranh,
            "dang_muon": max(0, da_tao - ranh)}


def get_db():
    conn = _muon()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        _tra(conn)
