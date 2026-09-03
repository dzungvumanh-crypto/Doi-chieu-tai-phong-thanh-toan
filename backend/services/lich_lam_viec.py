"""Lịch làm việc thực tế — ngày nghỉ lễ và ngày làm bù, hợp từ hai nguồn khai báo.

Hai bảng cùng nói về ngày nghỉ, không bảng nào phủ hết:

- `public_holidays`   — danh mục ngày lễ chung, nhập ở màn hình **Nghỉ phép**.
- `duty_special_days` — khai báo riêng của Sổ trực (**Phân lịch trực → Ngày đặc
  biệt**). Đây là nơi DUY NHẤT trong phần mềm có khái niệm **ngày làm bù**.

Quy tắc hợp: **khai báo riêng của Sổ trực thắng** — ngày nào đã có dòng trong
`duty_special_days` thì lấy nguyên `day_type` của dòng đó, kể cả khi ngày ấy
cũng nằm trong `public_holidays`. Cần thế để giữ được ngày làm bù rơi trúng
ngày lễ (nhà nước hoán đổi ngày nghỉ): hợp thẳng hai tập thì ngày ấy vừa là lễ
vừa là bù, hai màn hình đọc ra hai câu trả lời trái nhau.

Giống hệt `duty_constraint_service.get_holiday_dates()`, chỉ khác là nhận
khoảng ngày thay vì một năm — báo cáo chứng từ tra cứu vắt qua giao thừa.

`cutoff` và `settlement` là ngày làm việc **bình thường** (thậm chí bận hơn),
tuyệt đối không được coi là ngày nghỉ. Chúng chỉ có mặt ở đây với vai trò
"đã khai riêng" — tức là chặn ngày đó nhận nhãn lễ từ `public_holidays`.
"""
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import FrozenSet

# Chỉ hai loại này đổi được ngày làm việc thành ngày nghỉ hoặc ngược lại
NGHI_LE = "holiday"
LAM_BU = "makeup"


@dataclass(frozen=True)
class LichLamViec:
    ngay_le: FrozenSet[date]
    ngay_bu: FrozenSet[date]


#: Lịch trống — không có khai báo lễ/bù nào, ngày làm việc thuần theo thứ.
#: Dùng làm mặc định cho hàm không bắt buộc truyền lịch.
LICH_RONG = LichLamViec(frozenset(), frozenset())


def tai_lich(db: sqlite3.Connection, lo: date, hi: date) -> LichLamViec:
    """Đọc ngày lễ + ngày làm bù trong [lo, hi] từ cả hai nguồn."""
    khai_rieng = {
        date.fromisoformat(r["date"]): (r["day_type"], r["is_confirmed"])
        for r in db.execute(
            "SELECT date, day_type, is_confirmed FROM duty_special_days "
            "WHERE date >= ? AND date <= ?",
            (lo.isoformat(), hi.isoformat()),
        ).fetchall()
    }

    ngay_le = {d for d, (loai, _) in khai_rieng.items() if loai == NGHI_LE}
    for r in db.execute(
        "SELECT date FROM public_holidays WHERE date >= ? AND date <= ?",
        (lo.isoformat(), hi.isoformat()),
    ).fetchall():
        d = date.fromisoformat(r["date"])
        if d not in khai_rieng:
            ngay_le.add(d)

    # Ngày bù phải ĐÃ xác nhận mới tính — cùng điều kiện với get_makeup_dates()
    # bên Sổ trực. Khai xong mà quên bấm xác nhận thì hai màn hình vẫn khớp:
    # cả hai đều coi hôm đó là ngày nghỉ bình thường.
    ngay_bu = {
        d for d, (loai, xac_nhan) in khai_rieng.items()
        if loai == LAM_BU and xac_nhan
    }

    return LichLamViec(frozenset(ngay_le), frozenset(ngay_bu))


def la_ngay_lam_viec(d: date, lich: LichLamViec) -> bool:
    """Ngày lễ thì nghỉ; ngày bù thì đi làm dù rơi vào T7/CN; còn lại theo thứ."""
    if d in lich.ngay_le:
        return False
    if d in lich.ngay_bu:
        return True
    return d.weekday() < 5


def dem_ngay_lam_viec(
    start_exclusive: date,
    end_inclusive: date,
    lich: LichLamViec,
    loai_tru: FrozenSet[date] = frozenset(),
) -> int:
    """Đếm ngày làm việc trong (start, end]. `loai_tru` là ngày nghỉ riêng của một người."""
    count = 0
    d = start_exclusive + timedelta(days=1)
    while d <= end_inclusive:
        if la_ngay_lam_viec(d, lich) and d not in loai_tru:
            count += 1
        d += timedelta(days=1)
    return count
