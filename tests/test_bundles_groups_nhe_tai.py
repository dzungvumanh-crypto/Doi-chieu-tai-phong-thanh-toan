"""`GET /api/bundles/groups` phải nhẹ — không kéo cả kho chứng từ về.

Ba ô lọc trên trang "Đóng chứng từ" đều mặc định "tất cả", nên lần mở trang đầu
tiên gọi endpoint này KHÔNG kèm điều kiện nào. Trước đây nó trả kèm
`bundles[].items[]`: mỗi nhóm 1 câu SQL, mỗi tập thêm 1 câu — 283 câu và 315 KB
cho kho một năm, và tăng thẳng theo tổng lượng lưu trữ (đo trên dữ liệu nhân
theo năm: 5 năm là 513 ms / 5,1 MB). Giao diện không đọc tới `bundles` một lần nào.

Chi tiết tập nằm ở `GET /groups/{id}` và các đường in bìa — không đụng tới.
"""
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, ".")

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.main import app

SCHEMA = """
CREATE TABLE departments (
    id INTEGER PRIMARY KEY, code TEXT, name TEXT,
    is_source INTEGER DEFAULT 1, is_active INTEGER DEFAULT 1);
CREATE TABLE user_tttt (
    id INTEGER PRIMARY KEY, employee_code TEXT, full_name TEXT, role TEXT,
    department_id INTEGER, username TEXT, phone TEXT, email TEXT,
    start_date TEXT, ipcas_code TEXT, payment_username TEXT, is_active INTEGER DEFAULT 1);
CREATE TABLE bundle_groups (
    id INTEGER PRIMARY KEY, department_id INTEGER, created_by_id INTEGER,
    total_bundles INTEGER, created_at TEXT, notes TEXT);
CREATE TABLE bundles (
    id INTEGER PRIMARY KEY, group_id INTEGER, sequence INTEGER, total_sheets INTEGER,
    custodian_id INTEGER, storage_box TEXT, storage_location TEXT,
    cover_printed_at TEXT, status TEXT, cover_units TEXT);
CREATE TABLE bundle_items (id INTEGER PRIMARY KEY, bundle_id INTEGER, entry_id INTEGER);
"""

N_NHOM, N_TAP_MOI_NHOM, N_MUC_MOI_TAP = 12, 20, 8


class _ConnDem(sqlite3.Connection):
    """Đếm số câu lệnh SQL để bắt N+1 quay lại."""
    dem = 0

    def execute(self, *a, **k):
        _ConnDem.dem += 1
        return super().execute(*a, **k)


@pytest.fixture
def client_co_kho():
    # check_same_thread=False: TestClient chạy route trong threadpool, giống get_db thật
    conn = sqlite3.connect(":memory:", check_same_thread=False, factory=_ConnDem)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO departments VALUES (1,'KT','Phòng Kế toán',1,1)")
    conn.execute("INSERT INTO user_tttt (id,employee_code,full_name,role,department_id,username)"
                 " VALUES (1,'NV001','Nguyễn Văn A','admin',1,'a')")
    bid = 0
    for g in range(1, N_NHOM + 1):
        conn.execute("INSERT INTO bundle_groups VALUES (?,1,1,?,?,?)",
                     (g, N_TAP_MOI_NHOM, f"2026-0{(g % 9) + 1}-01 08:00:00",
                      f"Tháng {g:02d}/2026"))
        for s in range(1, N_TAP_MOI_NHOM + 1):
            bid += 1
            conn.execute("INSERT INTO bundles VALUES (?,?,?,300,1,'H1','K1',NULL,'pending',NULL)",
                         (bid, g, s))
            for m in range(N_MUC_MOI_TAP):
                conn.execute("INSERT INTO bundle_items (bundle_id, entry_id) VALUES (?,?)", (bid, m))
    conn.commit()

    def _db():
        yield conn

    app.dependency_overrides[get_current_staff] = lambda: {
        "id": 1, "role": StaffRole.ADMIN, "username": "a", "full_name": "Nguyễn Văn A"}
    app.dependency_overrides[get_db] = _db
    yield TestClient(app), conn
    app.dependency_overrides.clear()
    conn.close()


# ── Không kéo cả kho về ──────────────────────────────────────────────────────

def test_khong_tra_kem_tap_va_muc(client_co_kho):
    client, _ = client_co_kho
    r = client.get("/api/bundles/groups")
    assert r.status_code == 200
    nhom = r.json()
    assert len(nhom) == N_NHOM
    assert "bundles" not in nhom[0], (
        "danh sách bìa không được kèm tập/mục — giao diện không đọc tới, "
        "mà mỗi tập là thêm một câu SQL và vài KB payload"
    )


def test_so_cau_sql_khong_tang_theo_so_tap(client_co_kho):
    """Chốt chặn N+1: số câu SQL phải là hằng số, không phụ thuộc kho lớn cỡ nào."""
    client, _ = client_co_kho
    _ConnDem.dem = 0
    client.get("/api/bundles/groups")
    assert _ConnDem.dem <= 5, (
        f"{_ConnDem.dem} câu SQL cho {N_NHOM} nhóm / {N_NHOM * N_TAP_MOI_NHOM} tập — "
        "N+1 đã quay lại"
    )


def test_payload_khong_phinh_theo_so_tap(client_co_kho):
    client, _ = client_co_kho
    r = client.get("/api/bundles/groups")
    kb = len(r.content) / 1024
    assert kb < 12, f"payload {kb:.1f} KB cho {N_NHOM} nhóm — đang trả thừa dữ liệu"


# ── Vẫn đủ thứ giao diện cần ─────────────────────────────────────────────────

def test_van_du_cot_hien_tren_bang(client_co_kho):
    """Trang danh sách hiện: tên phòng, kỳ, ngày tạo, người tạo, số bìa."""
    client, _ = client_co_kho
    g = client.get("/api/bundles/groups").json()[0]
    assert g["department"]["name"] == "Phòng Kế toán"
    assert g["created_by_staff"]["full_name"] == "Nguyễn Văn A"
    assert g["notes"].startswith("Tháng")
    assert g["created_at"]
    assert g["total_bundles"] == N_TAP_MOI_NHOM, "số bìa lấy từ cột sẵn có, không đếm lại"
    assert g["id"]


def test_loc_theo_phong_thang_nam_van_chay(client_co_kho):
    client, _ = client_co_kho
    r = client.get("/api/bundles/groups",
                   params={"department_id": 1, "year": 2026, "month": 3})
    assert r.status_code == 200
    ra = r.json()
    assert len(ra) == 1 and ra[0]["notes"] == "Tháng 03/2026"


def test_khong_co_nhom_nao_thi_tra_mang_rong(client_co_kho):
    client, _ = client_co_kho
    r = client.get("/api/bundles/groups", params={"year": 1999})
    assert r.status_code == 200 and r.json() == []


def test_nhom_khong_ro_nguoi_tao_van_tra_ve_duoc(client_co_kho):
    """created_by_id trỏ vào người đã bị xóa — không được ném 500."""
    client, conn = client_co_kho
    conn.execute("INSERT INTO bundle_groups VALUES (99,1,404,3,'2026-09-01 08:00:00','Tháng 09/2026')")
    conn.commit()
    r = client.get("/api/bundles/groups", params={"year": 2026, "month": 9})
    assert r.status_code == 200
    assert r.json()[0]["created_by_staff"] is None
