"""Xoá ô chứng từ ĐÃ XÁC NHẬN phải hỏi lý do và để lại vết trong Nhật ký thao tác.

Trước bản vá, hậu kiểm viên xoá trắng một ô đã chốt là ô đó biến mất cùng toàn bộ
`entry_change_logs` của nó, còn nhật ký hệ thống chỉ ghi được "PUT /entry-upsert —
HTTP 200" — không phân biệt nổi với một lần sửa số tờ bình thường. Nghĩa là số liệu
bàn giao đã xác nhận bị gỡ mà không ai truy được ai gỡ, gỡ của ai, ngày nào.

Chạy: .venv/Scripts/python.exe -m pytest tests/test_xoa_o_chung_tu_ghi_nhat_ky.py -v
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.database import get_db
from backend.main import app

HKV_ID = 5          # hậu kiểm viên đang đăng nhập
GDV_ID = 9          # giao dịch viên có ô chứng từ
PHONG_ID = 3
NGAY = "2026-08-13"

_SCHEMA = """
    CREATE TABLE user_groups (id INTEGER PRIMARY KEY, name TEXT, is_active BOOLEAN DEFAULT 1);
    CREATE TABLE group_members (group_id INTEGER, staff_id INTEGER);
    CREATE TABLE group_features (group_id INTEGER, feature_code TEXT);
    CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE user_tttt (
        id INTEGER PRIMARY KEY, full_name TEXT, username TEXT, ipcas_code TEXT,
        role TEXT, department_id INTEGER, is_active INTEGER DEFAULT 1);
    CREATE TABLE staff_department_history (
        id INTEGER PRIMARY KEY, staff_id INTEGER, department_id INTEGER, effective_from TEXT);
    CREATE TABLE handovers (
        id INTEGER PRIMARY KEY, department_id INTEGER, handover_date TEXT,
        received_by_id INTEGER, status TEXT, created_at TEXT,
        UNIQUE(department_id, handover_date));
    CREATE TABLE document_entries (
        id INTEGER PRIMARY KEY, handover_id INTEGER, staff_id INTEGER,
        source_user_id INTEGER, transaction_date TEXT, sheet_count INTEGER,
        notes TEXT, entry_status TEXT, entered_by_id INTEGER,
        confirmed_by_id INTEGER, confirmed_at TEXT, borrowed_at TEXT, borrow_reason TEXT);
    CREATE TABLE entry_change_logs (
        id INTEGER PRIMARY KEY, entry_id INTEGER, action TEXT, performed_by_id INTEGER,
        timestamp TEXT, old_sheet_count INTEGER, new_sheet_count INTEGER, notes TEXT);
    CREATE TABLE audit_logs (
        id INTEGER PRIMARY KEY, actor_id INTEGER, action TEXT, target_type TEXT,
        target_id INTEGER, detail TEXT, ip_address TEXT, created_at TEXT);

    INSERT INTO departments (id, name) VALUES (3, 'Phong Khach hang doanh nghiep');
    INSERT INTO user_tttt (id, full_name, username, ipcas_code, role, department_id) VALUES
        (5, 'Tran Thi Hau Kiem', 'hkv01', 'HK005', 'hau_kiem_vien', 1),
        (9, 'Nguyen Van A',      'gdv01', 'GD009', 'chuyen_vien',   3);
    -- HKV lấy quyền qua nhóm, đúng như trên máy thật (không phải admin bypass)
    INSERT INTO user_groups (id, name, is_active) VALUES (1, 'Nhom hau kiem', 1);
    INSERT INTO group_members (group_id, staff_id) VALUES (1, 5);
    INSERT INTO group_features (group_id, feature_code) VALUES
        (1, 'handovers.save_entry'), (1, 'handovers.confirm_entry');

    INSERT INTO handovers (id, department_id, handover_date, status)
        VALUES (1, 3, '2026-08-13', 'draft');
"""


def _client(entry_status: str = "confirmed"):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT INTO document_entries (id, handover_id, staff_id, transaction_date,"
        " sheet_count, entry_status, entered_by_id, confirmed_by_id)"
        " VALUES (100, 1, ?, ?, 25, ?, ?, ?)",
        (GDV_ID, NGAY, entry_status, GDV_ID, HKV_ID),
    )
    conn.execute(
        "INSERT INTO entry_change_logs (entry_id, action, performed_by_id, new_sheet_count)"
        " VALUES (100, 'handover', ?, 25)", (GDV_ID,),
    )
    conn.commit()

    app.dependency_overrides[get_current_staff] = lambda: {
        "id": HKV_ID, "role": "hau_kiem_vien", "username": "hkv01",
        "full_name": "Tran Thi Hau Kiem", "department_id": 1,
    }
    def _db():
        yield conn
    app.dependency_overrides[get_db] = _db
    return TestClient(app), conn


def _xoa(client, reason=None):
    body = {"staff_id": GDV_ID, "date": NGAY, "sheet_count": 0}
    if reason is not None:
        body["reason"] = reason
    return client.put("/api/handovers/entry-upsert", json=body)


@pytest.fixture
def da_xac_nhan():
    client, conn = _client("confirmed")
    yield client, conn
    app.dependency_overrides.clear()


@pytest.fixture
def cho_xac_nhan():
    client, conn = _client("pending_confirm")
    yield client, conn
    app.dependency_overrides.clear()


# ─── Thiếu lý do → chặn ───────────────────────────────────────────────────────
def test_xoa_o_da_chot_khong_co_ly_do_bi_chan(da_xac_nhan):
    client, conn = da_xac_nhan
    r = _xoa(client)
    assert r.status_code == 400, r.text
    assert "lý do" in r.json()["detail"].lower()
    # Chặn rồi thì ô phải còn nguyên, không xoá nửa vời
    assert conn.execute("SELECT COUNT(*) FROM document_entries").fetchone()[0] == 1


def test_ly_do_toan_khoang_trang_cung_bi_chan(da_xac_nhan):
    client, conn = da_xac_nhan
    assert _xoa(client, "   ").status_code == 400
    assert conn.execute("SELECT COUNT(*) FROM document_entries").fetchone()[0] == 1


# ─── Có lý do → xoá và ghi vết ────────────────────────────────────────────────
def test_xoa_co_ly_do_thi_ghi_mot_dong_nhat_ky_ke_du_chuyen(da_xac_nhan):
    client, conn = da_xac_nhan
    r = _xoa(client, "GDV nhap nham ngay, da nhap lai dung ngay 14/08")
    assert r.status_code == 200, r.text

    assert conn.execute("SELECT COUNT(*) FROM document_entries").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM entry_change_logs").fetchone()[0] == 0

    rows = conn.execute(
        "SELECT * FROM audit_logs WHERE action = 'handover_entry_delete'").fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["actor_id"] == HKV_ID          # ai xoá
    assert row["target_id"] == 100
    d = row["detail"]
    assert "Nguyen Van A" in d                # xoá của ai
    assert "GD009" in d
    assert "13/08/2026" in d                  # ngày nào
    assert "25 tờ" in d                       # bao nhiêu tờ
    assert "Phong Khach hang doanh nghiep" in d
    assert "Đã xác nhận" in d                 # trạng thái trước khi xoá
    assert "nhap nham ngay" in d              # vì sao


def test_nhat_ky_hien_bang_tieng_viet_tren_man_hinh(da_xac_nhan):
    from backend.services.audit_labels import describe_detail, describe_work, result_ok
    client, conn = da_xac_nhan
    assert _xoa(client, "Xac nhan nham").status_code == 200
    row = conn.execute("SELECT * FROM audit_logs").fetchone()

    assert describe_work(row["action"], row["target_type"]) == "Xoá ô chứng từ đã xác nhận"
    assert describe_detail(row["detail"]).startswith("Xoá ô chứng từ — GDV Nguyen Van A")
    assert result_ok(row["detail"], row["action"]) is True


# ─── Không phá luồng bình thường của GDV ─────────────────────────────────────
def test_xoa_o_chua_xac_nhan_van_khong_can_ly_do(cho_xac_nhan):
    """Ô GDV vừa nhập, hậu kiểm chưa đụng tới — xoá là thao tác sửa nháp bình thường."""
    client, conn = cho_xac_nhan
    assert _xoa(client).status_code == 200
    assert conn.execute("SELECT COUNT(*) FROM document_entries").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'handover_entry_delete'"
    ).fetchone()[0] == 0


def test_sua_so_to_khong_bi_doi_ly_do(da_xac_nhan):
    """Chỉ ĐƯỜNG XOÁ mới hỏi lý do; sửa 25 → 30 vẫn liền tay như trước."""
    client, conn = da_xac_nhan
    r = client.put("/api/handovers/entry-upsert",
                   json={"staff_id": GDV_ID, "date": NGAY, "sheet_count": 30})
    assert r.status_code == 200, r.text
    assert conn.execute("SELECT sheet_count FROM document_entries WHERE id=100").fetchone()[0] == 30


# ─── describe_detail không làm bẩn màn hình bằng dòng của middleware ─────────
def test_dong_middleware_khong_hien_chi_tiet():
    from backend.services.audit_labels import describe_detail
    assert describe_detail("HTTP 200") == ""
    assert describe_detail("HTTP 403") == ""
    assert describe_detail(None) == ""
    assert describe_detail("Xoá ô chứng từ — GDV X") == "Xoá ô chứng từ — GDV X"
