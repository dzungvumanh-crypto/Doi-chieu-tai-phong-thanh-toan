"""P2 (23/09/2026): Dashboard Nghỉ phép tải đơn từ đầu năm trước, tìm lùi xa hơn thì tự tải đủ.

Canh chỗ dễ hỏng âm thầm: lọc ngày chạm quá mốc mà KHÔNG tải thêm → 0 kết quả, không ai biết.
"""
from datetime import date
from pathlib import Path

from frontend.pages.leaves._chung import _loc_lui_qua_moc as lui


def test_khong_loc_ngay_thi_khong_tai_them():
    assert lui(2025, None, None, None) is False


def test_khoang_ngay_trong_pham_vi():
    assert lui(2025, date(2025, 3, 1), date(2025, 3, 31), None) is False


def test_tu_ngay_truoc_moc():
    assert lui(2025, date(2024, 12, 31), None, None) is True


def test_chi_co_den_ngay_la_mo_ve_qua_khu():
    assert lui(2025, None, date(2026, 1, 31), None) is True


def test_ngay_tao_truoc_moc():
    assert lui(2025, None, None, date(2023, 6, 1)) is True
    assert lui(2025, None, None, date(2025, 6, 1)) is False


def test_da_tai_toan_bo_thi_khong_bao_gio_tai_them():
    assert lui(None, date(2010, 1, 1), None, date(2010, 1, 1)) is False


def _ma_trang() -> str:
    goi = Path(__file__).resolve().parents[1] / "frontend" / "pages" / "leaves"
    return "\n".join(f.read_text(encoding="utf-8") for f in sorted(goi.glob("*.py")))


def test_trang_noi_day_dung():
    ma = _ma_trang()
    # Tải ban đầu có giới hạn năm
    assert '{"scope": "all", "tu_nam": _pham_vi_all["tu_nam"]}' in ma
    # Nút Tìm kiếm + Enter đi qua _tim_kiem (có bước tải thêm), không gọi thẳng _apply_filter
    assert "on_click=lambda: _tim_kiem()" in ma
    assert 'on("keydown.enter", lambda _: _apply_filter())' not in ma
