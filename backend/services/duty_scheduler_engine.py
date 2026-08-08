"""
Duty Scheduler Engine — thuật toán phân lịch trực tự động.
Raw SQLite3. Staff được biểu diễn dưới dạng dict (không ORM).

Loại ca: normal | friday | cutoff | settlement_main | settlement_sub
Rotation roles: LD | NV | LD_friday | NV_friday | LD_cutoff | NV_cutoff

Ca ngày thường / thứ 6: bắt buộc 1 Lãnh đạo + 2 người, trong đó ĐÚNG 1 người
xử lý song phương (can_do_sp) — có thể là Lãnh đạo hoặc nhân viên.
Ngày thường bốc ngẫu nhiên trong nhóm ít ca nhất; thứ 6 luân phiên tất định.
"""
import json
import random
import sqlite3
import calendar as _cal
from datetime import datetime, date as _date, timedelta, timezone
from typing import List, Optional, Tuple

from backend.services.duty_staff_service import get_available_pool
from backend.services.duty_constraint_service import (
    get_requests_for_date, get_special_day, get_holiday_dates,
    get_shift_config, get_week_assignees,
)
from backend.services.duty_calendar_utils import get_week_dates, is_friday
from backend.services.duty_rules import get_cau_hinh_ca, resolve_sp_role

_VN_TZ = timezone(timedelta(hours=7))
DEFAULT_NV_COUNT = 2


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


def _sort_by_rotation(db: sqlite3.Connection, candidates: List[dict],
                      year: int, role: str, current_date: str = None) -> List[dict]:
    def sort_key(p: dict):
        s = _get_rotation_state(db, p["id"], year, role)
        day_miss = _preferred_day_mismatch(s.get("last_used"), current_date)
        return (
            s["shift_count"],
            day_miss,
            s["last_used"] or "0000-00-00",
            s["position"],
            p["id"],
        )
    return sorted(candidates, key=sort_key)


def _pick_by_rotation(db: sqlite3.Connection, candidates: List[dict],
                      year: int, role: str, current_date: str = None) -> Optional[dict]:
    if not candidates:
        return None
    return _sort_by_rotation(db, candidates, year, role, current_date)[0]


# ══════════════════════════════════════════════════════════════
# CHỌN TỪNG VAI TRÒ
# ══════════════════════════════════════════════════════════════

def _pick_leader(db: sqlite3.Connection, pool_ld: List[dict], requests: dict,
                 year: int, date_str: str,
                 rotation_role: str = "LD") -> Optional[dict]:
    if not pool_ld:
        return None

    week_ids = get_week_assignees(db, date_str)
    once_ids = set(requests.get("once_ids", set()))
    requested_ids = set(requests.get("LD", []))

    forced     = [p for p in pool_ld if p["id"] in once_ids]
    fresh_ld   = [p for p in pool_ld if p["id"] not in week_ids and p["id"] not in once_ids]
    repeat_ld  = [p for p in pool_ld if p["id"] in week_ids and p["id"] not in once_ids]

    if forced:
        candidates = forced
    elif fresh_ld:
        requested = [p for p in fresh_ld if p["id"] in requested_ids]
        candidates = requested if requested else fresh_ld
    else:
        requested = [p for p in repeat_ld if p["id"] in requested_ids]
        candidates = requested if requested else repeat_ld

    if not candidates:
        return None

    winner = _pick_by_rotation(db, candidates, year, rotation_role, current_date=date_str)
    if winner:
        _update_rotation(db, winner["id"], year, rotation_role, date_str)
    return winner


def _pick_sp(db: sqlite3.Connection, pool: dict, requests: dict,
             year: int, date_str: str,
             rotation_role: str = "NV") -> Tuple[Optional[dict], Optional[str]]:
    pool_sp = pool["SP"]
    week_ids = get_week_assignees(db, date_str)

    fresh_sp = [p for p in pool_sp if p["id"] not in week_ids]
    if fresh_sp:
        requested_ids = set(requests.get("SP", []))
        requested = [p for p in fresh_sp if p["id"] in requested_ids]
        candidates = requested if requested else fresh_sp
        winner = _pick_by_rotation(db, candidates, year, rotation_role, current_date=date_str)
        if winner:
            _update_rotation(db, winner["id"], year, rotation_role, date_str)
        return winner, None

    if pool_sp:
        requested_ids = set(requests.get("SP", []))
        requested = [p for p in pool_sp if p["id"] in requested_ids]
        candidates = requested if requested else pool_sp
        winner = _pick_by_rotation(db, candidates, year, rotation_role, current_date=date_str)
        if winner:
            _update_rotation(db, winner["id"], year, rotation_role, date_str)
        return winner, None

    return None, "no_sp"


def _pick_nvs(db: sqlite3.Connection, pool_nv: List[dict], requests: dict,
              year: int, date_str: str, nv_slots: int,
              rotation_role: str = "NV") -> List[dict]:
    week_ids = get_week_assignees(db, date_str)
    once_ids = set(requests.get("once_ids", set()))
    requested_ids = set(requests.get("NV", []))

    forced_nv   = [p for p in pool_nv if p["id"] in once_ids]
    fresh_nv    = [p for p in pool_nv if p["id"] not in week_ids and p["id"] not in once_ids]
    repeated_nv = [p for p in pool_nv if p["id"] in week_ids and p["id"] not in once_ids]

    ordered_pool: List[dict] = (
        forced_nv
        + [p for p in fresh_nv if p["id"] in requested_ids]
        + _sort_by_rotation(db, [p for p in fresh_nv if p["id"] not in requested_ids],
                            year, rotation_role, current_date=date_str)
        + [p for p in repeated_nv if p["id"] in requested_ids]
        + _sort_by_rotation(db, [p for p in repeated_nv if p["id"] not in requested_ids],
                            year, rotation_role, current_date=date_str)
    )

    selected: List[dict] = []
    seen: set = set()
    for p in ordered_pool:
        if len(selected) >= nv_slots:
            break
        if p["id"] not in seen:
            seen.add(p["id"])
            selected.append(p)
            _update_rotation(db, p["id"], year, rotation_role, date_str)

    return selected


def _pick_nvs_prefer_non_sp(db: sqlite3.Connection, pool_nv: List[dict], requests: dict,
                             year: int, date_str: str,
                             n_slots: int, nv_role: str) -> List[dict]:
    """Ưu tiên NV không có can_do_sp để tránh 2 SP-capable cùng ca."""
    non_sp = [p for p in pool_nv if not p.get("can_do_sp", 0)]
    if len(non_sp) >= n_slots:
        return _pick_nvs(db, non_sp, requests, year, date_str, n_slots, nv_role)
    return _pick_nvs(db, pool_nv, requests, year, date_str, n_slots, nv_role)


# ══════════════════════════════════════════════════════════════
# CA NGÀY THƯỜNG / THỨ 6 — 1 LD + 2 người, đúng 1 người song phương
# ══════════════════════════════════════════════════════════════

def _rank_candidates(db: sqlite3.Connection, candidates: List[dict], year: int,
                     role: str, date_str: str, rng: random.Random,
                     randomize: bool) -> List[dict]:
    """Xếp thứ tự ưu tiên trong 1 nhóm ứng viên. Thuần đọc — không ghi vòng xoay."""
    if not candidates:
        return []
    if not randomize:
        return _sort_by_rotation(db, candidates, year, role, date_str)

    # Ngẫu nhiên trong nhóm ít ca nhất, rồi tới nhóm ít ca kế tiếp
    counts = {p["id"]: _get_rotation_state(db, p["id"], year, role)["shift_count"]
              for p in candidates}
    ordered: List[dict] = []
    for c in sorted(set(counts.values())):
        group = [p for p in candidates if counts[p["id"]] == c]
        rng.shuffle(group)
        ordered.extend(group)
    return ordered


def _order_pool(db: sqlite3.Connection, people: List[dict], requests: dict, kind: str,
                year: int, role: str, date_str: str, rng: random.Random,
                randomize: bool) -> List[dict]:
    """Xếp pool theo tầng ưu tiên: đăng ký đích danh ngày > chưa trực trong tuần > đã trực."""
    week_ids = get_week_assignees(db, date_str)
    once_ids = set(requests.get("once_ids", set()))
    req_ids  = set(requests.get(kind, []))

    forced = [p for p in people if p["id"] in once_ids]
    rest   = [p for p in people if p["id"] not in once_ids]
    fresh  = [p for p in rest if p["id"] not in week_ids]
    repeat = [p for p in rest if p["id"] in week_ids]

    def _rank(group: List[dict]) -> List[dict]:
        return _rank_candidates(db, group, year, role, date_str, rng, randomize)

    def _layer(group: List[dict]) -> List[dict]:
        return (_rank([p for p in group if p["id"] in req_ids])
                + _rank([p for p in group if p["id"] not in req_ids]))

    return _rank(forced) + _layer(fresh) + _layer(repeat)


def _chon_to_hop(ld_order: List[dict], nv_order: List[dict],
                 so_ld: int, so_chinh: int, so_phu: int) -> Optional[Tuple]:
    """
    Chọn so_ld Lãnh đạo + so_chinh trực chính + so_phu trực phụ theo thứ tự
    ưu tiên đã xếp sẵn.

    Luật CỨNG: thiếu người so với số đã khai báo thì trả None — không hình
    thành ca trực. Luật MỀM (ít nhất 1 người song phương ở Lãnh đạo hoặc trực
    chính) chỉ cố gắng thoả, không thoả được thì vẫn lập ca kèm cảnh báo.
    """
    if len(ld_order) < so_ld or len(nv_order) < so_chinh + so_phu:
        return None

    # Nếu trong tầm với của nhóm nhân viên không có ai biết song phương thì
    # kéo Lãnh đạo biết song phương lên trước — mục tiêu là ca có người xử lý.
    trong_tam = nv_order[:so_chinh + so_phu]
    if not any(p.get("can_do_sp") for p in trong_tam):
        ld_order = ([p for p in ld_order if p.get("can_do_sp")]
                    + [p for p in ld_order if not p.get("can_do_sp")])

    leaders = ld_order[:so_ld]
    # Khai nhiều Lãnh đạo mà vơ trúng 2 người cùng biết song phương là lãng phí.
    # Thay người thứ hai trở đi bằng Lãnh đạo không biết song phương kế tiếp —
    # chỉ thay khi có sẵn người ngoài top, để không phá thứ tự vòng xoay.
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

    ld_co_sp = any(p.get("can_do_sp") for p in leaders)

    biet_sp  = [p for p in nv_order if p.get("can_do_sp")]
    khong_sp = [p for p in nv_order if not p.get("can_do_sp")]

    if ld_co_sp:
        # Lãnh đạo đã giữ vai → ưu tiên người không biết song phương cho đỡ dư
        uu_tien = khong_sp + biet_sp
    else:
        # Kéo đúng 1 người biết song phương lên đầu nhóm trực chính
        uu_tien = biet_sp[:1] + khong_sp + biet_sp[1:]

    nv_chinh = uu_tien[:so_chinh]
    nv_phu   = uu_tien[so_chinh:so_chinh + so_phu]
    return leaders, nv_chinh, nv_phu


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

def _generate_normal_or_friday(db: sqlite3.Connection, date_str: str, year: int,
                                ld_role: str, nv_role: str, shift_type: str,
                                rng: random.Random) -> Tuple[List[dict], List[dict]]:
    """Số người lấy từ khai báo ở tab Cài đặt, thiếu thì không lập ca.
    Ngày thường bốc ngẫu nhiên trong nhóm ít ca nhất; thứ 6 luân phiên tất định."""
    randomize = (shift_type == "normal")
    so_ld, so_chinh, so_phu = get_cau_hinh_ca(db, year, shift_type)

    pool = get_available_pool(db, date_str)
    requests = get_requests_for_date(db, date_str, year)
    warnings: List[dict] = []

    ld_order = _order_pool(db, pool["LD"], requests, "LD", year, ld_role, date_str, rng, randomize)
    nv_order = _order_pool(db, pool["NV"], requests, "NV", year, nv_role, date_str, rng, randomize)

    plan = _chon_to_hop(ld_order, nv_order, so_ld, so_chinh, so_phu)

    # ── Luật cứng: thiếu người so với khai báo thì KHÔNG hình thành ca ──
    if plan is None:
        if len(ld_order) < so_ld:
            ly_do = f"chỉ có {len(ld_order)}/{so_ld} Lãnh đạo khả dụng"
        else:
            ly_do = f"chỉ có {len(nv_order)}/{so_chinh + so_phu} nhân viên khả dụng"
        can_co = f"{so_ld} Lãnh đạo + {so_chinh} nhân viên"
        if so_phu:
            can_co += f" trực chính + {so_phu} trực phụ"
        return [], [{"date": date_str, "type": "khong_du_nguoi",
                     "msg": f"Ngày {date_str} không lập được ca trực — {ly_do}. "
                            f"Ca trực bắt buộc {can_co}."}]

    leaders, nv_chinh, nv_phu = plan
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


def _generate_cutoff(db: sqlite3.Connection, date_str: str, year: int,
                     nv_count: int) -> Tuple[List[dict], List[dict]]:
    sd = get_special_day(db, date_str)
    if not sd or not sd["is_confirmed"]:
        return [], [{"date": date_str, "type": "cutoff_unconfirmed",
                     "msg": f"Ngày cut-off {date_str} chưa được xác nhận — bỏ qua"}]

    pool = get_available_pool(db, date_str)
    requests = get_requests_for_date(db, date_str, year)
    warnings = []

    leader = _pick_leader(db, pool["LD"], requests, year, date_str, "LD_cutoff")

    if leader and leader.get("can_do_sp"):
        sp, sp_warn = None, "leader_sp"
    else:
        sp, sp_warn = _pick_sp(db, pool, requests, year, date_str, rotation_role="NV_cutoff")
        if not leader:
            warnings.append({"date": date_str, "type": "no_leader",
                             "msg": f"Không có Lãnh đạo khả dụng ngày cutoff {date_str}"})

    nv_pool = [p for p in pool["NV"] if p["id"] != (sp["id"] if sp else None)]
    if sp:
        nvs = _pick_nvs_prefer_non_sp(db, nv_pool, requests, year, date_str,
                                      max(0, nv_count - 1), "NV_cutoff")
    else:
        nvs = _pick_nvs_prefer_non_sp(db, nv_pool, requests, year, date_str,
                                      nv_count, "NV_cutoff")

    shift = _build_shift(date_str, "cutoff", [leader] if leader else [], sp, nvs,
                         sp_warning=sp_warn)
    return [shift], warnings


def _generate_settlement(db: sqlite3.Connection, date_str: str, year: int,
                          nv_count: int) -> Tuple[List[dict], List[dict]]:
    """Ca quyết toán: 2 cụm cùng ngày (main + sub)."""
    sd = get_special_day(db, date_str)
    if not sd or not sd["is_confirmed"]:
        return [], [{"date": date_str, "type": "settlement_unconfirmed",
                     "msg": f"Ngày quyết toán {date_str} chưa được xác nhận — bỏ qua"}]

    pool = get_available_pool(db, date_str)
    requests = get_requests_for_date(db, date_str, year)
    warnings = []

    # ─── Ca chính ────────────────────────────────────────────
    leader = _pick_leader(db, pool["LD"], requests, year, date_str, "LD")

    if leader and leader.get("can_do_sp"):
        sp, sp_warn = None, "leader_sp"
    else:
        sp, sp_warn = _pick_sp(db, pool, requests, year, date_str)
        if not leader:
            warnings.append({"date": date_str, "type": "no_leader",
                             "msg": f"Không có Lãnh đạo khả dụng ngày quyết toán {date_str}"})

    nv_pool_main = [p for p in pool["NV"] if p["id"] != (sp["id"] if sp else None)]
    if sp:
        nvs_main = _pick_nvs_prefer_non_sp(db, nv_pool_main, requests, year, date_str,
                                            max(0, nv_count - 1), "NV")
    else:
        nvs_main = _pick_nvs_prefer_non_sp(db, nv_pool_main, requests, year, date_str,
                                            nv_count, "NV")

    shift_main = _build_shift(date_str, "settlement_main", [leader] if leader else [],
                              sp, nvs_main, sp_warning=sp_warn)

    # ─── Ca phụ ──────────────────────────────────────────────
    used_ids = {leader["id"]} if leader else set()
    if sp:
        used_ids.add(sp["id"])
    used_ids.update(p["id"] for p in nvs_main)
    remaining_nv = [p for p in pool["NV"] if p["id"] not in used_ids]
    sub_count = max(1, len(remaining_nv) // 2)
    nvs_sub = remaining_nv[:sub_count]  # không cập nhật rotation

    shift_sub = _build_shift(date_str, "settlement_sub", [], None, nvs_sub)

    return [shift_main, shift_sub], warnings


# ══════════════════════════════════════════════════════════════
# ENTRY POINTS
# ══════════════════════════════════════════════════════════════

def _process_day(db: sqlite3.Connection, date_str: str, year: int, nv_count: int,
                 overwrite_draft: bool, overwrite_confirmed: bool,
                 confirmed_types: set, rng: random.Random) -> Tuple[int, int, List[dict]]:
    """Sinh ca cho 1 ngày. Trả (created, skipped, warnings)."""
    sd = get_special_day(db, date_str)
    day_type = sd["day_type"] if (sd and sd["is_confirmed"]) else None

    if day_type == "settlement":
        shifts, warns = _generate_settlement(db, date_str, year, nv_count)
    elif day_type == "cutoff":
        shifts, warns = _generate_cutoff(db, date_str, year, nv_count)
    elif is_friday(date_str):
        shifts, warns = _generate_normal_or_friday(
            db, date_str, year, "LD_friday", "NV_friday", "friday", rng
        )
    else:
        shifts, warns = _generate_normal_or_friday(
            db, date_str, year, "LD", "NV", "normal", rng
        )

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
    config = get_shift_config(db, year)
    nv_count = config["nv_count"] if config else DEFAULT_NV_COUNT

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

        c, s, w = _process_day(db, date_str, year, nv_count,
                                overwrite_draft, overwrite_confirmed, confirmed_types, rng)
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
    config = get_shift_config(db, year)
    nv_count = config["nv_count"] if config else DEFAULT_NV_COUNT
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

        c, s, w = _process_day(db, date_str, year, nv_count, overwrite_draft, False, set(), rng)
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

_DUTY_ROLE_MAP = {
    "LD": ["LD", "LD_friday", "LD_cutoff"],
    "NV": ["NV", "NV_friday", "NV_cutoff"],
}


def reset_rotation(db: sqlite3.Connection, year: int) -> None:
    """Xóa toàn bộ rotation_state của năm. Lazy-init sẽ tạo lại khi generate."""
    db.execute("DELETE FROM duty_rotation_state WHERE year=?", (year,))
    db.commit()
