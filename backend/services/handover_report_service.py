"""Tính chứng từ nộp đúng hạn / quá hạn theo phòng.

Ngày nộp thực tế lấy từ `entry_change_logs` — timestamp sớm nhất của action
'handover' (chuyên viên nộp) hoặc 'edited_hkv' (HKV nhập trực tiếp).

Không dùng `handovers.handover_date`: khi nhập qua lưới, cột này được gán bằng
đúng `transaction_date`, nên khoảng cách giữa hai ngày luôn bằng 0 và mọi
chứng từ đều bị coi là đúng hạn.

Chứng từ không có log nộp (dữ liệu import cũ) không có ngày nộp ở bất kỳ đâu
trong DB → bị loại khỏi báo cáo, đếm riêng ở `no_submit_date`.
"""
import logging
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import FrozenSet, Optional

log = logging.getLogger(__name__)

# Hạn nộp: trong vòng 1 ngày làm việc kể từ ngày giao dịch
DEADLINE_WORKING_DAYS = 1

# Action đánh dấu chứng từ được nộp lần đầu
_SUBMIT_ACTIONS = ("handover", "edited_hkv")

# Nới ngày tra cứu lễ/phép ra trước kỳ báo cáo để phủ hết khoảng tx → nộp
_LOOKUP_PAD_DAYS = 35


def working_days_between(
    start_exclusive: date,
    end_inclusive: date,
    holiday_dates: FrozenSet[date],
    leave_dates: FrozenSet[date] = frozenset(),
) -> int:
    """Đếm ngày làm việc trong (start, end]. Bỏ T7/CN, ngày lễ, ngày nghỉ phép."""
    count = 0
    d = start_exclusive + timedelta(days=1)
    while d <= end_inclusive:
        if d.weekday() < 5 and d not in holiday_dates and d not in leave_dates:
            count += 1
        d += timedelta(days=1)
    return count


def _parse_submit_date(raw) -> Optional[date]:
    if not raw:
        return None
    s = str(raw)
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        log.warning("Không đọc được timestamp nộp chứng từ: %r", raw)
        return None


def _load_holidays(db: sqlite3.Connection, lo: date, hi: date) -> FrozenSet[date]:
    rows = db.execute(
        "SELECT date FROM public_holidays WHERE date >= ? AND date <= ?",
        (lo.isoformat(), hi.isoformat()),
    ).fetchall()
    return frozenset(date.fromisoformat(r["date"]) for r in rows)


def _load_staff_leave(db: sqlite3.Connection, lo: date, hi: date) -> dict:
    """Ngày nghỉ phép đã duyệt của từng nhân viên (chỉ ngày trong tuần)."""
    rows = db.execute(
        """SELECT staff_id, start_date, end_date FROM leave_records
           WHERE status = 'approved' AND end_date >= ? AND start_date <= ?""",
        (lo.isoformat(), hi.isoformat()),
    ).fetchall()

    acc: dict = defaultdict(set)
    for r in rows:
        d = max(date.fromisoformat(r["start_date"]), lo)
        end = min(date.fromisoformat(r["end_date"]), hi)
        while d <= end:
            if d.weekday() < 5:
                acc[r["staff_id"]].add(d)
            d += timedelta(days=1)
    return {sid: frozenset(days) for sid, days in acc.items()}


def _fetch_entries(db: sqlite3.Connection, period_start: date, period_end: date) -> list:
    """Chứng từ có ngày giao dịch trong kỳ VÀ có log nộp.

    INNER JOIN với entry_change_logs → chứng từ cũ không có log tự động bị loại.
    """
    return db.execute(
        f"""SELECT de.id, de.transaction_date, de.sheet_count, de.staff_id,
                   h.received_by_id,
                   d.id AS dept_id, d.name AS dept_name,
                   MIN(ecl.timestamp) AS submitted_at,
                   u.full_name, u.ipcas_code, u.username, u.payment_username
            FROM document_entries de
            JOIN handovers h ON de.handover_id = h.id
            JOIN departments d ON h.department_id = d.id
            JOIN entry_change_logs ecl
              ON ecl.entry_id = de.id
             AND ecl.action IN ({','.join('?' * len(_SUBMIT_ACTIONS))})
            LEFT JOIN user_tttt u ON de.staff_id = u.id
            WHERE de.transaction_date >= ? AND de.transaction_date < ?
            GROUP BY de.id
            ORDER BY d.name, de.transaction_date""",
        (*_SUBMIT_ACTIONS, period_start.isoformat(), period_end.isoformat()),
    ).fetchall()


def _count_without_submit_log(db: sqlite3.Connection, period_start: date, period_end: date) -> int:
    return db.execute(
        f"""SELECT COUNT(*) FROM document_entries de
            WHERE de.transaction_date >= ? AND de.transaction_date < ?
              AND NOT EXISTS (
                  SELECT 1 FROM entry_change_logs ecl
                  WHERE ecl.entry_id = de.id
                    AND ecl.action IN ({','.join('?' * len(_SUBMIT_ACTIONS))})
              )""",
        (period_start.isoformat(), period_end.isoformat(), *_SUBMIT_ACTIONS),
    ).fetchone()[0] or 0


def _staff_display_name(row) -> str:
    return row["full_name"] or row["payment_username"] or row["username"] or f"ID {row['staff_id']}"


def compute_period(db: sqlite3.Connection, year: int, month: int) -> dict:
    """Thống kê nộp đúng hạn / quá hạn của kỳ (theo ngày giao dịch)."""
    period_start = date(year, month, 1)
    period_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    rows = _fetch_entries(db, period_start, period_end)

    # ── Khoảng tra cứu lễ/phép: phủ từ trước kỳ đến ngày nộp muộn nhất ──
    submit_dates = [d for d in (_parse_submit_date(r["submitted_at"]) for r in rows) if d]
    lookup_lo = period_start - timedelta(days=_LOOKUP_PAD_DAYS)
    lookup_hi = max([period_end, *submit_dates]) if submit_dates else period_end

    holidays = _load_holidays(db, lookup_lo, lookup_hi)
    staff_leave = _load_staff_leave(db, lookup_lo, lookup_hi)

    by_dept: dict = {}
    late_entries: list = []
    overall_total = 0
    overall_on_time = 0

    for r in rows:
        submitted = _parse_submit_date(r["submitted_at"])
        if not submitted:
            continue

        tx_date = date.fromisoformat(r["transaction_date"])
        recv_id = r["received_by_id"]
        receiver_leave = staff_leave.get(recv_id, frozenset()) if recv_id else frozenset()

        elapsed = working_days_between(tx_date, submitted, holidays, receiver_leave)
        days_late = max(0, elapsed - DEADLINE_WORKING_DAYS)
        on_time = days_late == 0

        dept_name = r["dept_name"]
        bucket = by_dept.setdefault(
            dept_name, {"dept_id": r["dept_id"], "total": 0, "on_time": 0}
        )
        bucket["total"] += 1
        overall_total += 1
        if on_time:
            bucket["on_time"] += 1
            overall_on_time += 1
        else:
            late_entries.append({
                "entry_id":         r["id"],
                "dept_id":          r["dept_id"],
                "dept_name":        dept_name,
                "staff_id":         r["staff_id"],
                "staff_name":       _staff_display_name(r),
                "ipcas_code":       r["ipcas_code"] or "",
                "transaction_date": r["transaction_date"],
                "submitted_date":   submitted.isoformat(),
                "days_late":        days_late,
                "sheet_count":      r["sheet_count"],
            })

    late_entries.sort(key=lambda e: (e["dept_name"], -e["days_late"], e["transaction_date"]))

    by_dept_list = []
    for dept_name, data in sorted(by_dept.items()):
        t, ot = data["total"], data["on_time"]
        by_dept_list.append({
            "dept_id":   data["dept_id"],
            "dept_name": dept_name,
            "total":     t,
            "on_time":   ot,
            "late":      t - ot,
            "rate":      round(ot / t * 100, 1) if t else None,
        })

    return {
        "period": f"{year:04d}-{month:02d}",
        "overall": {
            "total":   overall_total,
            "on_time": overall_on_time,
            "late":    overall_total - overall_on_time,
            "rate":    round(overall_on_time / overall_total * 100, 1) if overall_total else None,
        },
        "by_dept":        by_dept_list,
        "late_entries":   late_entries,
        "no_submit_date": _count_without_submit_log(db, period_start, period_end),
    }
