"""Xếp loại lao động — CRUD, phân quyền, nhập lô Excel, tra cứu/thống kê."""
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
    duong = tmp_path / "xeploai.db"
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
               (2, 'NS002', 'Trần Thị B',   'truong_phong', 2, 'b', 'x', 1);
        INSERT INTO user_groups (id, name, is_active) VALUES (1, 'XL', 1);
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


# ── CRUD cơ bản ───────────────────────────────────────────────────────────────
def test_khong_co_quyen_bi_tu_choi(client):
    r = client.post("/api/xep-loai", json={
        "staff_id": 2, "loai": "lao_dong", "ky": "nam", "nam": 2026,
        "ket_qua": "Hoàn thành tốt nhiệm vụ"})
    assert r.status_code == 403


def test_tao_sua_xoa_xep_loai_lao_dong_theo_nam(client, db):
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage")
    r = client.post("/api/xep-loai", json={
        "staff_id": 2, "loai": "lao_dong", "ky": "nam", "nam": 2026,
        "ket_qua": "Hoàn thành tốt nhiệm vụ"})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]

    rows = client.get("/api/xep-loai").json()
    assert len(rows) == 1
    assert rows[0]["staff_name"] == "Trần Thị B"
    assert rows[0]["department_name"] == "Phòng Thanh toán"
    assert rows[0]["quy"] is None

    r = client.put(f"/api/xep-loai/{rid}", json={
        "staff_id": 2, "loai": "lao_dong", "ky": "nam", "nam": 2026,
        "ket_qua": "Hoàn thành xuất sắc nhiệm vụ"})
    assert r.status_code == 200, r.text
    assert client.get("/api/xep-loai").json()[0]["ket_qua"] == "Hoàn thành xuất sắc nhiệm vụ"

    assert client.delete(f"/api/xep-loai/{rid}").status_code == 200
    assert client.get("/api/xep-loai").json() == []


def test_can_bo_khong_ton_tai_bi_tu_choi(client, db):
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage")
    r = client.post("/api/xep-loai", json={
        "staff_id": 999, "loai": "lao_dong", "ky": "nam", "nam": 2026,
        "ket_qua": "Hoàn thành tốt nhiệm vụ"})
    assert r.status_code == 400


def test_trung_lap_ky_bi_tu_choi(client, db):
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage")
    body = {"staff_id": 2, "loai": "lao_dong", "ky": "nam", "nam": 2026,
            "ket_qua": "Hoàn thành tốt nhiệm vụ"}
    assert client.post("/api/xep-loai", json=body).status_code == 201
    r = client.post("/api/xep-loai", json=body)
    assert r.status_code == 400
    assert "đã có xếp loại" in r.json()["detail"].lower()


# ── Validate loại ↔ kỳ ↔ kết quả ──────────────────────────────────────────────
def test_loai_khong_hop_voi_ky_bi_tu_choi(client, db):
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage")
    # tin_nhiem chỉ áp dụng theo năm, không theo quý
    r = client.post("/api/xep-loai", json={
        "staff_id": 2, "loai": "tin_nhiem", "ky": "quy", "nam": 2026, "quy": 1,
        "ket_qua": "Tín nhiệm cao"})
    assert r.status_code == 422


def test_ket_qua_khong_hop_le_bi_tu_choi(client, db):
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage")
    r = client.post("/api/xep-loai", json={
        "staff_id": 2, "loai": "lao_dong", "ky": "nam", "nam": 2026, "ket_qua": "Giỏi"})
    assert r.status_code == 422


def test_cap_uy_theo_quy_hop_le(client, db):
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage")
    r = client.post("/api/xep-loai", json={
        "staff_id": 2, "loai": "cap_uy", "ky": "quy", "nam": 2026, "quy": 2,
        "ket_qua": "Hoàn thành tốt nhiệm vụ"})
    assert r.status_code == 201, r.text
    rows = client.get("/api/xep-loai", params={"loai": "cap_uy"}).json()
    assert rows[0]["quy"] == 2 and rows[0]["nam"] == 2026


def test_thieu_quy_khi_ky_la_quy_bi_tu_choi(client, db):
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage")
    r = client.post("/api/xep-loai", json={
        "staff_id": 2, "loai": "cap_uy", "ky": "quy", "nam": 2026,
        "ket_qua": "Hoàn thành tốt nhiệm vụ"})
    assert r.status_code == 422


# ── Nhập lô từ Excel ──────────────────────────────────────────────────────────
def test_import_thieu_quyen_bi_tu_choi(client):
    content = _xlsx_bytes(["Mã cán bộ", "Năm", "Loại xếp loại", "Kết quả"],
                          [["NS002", 2026, "Lao động", "Hoàn thành tốt nhiệm vụ"]])
    r = client.post("/api/xep-loai/import", files={"file": ("mau.xlsx", content, _XLSX_MIME)})
    assert r.status_code == 403


def test_import_template_tai_duoc(client, db):
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage")
    r = client.get("/api/xep-loai/import-template")
    assert r.status_code == 200 and r.headers["content-type"].startswith(_XLSX_MIME)


def test_import_dry_run_khong_ghi_db(client, db):
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage")
    content = _xlsx_bytes(
        ["Mã cán bộ", "Năm", "Loại xếp loại", "Kết quả"],
        [["NS002", 2026, "Lao động", "Hoàn thành tốt nhiệm vụ"]])
    r = client.post("/api/xep-loai/import?dry_run=true",
                    files={"file": ("mau.xlsx", content, _XLSX_MIME)})
    assert r.status_code == 200, r.text
    kq = r.json()
    assert kq["tong_dong"] == 1 and kq["da_them"] == 1 and kq["loi"] == []
    assert client.get("/api/xep-loai").json() == []


def test_import_bao_loi_ma_can_bo_va_ket_qua_khong_khop(client, db):
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage")
    content = _xlsx_bytes(
        ["Mã cán bộ", "Năm", "Loại xếp loại", "Kết quả"],
        [["NS002", 2026, "Lao động", "Hoàn thành tốt nhiệm vụ"],
         ["NSXXX", 2026, "Lao động", "Hoàn thành tốt nhiệm vụ"],
         ["NS002", 2026, "Lao động", "Giỏi"]])
    r = client.post("/api/xep-loai/import?dry_run=false",
                    files={"file": ("mau.xlsx", content, _XLSX_MIME)})
    kq = r.json()
    assert kq["da_them"] == 1
    assert len(kq["loi"]) == 2
    rows = client.get("/api/xep-loai").json()
    assert len(rows) == 1 and rows[0]["ket_qua"] == "Hoàn thành tốt nhiệm vụ"


def test_import_theo_quy_va_trung_lap_trong_cung_file(client, db):
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage")
    content = _xlsx_bytes(
        ["Mã cán bộ", "Năm", "Quý", "Loại xếp loại", "Kết quả"],
        [["NS002", 2026, 1, "Cấp ủy", "Hoàn thành tốt nhiệm vụ"],
         ["NS002", 2026, 1, "Cấp ủy", "Hoàn thành xuất sắc nhiệm vụ"]])
    r = client.post("/api/xep-loai/import?dry_run=false",
                    files={"file": ("mau.xlsx", content, _XLSX_MIME)})
    kq = r.json()
    assert kq["da_them"] == 1
    assert len(kq["loi"]) == 1 and "đã có xếp loại" in kq["loi"][0]["ly_do"].lower()
    rows = client.get("/api/xep-loai", params={"loai": "cap_uy"}).json()
    assert len(rows) == 1 and rows[0]["quy"] == 1


def test_import_thieu_cot_bat_buoc_bao_400(client, db):
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage")
    content = _xlsx_bytes(["Ghi chú"], [["chỉ có ghi chú"]])
    r = client.post("/api/xep-loai/import", files={"file": ("mau.xlsx", content, _XLSX_MIME)})
    assert r.status_code == 400


# ── Tra cứu, thống kê ─────────────────────────────────────────────────────────
def test_stats_tong_hop_theo_phong(client, db):
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage")
    client.post("/api/xep-loai", json={
        "staff_id": 1, "loai": "lao_dong", "ky": "nam", "nam": 2026,
        "ket_qua": "Hoàn thành xuất sắc nhiệm vụ"})
    client.post("/api/xep-loai", json={
        "staff_id": 2, "loai": "lao_dong", "ky": "nam", "nam": 2026,
        "ket_qua": "Hoàn thành tốt nhiệm vụ"})

    r = client.get("/api/xep-loai/stats/tong-hop", params={"loai": "lao_dong", "nam": 2026, "ky": "nam"})
    assert r.status_code == 200, r.text
    data = r.json()
    theo_phong = {row["department_name"]: row for row in data["rows"]}
    assert theo_phong["Phòng Tổng hợp"]["counts"]["Hoàn thành xuất sắc nhiệm vụ"] == 1
    assert theo_phong["Phòng Thanh toán"]["counts"]["Hoàn thành tốt nhiệm vụ"] == 1
    assert data["tong"]["total"] == 2


def test_stats_tong_hop_thieu_quy_bi_tu_choi(client, db):
    _cap_quyen(db, 1, "menu.xep_loai")
    r = client.get("/api/xep-loai/stats/tong-hop", params={"loai": "cap_uy", "nam": 2026, "ky": "quy"})
    assert r.status_code == 400


def test_stats_tong_hop_chuan_hoa_quy_ve_none_khi_ky_la_nam(client, db):
    # Gọi lệch (ky=nam nhưng vẫn kèm quy) mô phỏng caller ngoài frontend (Swagger,
    # script) — response và tên file xuất phải phản ánh đúng "theo năm", không
    # được lặng lẽ giữ nguyên quy=3 rồi in nhầm "QUÝ 3" lên tiêu đề báo cáo năm.
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage", "xep_loai.export")
    client.post("/api/xep-loai", json={
        "staff_id": 2, "loai": "lao_dong", "ky": "nam", "nam": 2026,
        "ket_qua": "Hoàn thành tốt nhiệm vụ"})
    r = client.get("/api/xep-loai/stats/tong-hop",
                   params={"loai": "lao_dong", "nam": 2026, "ky": "nam", "quy": 3})
    assert r.status_code == 200, r.text
    assert r.json()["quy"] is None

    r = client.get("/api/xep-loai/export/tong-hop",
                   params={"loai": "lao_dong", "nam": 2026, "ky": "nam", "quy": 3})
    assert r.status_code == 200
    assert "_q" not in r.headers["content-disposition"]


def test_stats_ca_nhan_5_nam_lien_tiep_dien_khoang_trong(client, db):
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage")
    client.post("/api/xep-loai", json={
        "staff_id": 2, "loai": "lao_dong", "ky": "nam", "nam": 2024,
        "ket_qua": "Hoàn thành tốt nhiệm vụ"})
    client.post("/api/xep-loai", json={
        "staff_id": 2, "loai": "lao_dong", "ky": "nam", "nam": 2026,
        "ket_qua": "Hoàn thành xuất sắc nhiệm vụ"})

    r = client.get("/api/xep-loai/stats/ca-nhan",
                   params={"staff_id": 2, "loai": "lao_dong", "den_nam": 2026})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tu_nam"] == 2022 and data["den_nam"] == 2026
    theo_nam = {r["nam"]: r["ket_qua"] for r in data["nam_theo_thu_tu"]}
    assert theo_nam[2024] == "Hoàn thành tốt nhiệm vụ"
    assert theo_nam[2026] == "Hoàn thành xuất sắc nhiệm vụ"
    assert theo_nam[2025] is None
    assert len(data["nam_theo_thu_tu"]) == 5


def test_stats_ca_nhan_loai_chi_theo_quy_bao_loi_ro_thay_vi_rong(client, db):
    # cap_uy chỉ có ky='quy' — gọi tra cứu 5 năm (chỉ đọc ky='nam') phải báo lỗi
    # rõ ràng, không được lặng lẽ trả về 5 năm "Chưa có dữ liệu" trong khi dữ
    # liệu quý vẫn tồn tại thật (xem test dưới).
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage")
    client.post("/api/xep-loai", json={
        "staff_id": 2, "loai": "cap_uy", "ky": "quy", "nam": 2026, "quy": 1,
        "ket_qua": "Hoàn thành tốt nhiệm vụ"})
    r = client.get("/api/xep-loai/stats/ca-nhan", params={"staff_id": 2, "loai": "cap_uy"})
    assert r.status_code == 400
    assert "chỉ xếp theo quý" in r.json()["detail"].lower()


# ── Xuất Excel ────────────────────────────────────────────────────────────────
def test_export_thieu_quyen_bi_tu_choi(client, db):
    _cap_quyen(db, 1, "menu.xep_loai")
    r = client.get("/api/xep-loai/export/tong-hop", params={"loai": "lao_dong", "nam": 2026, "ky": "nam"})
    assert r.status_code == 403


def test_export_tong_hop_va_ca_nhan_thanh_cong(client, db):
    _cap_quyen(db, 1, "menu.xep_loai", "xep_loai.manage", "xep_loai.export")
    client.post("/api/xep-loai", json={
        "staff_id": 2, "loai": "lao_dong", "ky": "nam", "nam": 2026,
        "ket_qua": "Hoàn thành tốt nhiệm vụ"})

    r = client.get("/api/xep-loai/export/tong-hop", params={"loai": "lao_dong", "nam": 2026, "ky": "nam"})
    assert r.status_code == 200 and r.headers["content-type"].startswith(_XLSX_MIME)

    r = client.get("/api/xep-loai/export/ca-nhan", params={"staff_id": 2, "loai": "lao_dong"})
    assert r.status_code == 200 and r.headers["content-type"].startswith(_XLSX_MIME)
