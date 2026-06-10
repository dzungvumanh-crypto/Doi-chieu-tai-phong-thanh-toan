"""
Tiện ích lịch: ngày nghỉ lễ VN, ngày làm việc, cutoff, thứ Sáu.
"""
import calendar
from datetime import date, timedelta
from typing import List

try:
    from lunardate import LunarDate
    _LUNAR_OK = True
except ImportError:
    _LUNAR_OK = False

# ── Ngày lễ dương lịch cố định (tháng, ngày) ─────────────────────────────────
_FIXED_SOLAR = {
    (1,  1): "Tết Dương lịch",
    (4, 30): "Ngày Giải phóng miền Nam",
    (5,  1): "Quốc tế Lao động",
    (9,  2): "Quốc khánh",
}

# ── Ngày lễ âm lịch (tháng âm, ngày âm) → cần convert sang dương ────────────
_LUNAR_HOLIDAYS = {
    (1, 1): "Tết Nguyên Đán (mùng 1)",
    (1, 2): "Tết Nguyên Đán (mùng 2)",
    (1, 3): "Tết Nguyên Đán (mùng 3)",
    (1, 4): "Tết Nguyên Đán (mùng 4)",
    (1, 5): "Tết Nguyên Đán (mùng 5)",
    (3, 10): "Giỗ Tổ Hùng Vương",
}


def get_vn_holidays(year: int) -> List[dict]:
    """Trả danh sách ngày nghỉ lễ VN năm `year`. Mỗi phần tử: {'date': 'YYYY-MM-DD', 'label': str}"""
    holidays = []
    for (m, d), label in _FIXED_SOLAR.items():
        holidays.append({"date": f"{year}-{m:02d}-{d:02d}", "label": label})

    if _LUNAR_OK:
        for (lm, ld), label in _LUNAR_HOLIDAYS.items():
            try:
                solar = LunarDate(year, lm, ld).toSolarDate()
                holidays.append({"date": solar.strftime("%Y-%m-%d"), "label": label})
            except Exception:
                pass
    else:
        _FALLBACK_2026 = [
            ("2026-02-17", "Tết Nguyên Đán (mùng 1)"),
            ("2026-02-18", "Tết Nguyên Đán (mùng 2)"),
            ("2026-02-19", "Tết Nguyên Đán (mùng 3)"),
            ("2026-02-20", "Tết Nguyên Đán (mùng 4)"),
            ("2026-02-21", "Tết Nguyên Đán (mùng 5)"),
            ("2026-04-28", "Giỗ Tổ Hùng Vương"),
        ]
        for ds, label in _FALLBACK_2026:
            if ds.startswith(str(year)):
                holidays.append({"date": ds, "label": label})
    return holidays


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def is_friday(date_str: str) -> bool:
    return date.fromisoformat(date_str).weekday() == 4


def get_week_dates(start_date: str) -> List[str]:
    """Trả 5 ngày Mon-Fri của tuần chứa start_date."""
    d = date.fromisoformat(start_date)
    d = d - timedelta(days=d.weekday())
    return [(d + timedelta(days=i)).isoformat() for i in range(5)]


def get_month_dates(month: int, year: int) -> List[str]:
    last_day = calendar.monthrange(year, month)[1]
    return [date(year, month, d).isoformat() for d in range(1, last_day + 1)]


def get_month_working_days(month: int, year: int, holiday_dates: set) -> List[str]:
    result = []
    for ds in get_month_dates(month, year):
        d = date.fromisoformat(ds)
        if not is_weekend(d) and ds not in holiday_dates:
            result.append(ds)
    return result


def compute_cutoff_dates(month: int, year: int, holiday_dates: set) -> List[str]:
    """Tính 2 ngày làm việc cuối tháng (cut-off)."""
    last_day = calendar.monthrange(year, month)[1]
    found = []
    for day in range(last_day, 0, -1):
        ds = date(year, month, day).isoformat()
        d = date.fromisoformat(ds)
        if not is_weekend(d) and ds not in holiday_dates:
            found.append(ds)
        if len(found) == 2:
            break
    return list(reversed(found))


def week_start_of_date(date_str: str) -> str:
    d = date.fromisoformat(date_str)
    return (d - timedelta(days=d.weekday())).isoformat()
