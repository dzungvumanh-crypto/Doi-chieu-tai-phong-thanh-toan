"""
Duty Scheduler Engine — thuật toán phân lịch trực tự động.
Raw SQLite3. Staff được biểu diễn dưới dạng dict (không ORM).

Loại ca: normal | friday | cutoff | settlement_main
Rotation roles: LD | NV | LD_friday | NV_friday | LD_cutoff | NV_cutoff

Số người mỗi ca lấy từ khai báo ở tab Cài đặt (duty_shift_config) — thiếu người
thì KHÔNG hình thành ca trực. Ca quyết toán có thêm nhóm trực phụ (về sớm hơn).
Cần ít nhất 1 người xử lý song phương trong Lãnh đạo hoặc nhóm trực chính.
Chỉ thứ 6 luân phiên tất định; các loại ca khác bốc ngẫu nhiên trong nhóm ít ca nhất.
"""
import json
import random
import sqlite3
import calendar as _cal
from datetime import datetime, date as _date, timedelta, timezone
from typing import List, Optional, Tuple

from backend.services.duty_staff_service import get_available_pool
from backend.services.duty_constraint_service import (
    get_requests_for_date, get_special_day, get_holiday_dates, get_week_assignees,
)
from backend.services.duty_calendar_utils import get_week_dates, is_friday
from backend.services.duty_rules import get_cau_hinh_ca, resolve_sp_role

_VN_TZ = timezone(timedelta(hours=7))


def _now():
    return datetime.now(_VN_TZ).replace(tzinfo=None)


# ══════════════════════════════════════════════════════════════
# ROTATION STATE
# ══════════════════════════════════════════════════════════════

def _get_rotation_state(db: sqlite3.Connection, staff_id: int, year: int, role: str) -> dict:
    """Lấy hoặc tạo mới rotation_state cho (year, role, staff_id)."""
    row = db.execute(
        "SELECT * FROM duty_rotation_state WHERE year=? AND role=? AND staff_id=?",
        (year, role, staff_id)
    ).fetchone()
    if row:
        return dict(row)

    # Lazy init — tính position từ display_order
    meta = db.execute(
        "SELECT COALESCE(m.display_order, 999) AS display_order "
        "FROM user_tttt u LEFT JOIN duty_staff_meta m ON u.id=m.user_id WHERE u.id=?",
        (staff_id,)
    ).fetchone()
    display_order = meta["display_order"] if meta else 999
    pos = display_order * 10 + staff_id

    db.execute(
        "INSERT OR IGNORE INTO duty_rotation_state (year, role, staff_id, shift_count, last_used, position) VALUES (?,?,?,0,NULL,?)",
        (year, role, staff_id, pos)
    )
    return {"year": year, "role": role, "staff_id": staff_id,
            "shift_count": 0, "last_used": None, "position": pos}


def _update_rotation(db: sqlite3.Connection, staff_id: int, year: int,
                     role: str, date_str: str) -> None:
    """Tăng shift_count và cập nhật last_used."""
    _get_rotation_state(db, staff_id, year, role)  # đảm bảo row tồn tại
    db.execute(
        "UPDATE duty_rotation_state SET shift_count = shift_count + 1, last_used = ? "
        "WHERE year=? AND role=? AND staff_id=?",
        (date_str, year, role, staff_id)
    )


# ══════════════════════════════════════════════════════════════
# SORT HELPERS
# ══════════════════════════════════════════════════════════════

def _preferred_day_mismatch(last_used: Optional[str], current_date: Optional[str]) -> int:
    if not last_used or not current_date:
        return 0
    try:
        last_wd = datetime.strptime(last_used, "%Y-%m-%d").weekday()
        curr_wd = datetime.strptime(current_date, "%Y-%m-%d").weekday()
        preferred_next = (last_wd + 1) % 5
        return (curr_wd - preferred_next) % 5
    except (ValueError, AttributeError):
        return 5


# Mỗi vai có nhiều kênh vòng xoay theo loại ca. Cân bằng phải xét TỔNG cả nhóm:
# đếm riêng từng kênh thì một người đứng cuối cả ba sổ mà tổng số ca vẫn cao nhất.
_NHOM_KENH = {
    "LD": ("LD", "LD_friday", "LD_cutoff"),
    "NV": ("NV", "NV_friday", "NV_cutoff"),
}


def _tong_ca(db: sqlite3.Connection, staff_id: int, year: int,
             role: str) -> Tuple[int, str]:
    """Tổng số ca trên mọi kênh cùng vai, kèm ngày trực gần nhất."""
    _get_rotation_state(db, staff_id, year, role)   # lazy-init kênh đang dùng
    kenh = _NHOM_KENH["LD" if role.startswith("LD") else "NV"]
    row = db.execute(
        f"SELECT COALESCE(SUM(shift_count), 0) AS tong, MAX(last_used) AS gan_nhat "
        f"FROM duty_rotation_state WHERE year=? AND staff_id=? "
        f"AND role IN ({','.join('?' * len(kenh))})",
        (year, staff_id, *kenh),
    ).fetchone()
    return row["tong"], (row["gan_nhat"] or "")


def _sort_by_rotation(db: sqlite3.Connection, candidates: List[dict],
                      year: int, role: str, current_date: str = None,
                      tranh_sp: bool = False) -> List[dict]:
    def sort_key(p: dict):
        tong, gan_nhat = _tong_ca(db, p["id"], year, role)
        s = _get_rotation_state(db, p["id"], year, role)
        return (
            tong,
            # Chỉ phân biệt người biết song phương khi đã ngang số ca
            bool(p.get("can_do_sp")) if tranh_sp else False,
            _preferred_day_mismatch(gan_nhat, current_date),
            gan_nhat or "0000-00-00",
            s["position"],
            p["id"],
        )
    return sorted(candidates, key=sort_key)


# ══════════════════════════════════════════════════════════════
# XẾP THỨ TỰ ƯU TIÊN & CHỌN TỔ HỢP
# ══════════════════════════════════════════════════════════════

def _rank_candidates(db: sqlite3.Connection, candidates: List[dict], year: int,
                     role: str, date_str: str, rng: random.Random,
                     randomize: bool, tranh_sp: bool = False) -> List[dict]:
    """
    Xếp thứ tự ưu tiên trong 1 nhóm ứng viên. Thuần đọc — không ghi vòng xoay.

    `tranh_sp` — Lãnh đạo đã giữ vai song phương nên ca không cần thêm người
    biết song phương nữa. Đây chỉ là tiêu chí PHỤ: dùng để chọn giữa những người
    đang ngang số ca, không được đẩy người ít ca xuống cuối chỉ vì họ biết song
    phương. Hy sinh cân bằng cho một luật mềm là đánh đổi sai.
    """
    if not candidates:
        return []
    if not randomize:
        return _sort_by_rotation(db, candidates, year, role, date_str, tranh_sp)

    # Ngẫu nhiên trong nhóm ít ca nhất, rồi tới nhóm ít ca kế tiếp
    bang = {p["id"]: _tong_ca(db, p["id"], year, role) for p in candidates}
    ordered: List[dict] = []
    for c in sorted({t for t, _ in bang.values()}):
        nhom = [p for p in candidates if bang[p["id"]][0] == c]
        rng.shuffle(nhom)
        # sort ổn định — thứ tự ngẫu nhiên được giữ trong từng mức khoá
        nhom.sort(key=lambda p: (
            bool(p.get("can_do_sp")) if tranh_sp else False,
            _preferred_day_mismatch(bang[p["id"]][1], date_str),
        ))
        ordered.extend(nhom)
    return ordered


def _order_pool(db: sqlite3.Connection, people: List[dict], requests: dict, kind: str,
                year: int, role: str, date_str: str, rng: random.Random,
                randomize: bool, tranh_sp: bool = False) -> List[dict]:
    """Xếp pool theo tầng ưu tiên: đăng ký đích danh ngày > chưa trực trong tuần > đã trực."""
    week_ids = get_week_assignees(db, date_str)
    once_ids = set(requests.get("once_ids", set()))
    req_ids  = set(requests.get(kind, []))

    forced = [p for p in people if p["id"] in once_ids]
    rest   = [p for p in people if p["id"] not in once_ids]
    fresh  = [p for p in rest if p["id"] not in week_ids]
    repeat = [p for p in rest if p["id"] in week_ids]

    def _rank(group: List[dict]) -> List[dict]:
        return _rank_candidates(db, group, year, role, date_str, rng, randomize, tranh_sp)

    def _layer(group: List[dict]) -> List[dict]:
        return (_rank([p for p in group if p["id"] in req_ids])
                + _rank([p for p in group if p["id"] not in req_ids]))

    return _rank(forced) + _layer(fresh) + _layer(repeat)


def _chon_lanh_dao(ld_order: List[dict], so_ld: int, nv_co_sp: bool) -> List[dict]:
    """Chọn so_ld Lãnh đạo theo thứ tự ưu tiên đã xếp sẵn."""
    # Chỉ khi CẢ pool nhân viên không còn ai biết song phương mới kéo Lãnh đạo
    # biết song phương lên trước — nếu không, việc kéo sẽ lặp lại gần như mỗi
    # ngày và dồn hết ca cho vài người.
    if not nv_co_sp:
        ld_order = ([p for p in ld_order if p.get("can_do_sp")]
                    + [p for p in ld_order if not p.get("can_do_sp")])

    leaders = ld_order[:so_ld]
    # Khai nhiều Lãnh đạo mà vơ trúng 2 người cùng biết song phương là lãng phí.
    # Chỉ thay khi có sẵn người ngoài top, để không phá thứ tự vòng xoay.
    if sum(1 for p in leaders if p.get("can_do_sp")) > 1:
        du_bi = [p for p in ld_order[so_ld:] if not p.get("can_do_sp")]
        thay_the, da_co_sp = [], False
        for p in leaders:
            if p.get("can_do_sp"):
                if da_co_sp and du_bi:
                    thay_the.append(du_bi.pop(0))
                    continue
                da_co_sp = True
            thay_the.append(p)
        leaders = thay_the
    return leaders


def _chia_nhan_vien(nv_order: List[dict], so_chinh: int, so_phu: int,
                    ld_co_sp: bool) -> Tuple[List[dict], List[dict]]:
    """
    Chia nhân viên thành nhóm trực chính và trực phụ.

    Nếu Lãnh đạo chưa giữ vai song phương thì kéo đúng 1 người biết song phương
    lên đầu nhóm trực chính — người ở nhóm phụ về sớm nên không thay vai được.
    Nếu Lãnh đạo đã giữ vai thì `nv_order` vốn đã xếp người không biết song
    phương lên trước trong từng mức số ca (tham số `tranh_sp`), không cần đảo gì.
    """
    if not ld_co_sp:
        biet_sp = [p for p in nv_order if p.get("can_do_sp")]
        if biet_sp:
            nv_order = biet_sp[:1] + [p for p in nv_order if p["id"] != biet_sp[0]["id"]]
    return nv_order[:so_chinh], nv_order[so_chinh:so_chinh + so_phu]


# ══════════════════════════════════════════════════════════════
# BUILD & SAVE SHIFT
# ══════════════════════════════════════════════════════════════

def _build_shift(shift_date: str, shift_type: str, leaders: List[dict],
                 sp: Optional[dict], nvs: List[dict],
                 sp_warning: Optional[str] = None,
                 nv_phu: Optional[List[dict]] = None) -> dict:
    return {
        "shift_date":  shift_date,
        "shift_type":   shift_type,
        "leader_ids":   json.dumps([p["id"] for p in leaders]),
        "sp_id":        sp["id"] if sp else None,
        "sp_warning":   sp_warning,
        "nv_ids":       json.dumps([p["id"] for p in nvs]),
        "nv_count":     len(nvs),
        "nv_phu_ids":   json.dumps([p["id"] for p in (nv_phu or [])]),
        "nv_phu_count": len(nv_phu or []),
        "is_auto":      1,
        "status":       "draft",
    }


def _save_shift(db: sqlite3.Connection, data: dict) -> int:
    """Lưu 1 ca vào DB. Trả về shift_id mới."""
    cursor = db.execute(
        "INSERT INTO duty_shifts (shift_date, shift_type, leader_ids, sp_id, sp_warning, "
        "nv_ids, nv_count, nv_phu_ids, nv_phu_count, is_auto, status, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (data["shift_date"], data["shift_type"], data["leader_ids"], data["sp_id"],
         data.get("sp_warning"), data["nv_ids"], data["nv_count"],
         data.get("nv_phu_ids", "[]"), data.get("nv_phu_count", 0),
         data["is_auto"], data["status"], _now())
    )
    return cursor.lastrowid


# ══════════════════════════════════════════════════════════════
# GENERATE TỪNG LOẠI CA
# ══════════════════════════════════════════════════════════════

def _generate_ca(db: sqlite3.Connection, date_str: str, year: int,
                 ld_role: str, nv_role: str, shift_type: str,
                 rng: random.Random) -> Tuple[List[dict], List[dict]]:
    """
    Sinh MỘT ca trực cho mọi loại ca — ngày thường, thứ 6, cut-off, quyết toán.
    Bốn loại chỉ khác nhau ở số người khai báo và kênh vòng xoay, nên dùng
    chung một đường; ngày quyết toán thì có thêm nhóm trực phụ.

    Số người lấy từ khai báo ở tab Cài đặt, thiếu thì không lập ca.
    Chỉ thứ 6 luân phiên tất định, các loại còn lại bốc ngẫu nhiên trong
    nhóm ít ca nhất.
    """
    randomize = (shift_type != "friday")
    so_ld, so_chinh, so_phu = get_cau_hinh_ca(db, year, shift_type)

    pool = get_available_pool(db, date_str)
    requests = get_requests_for_date(db, date_str, year)
    warnings: List[dict] = []

    ld_order = _order_pool(db, pool["LD"], requests, "LD", year, ld_role, date_str, rng, randomize)

    # ── Luật cứng: thiếu người so với khai báo thì KHÔNG hình thành ca ──
    if len(ld_order) < so_ld or len(pool["NV"]) < so_chinh + so_phu:
        if len(ld_order) < so_ld:
            ly_do = f"chỉ có {len(ld_order)}/{so_ld} Lãnh đạo khả dụng"
        else:
            ly_do = f"chỉ có {len(pool['NV'])}/{so_chinh + so_phu} nhân viên khả dụng"
        can_co = f"{so_ld} Lãnh đạo + {so_chinh} nhân viên"
        if so_phu:
            can_co += f" trực chính + {so_phu} trực phụ"
        return [], [{"date": date_str, "type": "khong_du_nguoi",
                     "msg": f"Ngày {date_str} không lập được ca trực — {ly_do}. "
                            f"Ca trực bắt buộc {can_co}."}]

    # Chọn Lãnh đạo trước để biết ca đã có người song phương chưa, rồi mới xếp
    # nhân viên — biết điều đó thì mới xếp được đúng thứ tự ưu tiên.
    leaders  = _chon_lanh_dao(ld_order, so_ld,
                              any(p.get("can_do_sp") for p in pool["NV"]))
    ld_co_sp = any(p.get("can_do_sp") for p in leaders)
    nv_order = _order_pool(db, pool["NV"], requests, "NV", year, nv_role, date_str,
                           rng, randomize, tranh_sp=ld_co_sp)
    nv_chinh, nv_phu = _chia_nhan_vien(nv_order, so_chinh, so_phu, ld_co_sp)
    sp, sp_warn = resolve_sp_role(leaders, nv_chinh, nv_phu)
    # sp tách khỏi nv_ids để hiển thị riêng, giống đường sửa tay
    nvs = [p for p in nv_chinh if sp is None or p["id"] != sp["id"]]

    # ── Luật mềm: vẫn lập ca, chỉ cảnh báo ──
    if sp_warn == "no_sp_chinh":
        warnings.append({"date": date_str, "type": "no_sp_chinh",
                         "msg": f"Ngày {date_str}: Lãnh đạo và nhóm trực chính không có "
                                f"ai xử lý song phương"})
    elif sp_warn == "multi_sp":
        warnings.append({"date": date_str, "type": "multi_sp",
                         "msg": f"Ngày {date_str} có nhiều hơn 1 người xử lý song phương"})

    # ── Ghi vòng xoay sau khi đã chốt tổ hợp (tránh tính cho ứng viên bị loại) ──
    for p in leaders:
        _update_rotation(db, p["id"], year, ld_role, date_str)
    for p in nv_chinh + nv_phu:
        _update_rotation(db, p["id"], year, nv_role, date_str)

    shift = _build_shift(date_str, shift_type, leaders, sp, nvs,
                         sp_warning=sp_warn, nv_phu=nv_phu)
    return [shift], warnings


def _generate_ngay_dac_biet(db: sqlite3.Connection, date_str: str, year: int,
                            shift_type: str, ld_role: str, nv_role: str,
                            rng: random.Random) -> Tuple[List[dict], List[dict]]:
    """Cut-off / quyết toán chỉ sinh khi ngày đó đã được xác nhận ở tab Ngày đặc biệt."""
    sd = get_special_day(db, date_str)
    if not sd or not sd["is_confirmed"]:
        ten = "cut-off" if shift_type == "cutoff" else "quyết toán"
        return [], [{"date": date_str, "type": f"{shift_type}_unconfirmed",
                     "msg": f"Ngày {ten} {date_str} chưa được xác nhận — bỏ qua"}]
    return _generate_ca(db, date_str, year, ld_role, nv_role, shift_type, rng)


# ══════════════════════════════════════════════════════════════
# ENTRY POINTS
# ══════════════════════════════════════════════════════════════

def _process_day(db: sqlite3.Connection, date_str: str, year: int,
                 confirmed_types: set, rng: random.Random) -> Tuple[int, int, List[dict]]:
    """Sinh ca cho 1 ngày. Trả (created, skipped, warnings).
    Ngày đặc biệt được ưu tiên trước thứ 6 — quyết toán rơi vào thứ 6 vẫn là
    ca quyết toán."""
    sd = get_special_day(db, date_str)
    day_type = sd["day_type"] if (sd and sd["is_confirmed"]) else None

    if day_type == "settlement":
        shifts, warns = _generate_ngay_dac_biet(
            db, date_str, year, "settlement_main", "LD", "NV", rng)
    elif day_type == "cutoff":
        shifts, warns = _generate_ngay_dac_biet(
            db, date_str, year, "cutoff", "LD_cutoff", "NV_cutoff", rng)
    elif is_friday(date_str):
        shifts, warns = _generate_ca(db, date_str, year, "LD_friday", "NV_friday",
                                     "friday", rng)
    else:
        shifts, warns = _generate_ca(db, date_str, year, "LD", "NV", "normal", rng)

    created = 0
    skipped = 0
    for shift_data in shifts:
        if shift_data["shift_type"] in confirmed_types:
            skipped += 1
        else:
            _save_shift(db, shift_data)
            created += 1

    return created, skipped, warns


def generate_schedule_for_week(db: sqlite3.Connection, week_start_str: str,
                                overwrite_draft: bool = False,
                                overwrite_confirmed: bool = False,
                                seed: Optional[int] = None) -> dict:
    """Sinh lịch trực cho 1 tuần (Mon-Fri). Bỏ qua ngày lễ và ngày đã confirmed.
    `seed` chỉ dùng cho test — production để None (bốc ngẫu nhiên thật)."""
    rng = random.Random(seed)
    year = int(week_start_str[:4])
    holiday_dates = get_holiday_dates(db, year)
    week_dates = get_week_dates(week_start_str)
    working_days = [d for d in week_dates if d not in holiday_dates]

    all_warnings: List[dict] = []
    created = 0
    skipped = 0

    for date_str in working_days:
        existing = db.execute(
            "SELECT shift_type, status FROM duty_shifts WHERE shift_date=?", (date_str,)
        ).fetchall()

        confirmed_shifts = [s for s in existing if s["status"] == "confirmed"]
        draft_shifts     = [s for s in existing if s["status"] == "draft"]
        confirmed_types  = {s["shift_type"] for s in confirmed_shifts}

        if existing:
            if confirmed_shifts and not overwrite_confirmed:
                if draft_shifts and overwrite_draft:
                    db.execute(
                        "DELETE FROM duty_shifts WHERE shift_date=? AND status='draft'",
                        (date_str,)
                    )
                elif draft_shifts:
                    skipped += len(existing)
                    continue
                else:
                    skipped += len(confirmed_shifts)
                    continue
            elif not overwrite_draft:
                skipped += len(existing)
                continue
            else:
                if overwrite_confirmed:
                    db.execute("DELETE FROM duty_shifts WHERE shift_date=?", (date_str,))
                    confirmed_types = set()
                else:
                    db.execute(
                        "DELETE FROM duty_shifts WHERE shift_date=? AND status='draft'",
                        (date_str,)
                    )

        c, s, w = _process_day(db, date_str, year, confirmed_types, rng)
        created += c
        skipped += s
        all_warnings.extend(w)

    db.commit()
    return {"created": created, "skipped": skipped, "warnings": all_warnings,
            "week_start": week_start_str}


def generate_schedule(db: sqlite3.Connection, month: int, year: int,
                      overwrite_draft: bool = False,
                      seed: Optional[int] = None) -> dict:
    """Sinh lịch trực theo tuần cho tháng chỉ định.
    `seed` chỉ dùng cho test — production để None (bốc ngẫu nhiên thật)."""
    rng = random.Random(seed)
    holiday_dates = get_holiday_dates(db, year)

    first_day = _date(year, month, 1)
    start_monday = first_day - timedelta(days=first_day.weekday())
    last_day = _date(year, month, _cal.monthrange(year, month)[1])
    end_friday = last_day + timedelta(days=(4 - last_day.weekday()) % 7)

    if end_friday.year != year:
        holiday_dates = holiday_dates | get_holiday_dates(db, end_friday.year)

    working_days = []
    cur = start_monday
    while cur <= end_friday:
        ds = cur.isoformat()
        if cur.weekday() < 5 and ds not in holiday_dates:
            working_days.append(ds)
        cur += timedelta(days=1)

    all_warnings: List[dict] = []
    total_created = 0
    total_skipped = 0

    for date_str in working_days:
        existing = db.execute(
            "SELECT shift_type, status FROM duty_shifts WHERE shift_date=?", (date_str,)
        ).fetchall()

        if existing:
            if any(s["status"] == "confirmed" for s in existing):
                total_skipped += len(existing)
                continue
            if not overwrite_draft:
                total_skipped += len(existing)
                continue
            db.execute("DELETE FROM duty_shifts WHERE shift_date=?", (date_str,))

        c, s, w = _process_day(db, date_str, year, set(), rng)
        total_created += c
        total_skipped += s
        all_warnings.extend(w)

    db.commit()
    return {"created": total_created, "skipped": total_skipped,
            "warnings": all_warnings, "month": month, "year": year}


# ══════════════════════════════════════════════════════════════
# ROTATION MANAGEMENT
# ══════════════════════════════════════════════════════════════

ALL_ROTATION_ROLES = ["LD", "NV", "LD_friday", "NV_friday", "LD_cutoff", "NV_cutoff"]


def reset_rotation(db: sqlite3.Connection, year: int) -> None:
    """Xóa toàn bộ rotation_state của năm. Lazy-init sẽ tạo lại khi generate."""
    db.execute("DELETE FROM duty_rotation_state WHERE year=?", (year,))
    db.commit()
