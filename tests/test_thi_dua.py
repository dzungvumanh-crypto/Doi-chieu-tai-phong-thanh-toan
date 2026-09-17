"""Thi đua khen thưởng — CRUD 3 loại, phân quyền, file sáng kiến, tra cứu/thống
kê, nhập lô Excel."""
import io
import sqlite3

import openpyxl
import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.database import get_db
from backend.db.migrations import _create_tables
from backend.main import app

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ── Fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture
def db(tmp_path):
    duong = tmp_path / "thidua.db"
    _create_tables(str(duong))
    conn = sqlite3.connect(duong, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        ALTER TABLE user_tttt ADD COLUMN is_deleted BOOLEAN DEFAULT 0;
        INSERT INTO departments (id, code, name) VALUES
            (1, 'TH', 'Phòng Tổng hợp'),
            (2, 'TT', 'Phòng Thanh toán');
        INSERT INTO user_tttt (id, employee_code, full_name, role, department_id,
                               username, pwd_hash, is_active)
        VALUES (1, 'NS001', 'Nguyễn Văn A', 'chuyen_vien', 1, 'a', 'x', 1),
               (2, 'NS002', 'Trần Thị B',   'chuyen_vien', 2, 'b', 'x', 1);
        INSERT INTO user_groups (id, name, is_active) VALUES (1, 'TD', 1);
        """
    )
    conn.commit()
    yield conn
    conn.close()


def _cap_quyen(db, staff_id: int, *codes: str):
    db.execute("INSERT OR IGNORE INTO group_members (group_id, staff_id) VALUES (1, ?)",
               (staff_id,))
    for c in codes:
        db.execute("INSERT OR IGNORE INTO group_features (group_id, feature_code) VALUES (1, ?)",
                   (c,))
    db.commit()


@pytest.fixture
def client(db):
    """Đăng nhập sẵn là cán bộ id=1 (chuyên viên) — mọi test quyền phải đi qua
    đúng đường phân quyền theo nhóm, không phải admin bypass."""
    app.dependency_overrides[get_current_staff] = lambda: {
        "id": 1, "role": "chuyen_vien", "username": "a", "full_name": "Nguyễn Văn A"}

    def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _xlsx_bytes(headers: list, rows: list) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Danh hiệu đơn vị ──────────────────────────────────────────────────────────
def test_don_vi_can_khong_co_quyen_bi_tu_choi(client):
    r = client.post("/api/thi-dua/don-vi", json={"year": 2026, "danh_hieu": "Tập thể xuất sắc"})
    assert r.status_code == 403


def test_don_vi_crud_toan_trung_tam_va_phong(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_unit")
    r = client.post("/api/thi-dua/don-vi", json={
        "year": 2026, "department_id": None, "danh_hieu": "Tập thể lao động xuất sắc",
        "so_quyet_dinh": "12/QĐ", "ngay_quyet_dinh": "2026-01-15"})
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    rows = client.get("/api/thi-dua/don-vi").json()
    assert len(rows) == 1 and rows[0]["department_name"] == "Toàn Trung tâm"

    r = client.put(f"/api/thi-dua/don-vi/{did}",
                   json={"year": 2026, "department_id": 1, "danh_hieu": "Cờ thi đua"})
    assert r.status_code == 200, r.text
    rows = client.get("/api/thi-dua/don-vi").json()
    assert rows[0]["department_name"] == "Phòng Tổng hợp" and rows[0]["danh_hieu"] == "Cờ thi đua"

    assert client.delete(f"/api/thi-dua/don-vi/{did}").status_code == 200
    assert client.get("/api/thi-dua/don-vi").json() == []


def test_don_vi_phong_khong_ton_tai_bi_tu_choi(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_unit")
    r = client.post("/api/thi-dua/don-vi",
                    json={"year": 2026, "department_id": 999, "danh_hieu": "X"})
    assert r.status_code == 400


# ── Danh hiệu cá nhân ─────────────────────────────────────────────────────────
def test_ca_nhan_crud_va_cap(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_individual")
    r = client.post("/api/thi-dua/ca-nhan", json={
        "staff_id": 2, "year": 2026, "cap": "chuyen_mon", "danh_hieu": "Lao động tiên tiến"})
    assert r.status_code == 201, r.text
    rows = client.get("/api/thi-dua/ca-nhan").json()
    assert rows[0]["staff_name"] == "Trần Thị B" and rows[0]["cap_nhan"] == "Chuyên môn"


def test_ca_nhan_cap_khong_hop_le_bi_tu_choi(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_individual")
    r = client.post("/api/thi-dua/ca-nhan",
                    json={"staff_id": 2, "year": 2026, "cap": "khong_hop_le", "danh_hieu": "X"})
    assert r.status_code == 422


def test_ca_nhan_can_bo_khong_ton_tai_bi_tu_choi(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_individual")
    r = client.post("/api/thi-dua/ca-nhan",
                    json={"staff_id": 999, "year": 2026, "cap": "dang", "danh_hieu": "X"})
    assert r.status_code == 400


# ── Sáng kiến cá nhân + file ──────────────────────────────────────────────────
def test_sang_kien_file_tai_len_tai_ve_xoa(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_initiative")
    sid = client.post("/api/thi-dua/sang-kien", json={
        "staff_id": 2, "year": 2026, "ten_sang_kien": "Cải tiến quy trình"}).json()["id"]

    r = client.post(f"/api/thi-dua/sang-kien/{sid}/file",
                    files={"file": ("qd.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 200, r.text
    assert bool(client.get("/api/thi-dua/sang-kien").json()[0]["has_file"])

    r = client.get(f"/api/thi-dua/sang-kien/{sid}/file")
    assert r.status_code == 200 and r.content == b"%PDF-1.4"

    assert client.delete(f"/api/thi-dua/sang-kien/{sid}/file").status_code == 200
    assert not client.get("/api/thi-dua/sang-kien").json()[0]["has_file"]


def test_sang_kien_file_sai_dinh_dang_bi_tu_choi(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_initiative")
    sid = client.post("/api/thi-dua/sang-kien",
                      json={"staff_id": 2, "year": 2026, "ten_sang_kien": "X"}).json()["id"]
    r = client.post(f"/api/thi-dua/sang-kien/{sid}/file",
                    files={"file": ("virus.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400


# ── Tra cứu, thống kê ─────────────────────────────────────────────────────────
def test_stats_tong_hop_gop_don_vi_va_ca_nhan_loc_theo_nam(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_unit", "thi_dua.manage_individual")
    client.post("/api/thi-dua/don-vi", json={"year": 2026, "danh_hieu": "A"})
    client.post("/api/thi-dua/ca-nhan",
               json={"staff_id": 2, "year": 2026, "cap": "dang", "danh_hieu": "B"})
    client.post("/api/thi-dua/don-vi", json={"year": 2025, "danh_hieu": "C"})

    rows = client.get("/api/thi-dua/stats/tong-hop", params={"year": 2026}).json()
    assert len(rows) == 2
    assert {r["loai"] for r in rows} == {"Đơn vị", "Cá nhân"}


def test_stats_sang_kien_loc_theo_can_bo(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_initiative")
    client.post("/api/thi-dua/sang-kien", json={"staff_id": 1, "year": 2026, "ten_sang_kien": "X"})
    client.post("/api/thi-dua/sang-kien", json={"staff_id": 2, "year": 2026, "ten_sang_kien": "Y"})
    rows = client.get("/api/thi-dua/stats/sang-kien", params={"staff_id": 2}).json()
    assert len(rows) == 1 and rows[0]["ten_sang_kien"] == "Y"


def test_goi_y_danh_hieu_tra_ve_gia_tri_da_nhap(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_unit")
    client.post("/api/thi-dua/don-vi", json={"year": 2026, "danh_hieu": "Cờ thi đua xuất sắc"})
    rows = client.get("/api/thi-dua/danh-hieu-goi-y", params={"loai": "don_vi"}).json()
    assert "Cờ thi đua xuất sắc" in rows


# ── Nhập lô từ Excel ──────────────────────────────────────────────────────────
def test_import_thieu_quyen_bi_tu_choi(client):
    content = _xlsx_bytes(["Năm", "Danh hiệu"], [[2026, "X"]])
    r = client.post("/api/thi-dua/don-vi/import",
                    files={"file": ("mau.xlsx", content, _XLSX_MIME)})
    assert r.status_code == 403


def test_import_template_tai_duoc(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_unit")
    r = client.get("/api/thi-dua/don-vi/import-template")
    assert r.status_code == 200 and r.headers["content-type"].startswith(_XLSX_MIME)


def test_import_don_vi_dry_run_khong_ghi_db(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_unit")
    content = _xlsx_bytes(
        ["Năm", "Đơn vị", "Danh hiệu"],
        [[2026, "", "Tập thể xuất sắc"], [2026, "Phòng Tổng hợp", "Cờ thi đua"]])
    r = client.post("/api/thi-dua/don-vi/import?dry_run=true",
                    files={"file": ("mau.xlsx", content, _XLSX_MIME)})
    assert r.status_code == 200, r.text
    kq = r.json()
    assert kq["tong_dong"] == 2 and kq["da_them"] == 2 and kq["loi"] == []
    assert client.get("/api/thi-dua/don-vi").json() == []


def test_import_don_vi_that_bao_loi_dong_khong_khop_don_vi(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_unit")
    content = _xlsx_bytes(
        ["Năm", "Đơn vị", "Danh hiệu"],
        [[2026, "", "Tập thể xuất sắc"], [2026, "Phòng không tồn tại", "Cờ thi đua"]])
    r = client.post("/api/thi-dua/don-vi/import?dry_run=false",
                    files={"file": ("mau.xlsx", content, _XLSX_MIME)})
    kq = r.json()
    assert kq["da_them"] == 1
    assert len(kq["loi"]) == 1 and "Phòng không tồn tại" in kq["loi"][0]["ly_do"]
    rows = client.get("/api/thi-dua/don-vi").json()
    assert len(rows) == 1 and rows[0]["danh_hieu"] == "Tập thể xuất sắc"


def test_import_ca_nhan_khop_va_khong_khop_ma_can_bo(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_individual")
    content = _xlsx_bytes(
        ["Mã cán bộ", "Cấp", "Danh hiệu", "Năm"],
        [["NS002", "Chuyên môn", "Lao động tiên tiến", 2026],
         ["NSXXX", "Đảng", "X", 2026]])
    r = client.post("/api/thi-dua/ca-nhan/import?dry_run=false",
                    files={"file": ("mau.xlsx", content, _XLSX_MIME)})
    kq = r.json()
    assert kq["da_them"] == 1
    assert len(kq["loi"]) == 1 and "NSXXX" in kq["loi"][0]["ly_do"]
    rows = client.get("/api/thi-dua/ca-nhan").json()
    assert len(rows) == 1 and rows[0]["cap"] == "chuyen_mon"


def test_import_sang_kien_khong_kem_file(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_initiative")
    content = _xlsx_bytes(
        ["Mã cán bộ", "Tên sáng kiến", "Năm"],
        [["NS001", "Giải pháp đối chiếu tự động", 2026]])
    r = client.post("/api/thi-dua/sang-kien/import?dry_run=false",
                    files={"file": ("mau.xlsx", content, _XLSX_MIME)})
    kq = r.json()
    assert kq["da_them"] == 1
    rows = client.get("/api/thi-dua/sang-kien").json()
    assert len(rows) == 1 and not rows[0]["has_file"]


def test_import_thieu_cot_bat_buoc_bao_400(client, db):
    _cap_quyen(db, 1, "menu.thi_dua", "thi_dua.manage_unit")
    content = _xlsx_bytes(["Ghi chú"], [["chỉ có ghi chú, thiếu Năm/Danh hiệu"]])
    r = client.post("/api/thi-dua/don-vi/import",
                    files={"file": ("mau.xlsx", content, _XLSX_MIME)})
    assert r.status_code == 400
