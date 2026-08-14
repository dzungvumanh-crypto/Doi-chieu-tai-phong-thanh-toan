"""
Test sửa NGÀY trên bảng "Tra cứu lưu trữ" (PATCH /api/bundles/storage-view).

Ngày của một tập được suy ra từ `bundles.cover_units` (JSON), fallback qua
`bundle_items → document_entries.transaction_date`. Sửa ngày vì vậy phải ghi vào
cover_units và **không** được đụng tới document_entries — đó là số liệu bàn giao
gốc của phòng nghiệp vụ, dùng chung cho báo cáo và các tập khác.
"""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.main import app

_SCHEMA = """
CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT, is_source INTEGER DEFAULT 1);
CREATE TABLE bundle_groups (id INTEGER PRIMARY KEY, department_id INTEGER,
                            total_bundles INTEGER DEFAULT 1, created_at TEXT, notes TEXT);
CREATE TABLE bundles (id INTEGER PRIMARY KEY, group_id INTEGER, sequence INTEGER,
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
    return {"id": 1, "role": StaffRole.ADMIN, "username": "t", "full_name": "T"}


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)   # TestClient chạy route ở thread khác
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO departments (id, name) VALUES (1, 'Phòng Thanh toán')")
    conn.execute(
        "INSERT INTO bundle_groups (id, department_id, total_bundles, created_at, notes) "
        "VALUES (1, 1, 0, '2026-02-01', 'Tháng 02/2026')"
    )
    conn.execute("INSERT INTO user_tttt (id, ipcas_code, full_name) VALUES (9, 'AB01', 'Nguyễn A')")
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def client(db):
    # Rollback khi lỗi giống hệt get_db thật — nếu không, dữ liệu chưa commit vẫn
    # nhìn thấy được trên cùng connection và test "lỗi thì không ghi gì" mất ý nghĩa
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


# ─── Helpers dựng dữ liệu ────────────────────────────────────────────────────

def _unit(day: int, sheets: int, code: str = "AB01") -> dict:
    return {"user_code": code, "full_name": "Nguyễn A", "date": f"2026-02-{day:02d}",
            "sheet_count": sheets, "is_large": False}


def _bundle_cover_units(db, bid: int, seq: int, sheets: int, units: list):
    db.execute(
        "INSERT INTO bundles (id, group_id, sequence, total_sheets, status, cover_units) "
        "VALUES (?, 1, ?, ?, 'pending', ?)",
        (bid, seq, sheets, json.dumps(units, ensure_ascii=False)),
    )
    db.commit()


def _bundle_qua_items(db, bid: int, seq: int, days: list, sheets: int):
    """Tập kiểu cũ: không có cover_units, ngày suy ra từ document_entries."""
    db.execute(
        "INSERT INTO bundles (id, group_id, sequence, total_sheets, status) "
        "VALUES (?, 1, ?, ?, 'pending')", (bid, seq, sheets),
    )
    for i, d in enumerate(days):
        eid = bid * 100 + i
        db.execute(
            "INSERT INTO document_entries (id, transaction_date, sheet_count, staff_id) "
            "VALUES (?, ?, ?, 9)", (eid, f"2026-02-{d:02d}", sheets),
        )
        db.execute("INSERT INTO bundle_items (bundle_id, entry_id) VALUES (?, ?)", (bid, eid))
    db.commit()


def _view(client) -> dict:
    r = client.get(_URL, params={"department_id": 1, "year": 2026, "month": 2})
    assert r.status_code == 200, r.text
    return r.json()


def _days_of(db, bid: int) -> list:
    row = db.execute("SELECT cover_units FROM bundles WHERE id = ?", (bid,)).fetchone()
    return sorted({int(u["date"][-2:]) for u in json.loads(row["cover_units"])})


# ─── Sửa ngày ────────────────────────────────────────────────────────────────

def test_doi_ngay_ghi_vao_cover_units_giu_nguyen_so_chung_tu(client, db):
    _bundle_cover_units(db, 10, 1, 25, [_unit(5, 25)])

    r = client.patch(_URL, json={"rows": [
        {"bundle_ids": [10], "bundle_sheets": [25], "days": [7]}
    ]})
    assert r.status_code == 200, r.text

    data = _view(client)
    assert data["rows"][0]["days"] == [7]
    assert data["rows"][0]["bundle_sheets"] == [25]
    assert data["total_sheets"] == 25


def test_doi_ngay_tap_khong_co_cover_units_khong_dung_document_entries(client, db):
    _bundle_qua_items(db, 11, 1, [5], 30)

    r = client.patch(_URL, json={"rows": [
        {"bundle_ids": [11], "bundle_sheets": [30], "days": [9]}
    ]})
    assert r.status_code == 200, r.text

    assert _view(client)["rows"][0]["days"] == [9]
    assert _days_of(db, 11) == [9]
    # Số liệu bàn giao gốc phải nguyên vẹn
    kept = [r["transaction_date"] for r in
            db.execute("SELECT transaction_date FROM document_entries").fetchall()]
    assert kept == ["2026-02-05"]


def test_them_ngay_vao_dong_mot_ngay(client, db):
    _bundle_cover_units(db, 12, 1, 40, [_unit(3, 40)])

    r = client.patch(_URL, json={"rows": [
        {"bundle_ids": [12], "bundle_sheets": [40], "days": [3, 4]}
    ]})
    assert r.status_code == 200, r.text

    assert _view(client)["rows"][0]["days"] == [3, 4]
    # Ngày thêm vào chưa có chứng từ nào → unit rỗng, tổng số tờ không đổi
    units = json.loads(db.execute("SELECT cover_units FROM bundles WHERE id = 12").fetchone()[0])
    assert sum(u["sheet_count"] for u in units) == 40


def test_gop_nhieu_ngay_ve_mot_ngay_khong_mat_so_to(client, db):
    _bundle_cover_units(db, 13, 1, 50, [_unit(3, 20), _unit(4, 30)])

    r = client.patch(_URL, json={"rows": [
        {"bundle_ids": [13], "bundle_sheets": [50], "days": [10]}
    ]})
    assert r.status_code == 200, r.text

    assert _days_of(db, 13) == [10]
    units = json.loads(db.execute("SELECT cover_units FROM bundles WHERE id = 13").fetchone()[0])
    assert sum(u["sheet_count"] for u in units) == 50


def test_dong_nhieu_tap_doi_ngay_thi_moi_tap_deu_doi(client, db):
    _bundle_cover_units(db, 14, 1, 10, [_unit(6, 10)])
    _bundle_cover_units(db, 15, 2, 20, [_unit(6, 20)])

    r = client.patch(_URL, json={"rows": [
        {"bundle_ids": [14, 15], "bundle_sheets": [10, 20], "days": [8]}
    ]})
    assert r.status_code == 200, r.text

    assert _days_of(db, 14) == [8] and _days_of(db, 15) == [8]
    row = _view(client)["rows"][0]
    assert row["days"] == [8] and row["n_bundles"] == 2


def test_tap_moi_nhan_ngay_vua_sua_trong_cung_lan_luu(client, db):
    _bundle_cover_units(db, 16, 1, 10, [_unit(2, 10)])

    r = client.patch(_URL, json={"rows": [
        {"bundle_ids": [16], "bundle_sheets": [10], "new_sheets": [15], "days": [12]}
    ]})
    assert r.status_code == 200, r.text

    row = _view(client)["rows"][0]
    assert row["days"] == [12]
    assert sorted(row["bundle_sheets"]) == [10, 15]


def test_xoa_tap_va_doi_ngay_cung_luc(client, db):
    _bundle_cover_units(db, 17, 1, 10, [_unit(2, 10)])
    _bundle_cover_units(db, 18, 2, 20, [_unit(2, 20)])

    r = client.patch(_URL, json={"rows": [
        {"bundle_ids": [17, 18], "bundle_sheets": [0, 20], "days": [14]}
    ]})
    assert r.status_code == 200, r.text

    assert db.execute("SELECT COUNT(*) FROM bundles").fetchone()[0] == 1
    assert _days_of(db, 18) == [14]


def test_khong_gui_days_thi_ngay_khong_doi(client, db):
    """Client cũ / chỉ sửa số chứng từ — ngày phải nguyên vẹn."""
    _bundle_cover_units(db, 19, 1, 10, [_unit(5, 10)])

    r = client.patch(_URL, json={"rows": [{"bundle_ids": [19], "bundle_sheets": [33]}]})
    assert r.status_code == 200, r.text

    row = _view(client)["rows"][0]
    assert row["days"] == [5] and row["bundle_sheets"] == [33]


# ─── Ngày không hợp lệ ───────────────────────────────────────────────────────

def test_xoa_het_ngay_thi_bao_loi_khong_lam_mat_tap(client, db):
    _bundle_cover_units(db, 20, 1, 10, [_unit(5, 10)])

    r = client.patch(_URL, json={"rows": [
        {"bundle_ids": [20], "bundle_sheets": [10], "days": []}
    ]})
    assert r.status_code == 400
    assert "ít nhất một ngày" in r.json()["detail"]
    assert _days_of(db, 20) == [5]


def test_ngay_khong_co_trong_thang_thi_bao_loi(client, db):
    _bundle_cover_units(db, 21, 1, 10, [_unit(5, 10)])

    r = client.patch(_URL, json={"rows": [
        {"bundle_ids": [21], "bundle_sheets": [10], "days": [30]}   # 2026-02 chỉ có 28 ngày
    ]})
    assert r.status_code == 400
    assert "30" in r.json()["detail"]
    assert _days_of(db, 21) == [5]


def test_loi_o_dong_sau_khong_luu_dong_dau(client, db):
    """Một lần lưu là một giao dịch — sai một dòng thì không dòng nào được ghi."""
    _bundle_cover_units(db, 22, 1, 10, [_unit(5, 10)])
    _bundle_cover_units(db, 23, 1, 20, [_unit(6, 20)])

    r = client.patch(_URL, json={"rows": [
        {"bundle_ids": [22], "bundle_sheets": [10], "days": [7]},
        {"bundle_ids": [23], "bundle_sheets": [20], "days": [99]},
    ]})
    assert r.status_code == 400
    assert _days_of(db, 22) == [5]


def test_nhom_tap_khong_ro_thang_thi_bao_loi(client, db):
    db.execute("UPDATE bundle_groups SET notes = NULL WHERE id = 1")
    _bundle_cover_units(db, 24, 1, 10, [_unit(5, 10)])

    r = client.patch(_URL, json={"rows": [
        {"bundle_ids": [24], "bundle_sheets": [10], "days": [7]}
    ]})
    assert r.status_code == 400
    assert "tháng" in r.json()["detail"].lower()
