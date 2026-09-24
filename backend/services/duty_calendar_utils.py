"""
Tiện ích lịch: ngày nghỉ lễ VN, ngày làm việc, cutoff, thứ Sáu.
"""
import calendar
import logging
from datetime import date, timedelta
from typing import List

_log = logging.getLogger(__name__)

try:
    from lunardate import LunarDate
except ImportError:
    LunarDate = None

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


def _doi_am_duong(ld) -> date:
    # lunardate 0.3 đổi tên toSolarDate -> to_solar_date, bản sau bỏ tên cũ. Máy chủ
    # đang 0.2.2 (chỉ tên cũ), máy dev 0.3.0 (cả hai) -> tra lúc chạy, không ghim bản.
    doi = getattr(ld, "to_solar_date", None) or ld.toSolarDate
    return doi()


def get_vn_holidays(year: int) -> List[dict]:
    """Trả danh sách ngày nghỉ lễ VN năm `year`. Mỗi phần tử: {'date': 'YYYY-MM-DD', 'label': str}"""
    holidays = []
    for (m, d), label in _FIXED_SOLAR.items():
        holidays.append({"date": f"{year}-{m:02d}-{d:02d}", "label": label})

    if LunarDate is None:
        # Thiếu thư viện là thiếu trọn 6 ngày lễ âm lịch. Không có bảng cứng dự
        # phòng: bảng cũ chỉ có năm 2026, ghi sai ngày Giỗ Tổ, và không bao giờ
        # chạy khi thư viện có mặt mà đổi API (issue #109) — lưới giả tệ hơn không lưới.
        _log.error("Thiếu thư viện lunardate — năm %d không có ngày lễ âm lịch", year)
        return holidays

    for (lm, ld), label in _LUNAR_HOLIDAYS.items():
        try:
            solar = _doi_am_duong(LunarDate(year, lm, ld))
            holidays.append({"date": solar.strftime("%Y-%m-%d"), "label": label})
        except Exception:
            # Đổi âm→dương hỏng là MẤT HẲN một ngày lễ khỏi danh sách gợi ý —
            # im lặng thì người phân lịch trực không biết vì sao thiếu.
            _log.warning("Không đổi được ngày lễ âm lịch %s (%d/%d) năm %d",
                         label, ld, lm, year, exc_info=True)
    return holidays


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def is_friday(date_str: str) -> bool:
    return date.fromisoformat(date_str).weekday() == 4


def get_week_dates(start_date: str) -> List[str]:
    """Trả 5 ngày Mon-Fri của tuần chứa start_date.

    Đây là các ngày làm việc *cố định*. Thứ 7 / chủ nhật chỉ đi làm khi được khai
    "Ngày bù" nên không nằm ở đây — muốn quét cả tuần thì dùng week_span()."""
    d = date.fromisoformat(start_date)
    d = d - timedelta(days=d.weekday())
    return [(d + timedelta(days=i)).isoformat() for i in range(5)]


def week_span(start_date: str) -> tuple:
    """Trả (thứ 2, chủ nhật) của tuần chứa start_date.

    Dùng cho các truy vấn "theo tuần" (xem / xác nhận / xoá). Quét theo khoảng
    thay vì theo danh sách ngày làm việc để ca thứ 7 / chủ nhật đã sinh vẫn luôn
    tìm thấy, kể cả khi bản ghi "Ngày bù" của hôm đó bị xoá sau này — nếu không
    ca ấy thành ca mồ côi: nằm trong DB mà màn hình không thấy, không xoá được."""
    d = date.fromisoformat(start_date)
    t2 = d - timedelta(days=d.weekday())
    return t2.isoformat(), (t2 + timedelta(days=6)).isoformat()


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


def compute_cutoff_dates(month: int, year: int, holiday_dates: set,
                         makeup_dates: set = None) -> List[str]:
    """Tính 2 ngày làm việc cuối tháng (cut-off).

    `makeup_dates` là các ngày cuối tuần đã khai đi làm bù — chúng cũng là ngày
    làm việc, nên nếu bỏ qua thì cut-off bị đẩy lùi lên nhầm ngày."""
    makeup_dates = makeup_dates or set()
    last_day = calendar.monthrange(year, month)[1]
    found = []
    for day in range(last_day, 0, -1):
        ds = date(year, month, day).isoformat()
        d = date.fromisoformat(ds)
        la_ngay_lam = not is_weekend(d) or ds in makeup_dates
        if la_ngay_lam and ds not in holiday_dates:
            found.append(ds)
        if len(found) == 2:
            break
    return list(reversed(found))


def week_start_of_date(date_str: str) -> str:
    d = date.fromisoformat(date_str)
    return (d - timedelta(days=d.weekday())).isoformat()
