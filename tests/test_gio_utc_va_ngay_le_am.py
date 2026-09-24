"""Issue #113 (bỏ datetime.utcnow) và #109 (lunardate đổi tên toSolarDate)."""
import ast
import logging
import pathlib
import sqlite3
from datetime import date

import pytest

from backend.core import rate_limit
from backend.services import duty_calendar_utils as lich

_GOC = pathlib.Path(__file__).resolve().parent.parent


# ══ #113 — giờ UTC naive ══════════════════════════════════════════════════════

@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE login_rate_limit (
        username TEXT PRIMARY KEY, attempt_count INTEGER DEFAULT 0,
        window_start TEXT, locked_until TEXT)""")
    yield conn
    conn.close()


def test_khoa_tai_khoan_khong_tron_naive_va_co_mui_gio(db):
    # Lần 2 trở đi đi qua `now - ws`; sau khi khoá, seconds_locked đi qua `lu - now`.
    # ws/lu do strptime sinh ra (naive) — now có múi giờ là TypeError ngay đây.
    for _ in range(rate_limit.MAX_FAILURES):
        rate_limit.record_failed(db, "an")
    con_lai = rate_limit.seconds_locked(db, "an")
    assert 0 < con_lai <= rate_limit.LOCKOUT.total_seconds()


def test_ma_du_an_khong_goi_utcnow():
    # Cảnh báo bỏ API chìm giữa hàng nghìn cảnh báo của thư viện — canh bằng mã nguồn,
    # bắt cả nhánh không test nào chạy tới.
    vi_pham = [
        f"{p.relative_to(_GOC)}:{n.lineno}"
        for thu_muc in ("backend", "frontend", "tests")
        for p in (_GOC / thu_muc).rglob("*.py")
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
        if isinstance(n, ast.Attribute) and n.attr == "utcnow"
    ]
    assert vi_pham == []


# ══ #109 — ngày lễ âm lịch ════════════════════════════════════════════════════

def _ngay(ds, nhan):
    return next(h["date"] for h in ds if h["label"] == nhan)


def test_ngay_le_2026_du_va_dung():
    ds = lich.get_vn_holidays(2026)
    assert len(ds) == 4 + 6
    assert _ngay(ds, "Tết Nguyên Đán (mùng 1)") == "2026-02-17"
    assert _ngay(ds, "Tết Nguyên Đán (mùng 5)") == "2026-02-21"
    assert _ngay(ds, "Giỗ Tổ Hùng Vương") == "2026-04-26"


class _AmMoi:
    """Giả lunardate >= 0.4: chỉ còn to_solar_date()."""
    def __init__(self, y, m, d):
        self.y, self.m, self.d = y, m, d

    def to_solar_date(self):
        return date(self.y, 1, 1)


class _AmCu:
    """Giả lunardate 0.2.2 (máy chủ): chỉ có toSolarDate()."""
    def __init__(self, y, m, d):
        self.y = y

    def toSolarDate(self):
        return date(self.y, 1, 1)


@pytest.mark.parametrize("gia", [_AmMoi, _AmCu])
def test_chay_duoc_ca_ten_cu_lan_ten_moi(monkeypatch, gia):
    monkeypatch.setattr(lich, "LunarDate", gia)
    assert len(lich.get_vn_holidays(2027)) == 10


def test_thieu_thu_vien_bao_loi_khong_bia_ngay(monkeypatch, caplog):
    monkeypatch.setattr(lich, "LunarDate", None)
    with caplog.at_level(logging.ERROR, logger=lich.__name__):
        ds = lich.get_vn_holidays(2026)
    assert len(ds) == 4
    assert "lunardate" in caplog.text
