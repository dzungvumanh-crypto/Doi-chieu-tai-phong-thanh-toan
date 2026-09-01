"""
Test nhập dữ liệu cho THÁNG CHƯA CÓ TẬP NÀO trên bảng "Tra cứu lưu trữ".

Các tháng đầu năm chưa triển khai chương trình nên không có tập nào. Bảng vẫn phải
hiện ô trống để nhập, và PATCH /api/bundles/storage-view phải tạo được nhóm tập
(bundle_groups) cho tháng đó — dòng mới không có bundle_ids nào để suy ra nhóm.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.main import app

_SCHEMA = """
CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT, is_source INTEGER DEFAULT 1);
CREATE TABLE bundle_groups (id INTEGER PRIMARY KEY AUTOINCREMENT, department_id INTEGER,
                            total_bundles INTEGER DEFAULT 1, created_by_id INTEGER,
                            created_at TEXT, notes TEXT);
CREATE TABLE bundles (id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER, sequence INTEGER,
                      total_sheets INTEGER, custodian_id INTEGER, storage_box TEXT,
                      storage_location TEXT, cover_printed_at TEXT, status TEXT,
                      cover_units TEXT);
CREATE TABLE bundle_items (id INTEGER PRIMARY KEY, bundle_id INTEGER, entry_id INTEGER);
CREATE TABLE document_entries (id INTEGER PRIMARY KEY, transaction_date TEXT,
                               sheet_count INTEGER, notes TEXT, staff_id INTEGER);
CREATE TABLE user_tttt (id INTEGER PRIMARY KEY, ipcas_code TEXT, full_name TEXT);
"""

_URL = "/api/bundles/storage-view"


def _fake_admin() -> dict:
    return {"id": 7, "role": StaffRole.ADMIN, "username": "t", "full_name": "T"}


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)   # TestClient chạy route ở thread khác
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO departments (id, name) VALUES (1, 'Phòng Thanh toán')")
    conn.execute("INSERT INTO user_tttt (id, ipcas_code, full_name) VALUES (7, 'AB07', 'Nguyễn B')")
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def client(db):
    def _get_db():
        try:
            yield db
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_current_staff] = _fake_admin
    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _patch(client, rows, dept=1, year=2026, month=3):
    body = {"rows": rows}
    if dept is not None:
        body["department_id"] = dept
    if year is not None:
        body["year"] = year
    if month is not None:
        body["month"] = month
    return client.patch(_URL, json=body)


def _new_row(days, sheets):
    """Dòng trống người dùng vừa gõ: chưa gắn với tập nào."""
    return {"bundle_ids": [], "bundle_sheets": [], "new_sheets": sheets, "days": days}


def _view(client, month=3) -> dict:
    r = client.get(_URL, params={"department_id": 1, "year": 2026, "month": month})
    assert r.status_code == 200, r.text
    return r.json()


def _groups(db) -> list:
    return db.execute(
        "SELECT id, notes, total_bundles, created_by_id FROM bundle_groups"
    ).fetchall()


# ─── Tháng trống: nhập mới ───────────────────────────────────────────────────

def test_thang_trong_van_tra_ve_ten_phong_va_ky(client, db):
    """Frontend cần department_name/period để vẽ đầu bảng dù chưa có dòng nào."""
    data = _view(client)
    assert data["department_name"] == "Phòng Thanh toán"
    assert data["period"] == "Tháng 03/2026"
    assert data["rows"] == []


def test_thang_trong_nhap_duoc_dong_dau_tien(client, db):
    r = _patch(client, [_new_row([3], [25])])
    assert r.status_code == 200, r.text

    groups = _groups(db)
    assert len(groups) == 1
    assert groups[0]["notes"] == "Tháng 03/2026"
    assert groups[0]["total_bundles"] == 1
    assert groups[0]["created_by_id"] == 7          # người đang đăng nhập tạo nhóm

    row = _view(client)["rows"][0]
    assert row["days"] == [3] and row["bundle_sheets"] == [25] and row["n_bundles"] == 1


def test_nhieu_dong_moi_mot_lan_luu_chi_tao_mot_nhom(client, db):
    r = _patch(client, [_new_row([3], [25]), _new_row([4], [10, 20])])
    assert r.status_code == 200, r.text

    assert len(_groups(db)) == 1
    assert _groups(db)[0]["total_bundles"] == 3

    data = _view(client)
    assert [x["days"] for x in data["rows"]] == [[3], [4]]
    assert data["total_sheets"] == 55


def test_dong_moi_nhieu_ngay(client, db):
    r = _patch(client, [_new_row([5, 6], [40])])
    assert r.status_code == 200, r.text

    row = _view(client)["rows"][0]
    assert row["days"] == [5, 6] and row["bundle_sheets"] == [40]


def test_thang_da_co_du_lieu_thi_dung_lai_nhom_cu(client, db):
    db.execute(
        "INSERT INTO bundle_groups (id, department_id, total_bundles, created_by_id, created_at, notes) "
        "VALUES (1, 1, 1, 7, '2026-03-01', 'Tháng 03/2026')"
    )
    db.execute(
        "INSERT INTO bundles (id, group_id, sequence, total_sheets, status, cover_units) "
        "VALUES (1, 1, 1, 10, 'pending', ?)",
        ('[{"user_code": "", "full_name": "", "date": "2026-03-02", '
         '"sheet_count": 10, "is_large": false}]',),
    )
    db.commit()

    r = _patch(client, [_new_row([9], [30])])
    assert r.status_code == 200, r.text

    assert len(_groups(db)) == 1                    # không đẻ thêm nhóm trùng tháng
    assert _groups(db)[0]["total_bundles"] == 2
    assert [x["days"] for x in _view(client)["rows"]] == [[2], [9]]


# ─── Dòng trống / thiếu dữ liệu ──────────────────────────────────────────────

def test_dong_de_trong_hoan_toan_thi_bo_qua(client, db):
    r = _patch(client, [_new_row([], [])])
    assert r.status_code == 200, r.text
    assert _groups(db) == []
    assert db.execute("SELECT COUNT(*) FROM bundles").fetchone()[0] == 0


def test_go_ngay_ma_quen_so_chung_tu_thi_bao_loi(client, db):
    r = _patch(client, [_new_row([3], [])])
    assert r.status_code == 400
    assert "số chứng từ" in r.json()["detail"]
    assert _groups(db) == []                        # lỗi thì không để lại nhóm rỗng


def test_go_so_chung_tu_ma_quen_ngay_thi_bao_loi(client, db):
    r = _patch(client, [_new_row([], [25])])
    assert r.status_code == 400
    assert "ngày" in r.json()["detail"]
    assert _groups(db) == []


def test_ngay_khong_co_trong_thang_thi_bao_loi(client, db):
    r = _patch(client, [_new_row([31], [25])], month=4)   # tháng 4 chỉ có 30 ngày
    assert r.status_code == 400
    assert "31" in r.json()["detail"]
    assert _groups(db) == []


def test_thieu_thang_thi_bao_loi(client, db):
    r = _patch(client, [_new_row([3], [25])], month=None)
    assert r.status_code == 400
    assert _groups(db) == []


def test_thang_khong_hop_le_thi_bao_loi(client, db):
    r = _patch(client, [_new_row([3], [25])], month=13)
    assert r.status_code == 400
    assert _groups(db) == []


def test_phong_khong_ton_tai_thi_404(client, db):
    r = _patch(client, [_new_row([3], [25])], dept=999)
    assert r.status_code == 404
    assert _groups(db) == []


def test_loi_o_dong_sau_khong_ghi_dong_truoc(client, db):
    """Một lần lưu là một giao dịch — dòng sau sai thì dòng đầu cũng không được ghi."""
    r = _patch(client, [_new_row([3], [25]), _new_row([99], [10])])
    assert r.status_code == 400
    assert _groups(db) == []
    assert db.execute("SELECT COUNT(*) FROM bundles").fetchone()[0] == 0


# ─── Nhiều tập cho một dòng nhiều ngày ───────────────────────────────────────

def test_hai_tap_cho_dong_nhieu_ngay_van_la_MOT_dong(client, db):
    """Gõ ngày "1 2" + số chứng từ "12 34" phải ra một dòng hai tập, không tách đôi."""
    r = _patch(client, [_new_row([1, 2], [12, 34])])
    assert r.status_code == 200, r.text

    rows = _view(client)["rows"]
    assert len(rows) == 1
    assert rows[0]["days"] == [1, 2]
    assert rows[0]["bundle_sheets"] == [12, 34]
    assert rows[0]["n_bundles"] == 2


def test_them_tap_thu_ba_vao_dong_nhieu_ngay(client, db):
    _patch(client, [_new_row([1, 2], [12, 34])])
    bids = _view(client)["rows"][0]["bundle_ids"]

    r = _patch(client, [{"bundle_ids": bids, "bundle_sheets": [12, 34],
                         "new_sheets": [34], "days": [1, 2]}])
    assert r.status_code == 200, r.text

    rows = _view(client)["rows"]
    assert len(rows) == 1                          # vẫn một dòng, không đẻ dòng mới
    assert rows[0]["n_bundles"] == 3
    assert sorted(rows[0]["bundle_sheets"]) == [12, 34, 34]
    assert _view(client)["total_sheets"] == 80


def test_dong_khac_tap_hop_ngay_thi_tach_rieng(client, db):
    r = _patch(client, [_new_row([1, 2], [12]), _new_row([1], [50]), _new_row([2, 3], [7])])
    assert r.status_code == 200, r.text

    rows = _view(client)["rows"]
    # Cùng ngày đầu thì dòng ít ngày lên trước
    assert [x["days"] for x in rows] == [[1], [1, 2], [2, 3]]
    assert [x["n_bundles"] for x in rows] == [1, 1, 1]


def test_nhan_bia_danh_so_cho_tap_nhieu_ngay(client, db):
    """Hai tập cùng hồ sơ "ngày 01, 02" phải ra bìa 1/2 và 2/2, không phải 1/1 cả hai."""
    from backend.api.bundles import _get_bundle_label

    units = ('[{"user_code": "", "full_name": "", "date": "2026-03-01", "sheet_count": %d, '
             '"is_large": false}, {"user_code": "", "full_name": "", "date": "2026-03-02", '
             '"sheet_count": 0, "is_large": false}]')
    all_bundles = [
        {"id": 1, "sequence": 1, "total_sheets": 12, "cover_units": units % 12},
        {"id": 2, "sequence": 2, "total_sheets": 34, "cover_units": units % 34},
    ]
    assert _get_bundle_label(all_bundles[0], all_bundles) == (1, 2)
    assert _get_bundle_label(all_bundles[1], all_bundles) == (2, 2)


def test_nhan_bia_tap_khac_ngay_van_la_mot_tren_mot(client, db):
    from backend.api.bundles import _get_bundle_label

    one = ('[{"user_code": "", "full_name": "", "date": "2026-03-%02d", '
           '"sheet_count": 10, "is_large": false}]')
    all_bundles = [
        {"id": 1, "sequence": 1, "total_sheets": 10, "cover_units": one % 1},
        {"id": 2, "sequence": 2, "total_sheets": 10, "cover_units": one % 2},
    ]
    assert _get_bundle_label(all_bundles[0], all_bundles) == (1, 1)
    assert _get_bundle_label(all_bundles[1], all_bundles) == (1, 1)
