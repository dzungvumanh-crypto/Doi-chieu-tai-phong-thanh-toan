"""
Test phân quyền 35 endpoint duty_*.

Trước đây mọi endpoint chỉ dùng Depends(get_current_staff): bất kỳ ai đăng nhập
đều gọi thẳng được DELETE /api/duty/schedule/week để xoá cả tuần lịch đã xác nhận.
Frontend chỉ ẩn nút — không phải rào chắn.

Hai lớp test:
  CẤU TRÚC — mọi route dưới /api/duty phải gắn require_feature, và đúng mã đã
             thống nhất. Bắt được cả trường hợp thêm endpoint mới mà quên gắn.
  HÀNH VI  — người không có quyền thật sự nhận 403, admin thì đi qua.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.database import get_db
from backend.main import app

# Đường dẫn (không kèm prefix) -> mã tính năng bắt buộc
MONG_DOI = {
    ("GET",    "/api/duty/schedule/month"):                    "menu.duty_schedule",
    ("GET",    "/api/duty/schedule/week"):                     "menu.duty_schedule",
    ("GET",    "/api/duty/schedule/date/{date_str}"):          "menu.duty_schedule",
    ("GET",    "/api/duty/schedule/{shift_id}"):               "menu.duty_schedule",
    ("POST",   "/api/duty/schedule/generate-week"):            "duty.generate",
    ("POST",   "/api/duty/schedule/generate-month"):           "duty.generate",
    ("PUT",    "/api/duty/schedule/{shift_id}"):               "duty.generate",
    ("POST",   "/api/duty/schedule/{shift_id}/confirm"):       "duty.confirm",
    ("POST",   "/api/duty/schedule/{shift_id}/unconfirm"):     "duty.confirm",
    ("POST",   "/api/duty/schedule/confirm-week"):             "duty.confirm",
    ("DELETE", "/api/duty/schedule/week"):                     "duty.delete",
    ("DELETE", "/api/duty/schedule/{shift_id}"):               "duty.delete",
    ("POST",   "/api/duty/schedule/rotation/reset"):           "duty.manage_config",

    ("GET",    "/api/duty/staff"):                             "menu.duty_schedule",
    ("POST",   "/api/duty/staff/{user_id}/meta"):              "duty.manage_staff",

    ("GET",    "/api/duty/constraints/absences"):              "menu.duty_schedule",
    ("POST",   "/api/duty/constraints/absences"):              "duty.manage_staff",
    ("POST",   "/api/duty/constraints/absences/range"):        "duty.manage_staff",
    ("DELETE", "/api/duty/constraints/absences/range"):        "duty.manage_staff",
    ("DELETE", "/api/duty/constraints/absences/{absence_id}"): "duty.manage_staff",
    ("GET",    "/api/duty/constraints/requests"):              "menu.duty_schedule",
    ("POST",   "/api/duty/constraints/requests"):              "duty.manage_staff",
    ("DELETE", "/api/duty/constraints/requests/{request_id}"): "duty.manage_staff",
    ("GET",    "/api/duty/constraints/special-days"):          "menu.duty_schedule",
    ("POST",   "/api/duty/constraints/special-days"):          "duty.manage_config",
    ("POST",   "/api/duty/constraints/special-days/{special_day_id}/confirm"): "duty.manage_config",
    ("DELETE", "/api/duty/constraints/special-days/{special_day_id}"):         "duty.manage_config",
    ("POST",   "/api/duty/constraints/special-days/compute-cutoff"):           "duty.manage_config",
    ("POST",   "/api/duty/constraints/special-days/seed-holidays"):            "duty.manage_config",
    ("GET",    "/api/duty/constraints/shift-config/{year}"):   "menu.duty_schedule",
    ("PUT",    "/api/duty/constraints/shift-config/{year}"):   "duty.manage_config",

    ("GET",    "/api/duty/stats/shift-count"):                 "menu.duty_schedule",
    ("GET",    "/api/duty/stats/monthly-summary"):             "menu.duty_schedule",
    ("GET",    "/api/duty/stats/rotation-state"):              "menu.duty_schedule",

    ("GET",    "/api/duty/export/week"):                       "duty.export",
}


def _ma_tinh_nang(ham) -> str:
    """Moi require_feature() sinh ra một closure giữ feature_code trong cell."""
    for cell in (ham.__closure__ or ()):
        try:
            v = cell.cell_contents
        except ValueError:
            continue
        if isinstance(v, str) and (v.startswith("duty.") or v.startswith("menu.duty")):
            return v
    return None


def _route_duty():
    """(method, path, mã tính năng đang gắn) cho mọi route dưới /api/duty."""
    ra = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if not path.startswith("/api/duty"):
            continue
        ma = next((m for d in r.dependant.dependencies
                   if (m := _ma_tinh_nang(d.call))), None)
        for method in (r.methods or set()) - {"HEAD", "OPTIONS"}:
            ra.append((method, path, ma))
    return ra


# ══════════════════════════════════════════════════════════════
# CẤU TRÚC
# ══════════════════════════════════════════════════════════════

def test_moi_endpoint_duty_deu_enforce_require_feature():
    thieu = [(m, p) for m, p, ma in _route_duty() if ma is None]
    assert not thieu, f"Endpoint chưa gắn require_feature: {thieu}"


def test_dung_ma_tinh_nang_da_thong_nhat():
    sai = {(m, p): ma for m, p, ma in _route_duty()
           if MONG_DOI.get((m, p)) not in (None, ma)}
    assert not sai, f"Gắn sai mã tính năng: {sai}"


def test_bang_mong_doi_khong_bo_sot_endpoint_nao():
    """Thêm endpoint mới mà quên khai vào bảng trên thì test này gãy."""
    thuc_te = {(m, p) for m, p, _ in _route_duty()}
    assert thuc_te == set(MONG_DOI), (
        f"Thừa: {thuc_te - set(MONG_DOI)} · Thiếu: {set(MONG_DOI) - thuc_te}")


def test_xoa_tuan_lich_khong_con_de_ai_cung_goi_duoc():
    """Chốt riêng endpoint nguy hiểm nhất — xoá cả tuần, kể cả ca đã xác nhận."""
    ma = next(ma for m, p, ma in _route_duty()
              if (m, p) == ("DELETE", "/api/duty/schedule/week"))
    assert ma == "duty.delete"


# ══════════════════════════════════════════════════════════════
# HÀNH VI
# ══════════════════════════════════════════════════════════════

_SCHEMA_NHOM = """
CREATE TABLE user_groups   (id INTEGER PRIMARY KEY, name TEXT, is_active INTEGER DEFAULT 1);
CREATE TABLE group_members (group_id INTEGER, staff_id INTEGER);
CREATE TABLE group_features(group_id INTEGER, feature_code TEXT);
"""


@pytest.fixture
def client_va_db():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(_SCHEMA_NHOM)
    db.execute("INSERT INTO user_groups (id, name) VALUES (1, 'Trực ban')")
    db.execute("INSERT INTO group_members (group_id, staff_id) VALUES (1, 7)")
    db.commit()

    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app), db
    app.dependency_overrides.clear()
    db.close()


def _dang_nhap(role="chuyen_vien", staff_id=7):
    app.dependency_overrides[get_current_staff] = lambda: {
        "id": staff_id, "role": role, "username": "u", "full_name": "Người dùng"}


def test_khong_co_quyen_thi_xoa_tuan_bi_chan_403(client_va_db):
    client, _ = client_va_db
    _dang_nhap()
    r = client.delete("/api/duty/schedule/week?week_start=2026-08-10")
    assert r.status_code == 403


def test_co_quyen_khac_van_khong_xoa_duoc(client_va_db):
    """Có duty.confirm không có nghĩa là được xoá."""
    client, db = client_va_db
    db.execute("INSERT INTO group_features (group_id, feature_code) VALUES (1, 'duty.confirm')")
    db.commit()
    _dang_nhap()
    assert client.delete("/api/duty/schedule/week?week_start=2026-08-10").status_code == 403


def test_duoc_cap_dung_quyen_thi_qua_duoc_cua(client_va_db):
    client, db = client_va_db
    db.execute("INSERT INTO group_features (group_id, feature_code) VALUES (1, 'duty.delete')")
    db.commit()
    _dang_nhap()
    # Qua được tầng quyền là đủ. Sau đó request chạm bảng duty_shifts không có
    # trong schema test → app trả 503 (handler sqlite3.OperationalError ở main.py),
    # chính là bằng chứng nó đã đi qua cửa quyền tới tầng nghiệp vụ.
    assert client.delete("/api/duty/schedule/week?week_start=2026-08-10").status_code == 503


def test_admin_di_qua_moi_tinh_nang(client_va_db):
    """Admin bypass toàn bộ require_feature — không cần thuộc nhóm nào."""
    client, _ = client_va_db
    _dang_nhap(role="admin", staff_id=1)
    assert client.delete("/api/duty/schedule/week?week_start=2026-08-10").status_code == 503
