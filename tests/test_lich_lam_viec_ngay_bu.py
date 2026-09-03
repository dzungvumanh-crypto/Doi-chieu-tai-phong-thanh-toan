"""Ngày làm bù rút ngắn hạn nộp chứng từ; ngày lễ nới ra.

Trước đây `working_days_between` chỉ biết `d.weekday() < 5` + `public_holidays`,
nên thứ Bảy phải đi làm bù vẫn bị coi là ngày nghỉ — chứng từ nộp muộn một ngày
làm việc thật vẫn được tính đúng hạn. Ngày làm bù chỉ được khai ở màn
Phân lịch trực → Ngày đặc biệt (`duty_special_days`), nên báo cáo phải đọc bảng đó.
"""
import sqlite3
from datetime import date

import pytest

from backend.services.lich_lam_viec import (
    dem_ngay_lam_viec, la_ngay_lam_viec, tai_lich,
)

# 2026: 03/01 là thứ Bảy, 05/01 là thứ Hai
T7 = date(2026, 1, 3)
CN = date(2026, 1, 4)
T2 = date(2026, 1, 5)
T6 = date(2026, 1, 2)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE public_holidays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL UNIQUE,
            name TEXT NOT NULL);
        CREATE TABLE duty_special_days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE UNIQUE NOT NULL,
            day_type VARCHAR(20) NOT NULL
                CHECK(day_type IN ('holiday','cutoff','settlement','makeup')),
            label VARCHAR(100),
            is_confirmed BOOLEAN DEFAULT 0,
            created_at DATETIME);
    """)
    yield conn
    conn.close()


def _dat_ngay_dac_biet(db, ngay, loai, xac_nhan=1):
    db.execute(
        "INSERT INTO duty_special_days (date, day_type, is_confirmed) VALUES (?,?,?)",
        (ngay.isoformat(), loai, xac_nhan),
    )


def _lich(db):
    return tai_lich(db, date(2026, 1, 1), date(2026, 1, 31))


# ── Ngày bù ──────────────────────────────────────────────────────────────────

def test_t7_lam_bu_da_xac_nhan_la_ngay_lam_viec(db):
    _dat_ngay_dac_biet(db, T7, "makeup")
    assert la_ngay_lam_viec(T7, _lich(db)) is True


def test_t7_lam_bu_chua_xac_nhan_van_la_ngay_nghi(db):
    """Cùng điều kiện với get_makeup_dates() bên Sổ trực — khai xong phải bấm xác nhận."""
    _dat_ngay_dac_biet(db, T7, "makeup", xac_nhan=0)
    assert la_ngay_lam_viec(T7, _lich(db)) is False


def test_ngay_bu_rut_ngan_han_nop(db):
    """Giao dịch thứ Sáu, nộp thứ Hai: không có ngày bù thì cách 1 ngày làm việc
    (đúng hạn); khai thứ Bảy là ngày bù thì thành 2 (quá hạn 1 ngày)."""
    assert dem_ngay_lam_viec(T6, T2, _lich(db)) == 1
    _dat_ngay_dac_biet(db, T7, "makeup")
    assert dem_ngay_lam_viec(T6, T2, _lich(db)) == 2


# ── Ngày lễ ──────────────────────────────────────────────────────────────────

def test_ngay_le_tu_public_holidays(db):
    db.execute("INSERT INTO public_holidays (date, name) VALUES (?,?)",
               (T2.isoformat(), "Nghỉ bù Tết Dương lịch"))
    assert la_ngay_lam_viec(T2, _lich(db)) is False


def test_ngay_le_khai_rieng_ben_so_truc(db):
    _dat_ngay_dac_biet(db, T2, "holiday", xac_nhan=0)
    assert la_ngay_lam_viec(T2, _lich(db)) is False


def test_khai_rieng_thang_public_holidays(db):
    """Nhà nước hoán đổi: ngày trong danh mục lễ chung nhưng Sổ trực khai là ngày bù.
    Hợp thẳng hai tập thì ngày ấy vừa lễ vừa bù — phải theo khai báo của Sổ trực."""
    db.execute("INSERT INTO public_holidays (date, name) VALUES (?,?)",
               (T7.isoformat(), "Nghỉ lễ"))
    _dat_ngay_dac_biet(db, T7, "makeup")
    lich = _lich(db)
    assert T7 not in lich.ngay_le
    assert la_ngay_lam_viec(T7, lich) is True


# ── Cut-off / quyết toán là ngày làm việc bình thường ────────────────────────

@pytest.mark.parametrize("loai", ["cutoff", "settlement"])
def test_cutoff_va_quyet_toan_khong_phai_ngay_nghi(db, loai):
    _dat_ngay_dac_biet(db, T2, loai)
    assert la_ngay_lam_viec(T2, _lich(db)) is True


@pytest.mark.parametrize("loai", ["cutoff", "settlement"])
def test_cutoff_t7_van_la_ngay_nghi(db, loai):
    """Cut-off không biến thứ Bảy thành ngày làm việc — chỉ 'makeup' làm được thế."""
    _dat_ngay_dac_biet(db, T7, loai)
    assert la_ngay_lam_viec(T7, _lich(db)) is False


def test_cutoff_chan_nhan_le_tu_danh_muc_chung(db):
    """Đã khai riêng thì thắng, kể cả loại không phải lễ/bù."""
    db.execute("INSERT INTO public_holidays (date, name) VALUES (?,?)",
               (T2.isoformat(), "Nghỉ lễ"))
    _dat_ngay_dac_biet(db, T2, "cutoff")
    assert la_ngay_lam_viec(T2, _lich(db)) is True


# ── Khoảng tra cứu vắt qua giao thừa ─────────────────────────────────────────

def test_tai_lich_vat_qua_hai_nam(db):
    _dat_ngay_dac_biet(db, date(2025, 12, 27), "makeup")   # thứ Bảy
    db.execute("INSERT INTO public_holidays (date, name) VALUES (?,?)",
               ("2026-01-01", "Tết Dương lịch"))
    lich = tai_lich(db, date(2025, 12, 1), date(2026, 1, 31))
    assert date(2025, 12, 27) in lich.ngay_bu
    assert date(2026, 1, 1) in lich.ngay_le


# ── Không khai gì thì y như trước ────────────────────────────────────────────

def test_khong_khai_gi_thi_theo_thu(db):
    lich = _lich(db)
    assert la_ngay_lam_viec(T6, lich) is True
    assert la_ngay_lam_viec(T7, lich) is False
    assert la_ngay_lam_viec(CN, lich) is False
