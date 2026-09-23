"""Trang Nghỉ phép cất TÊN tab (chuỗi) vào app.storage.user, không cất đối tượng Tab.

Chưa bấm tab nào thì `leave_tabs.value` là đối tượng Tab gán lúc dựng trang. Cất nguyên
đối tượng đó: lưu phiên xuống đĩa lỗi "Tab is not JSON serializable" (có trong
logs/frontend.log), và sau khi duyệt/huỷ đơn trang mới không khớp tab nào → bật về
Dashboard thay vì ở lại tab đang đứng (rà soát 23/09/2026).
"""
import re
from pathlib import Path

from nicegui.props import Props

from frontend.pages.leaves._chung import _ten_tab


class _TabGia:
    """Đủ giống ui.tab cho _ten_tab(): `props` là Props (lớp con của dict) có 'name'."""

    def __init__(self, name: str):
        self.props = Props({"name": name}, element=self)


def test_doi_tab_ra_ten():
    assert _ten_tab(_TabGia("pending")) == "pending"


def test_chuoi_va_none_giu_nguyen():
    assert _ten_tab("pending") == "pending"
    assert _ten_tab(None) is None


def _ma_goi_nghi_phep() -> str:
    goi = Path(__file__).resolve().parents[1] / "frontend" / "pages" / "leaves"
    return "\n".join(f.read_text(encoding="utf-8") for f in sorted(goi.glob("*.py")))


def test_moi_cho_cat_tab_deu_qua_ten_tab():
    ma = _ma_goi_nghi_phep()
    cho_ghi = re.findall(r'\["_leaves_goto_raw"\]\s*=\s*(.+)', ma)
    assert cho_ghi, "không thấy chỗ ghi _leaves_goto_raw — test đã lỗi thời?"
    for ve_phai in cho_ghi:
        assert ve_phai.strip().startswith("_ten_tab("), ve_phai


def test_tab_panels_nhan_ten_tab():
    """tab_panels gắn hai chiều với leave_tabs — giá trị đầu vào thành luôn leave_tabs.value."""
    assert "ui.tab_panels(leave_tabs, value=_ten_tab(" in _ma_goi_nghi_phep()
