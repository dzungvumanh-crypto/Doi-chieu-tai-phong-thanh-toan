"""
Sổ trực hỏng KHÔNG được kéo theo Chứng từ / Nghỉ phép.

`/pending-counts` và `/pending-items` là nguồn chung cho cả 3 badge và cả 3
màn `/pending/*`, chạy cho MỌI user kể cả người không dùng Sổ trực. Trước khi
bọc try/except, một lỗi SQL ở nhánh so_truc (bảng chưa migrate, cột đổi tên)
làm 500 cả endpoint → mất luôn badge Chứng từ + Nghỉ phép, và
/pending/handovers báo "Không tải được danh sách" dù module đó vẫn khoẻ.

Giả lập bằng cách DROP bảng `so_truc_records` — đúng lỗi `sqlite3.Error` mà
nhánh đó có thể ném ra thật.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.database import get_db
from backend.main import app

_SCHEMA = """
CREATE TABLE departments (id INTEGER PRIMARY KEY, code TEXT, name TEXT);
CREATE TABLE handovers (id INTEGER PRIMARY KEY, department_id INTEGER);
CREATE TABLE document_entries (
    id INTEGER PRIMARY KEY, handover_id INTEGER, staff_id INTEGER,
    entry_status TEXT, entered_by_id INTEGER, sheet_count INTEGER DEFAULT 0,
    transaction_date TEXT, notes TEXT
);
CREATE TABLE entry_change_logs (
    id INTEGER PRIMARY KEY, entry_id INTEGER, action TEXT, timestamp DATETIME
);
CREATE TABLE user_tttt (
    id INTEGER PRIMARY KEY, full_name TEXT, ipcas_code TEXT, department_id INTEGER
);
CREATE TABLE leave_records (
    id INTEGER PRIMARY KEY, status TEXT, ksv_approver_id INTEGER, gd_approver_id INTEGER,
    staff_id INTEGER, start_date TEXT, end_date TEXT, leave_type TEXT, reason TEXT,
    created_at DATETIME
);
CREATE TABLE so_truc_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT, truc_date TEXT NOT NULL,
    gdv1_id INTEGER, gdv2_id INTEGER, ghi_chu TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    initiated_by INTEGER, ksv_id INTEGER, confirmed_by INTEGER,
    ksv_decided_by INTEGER, reject_reason TEXT, gdv_decided_by INTEGER,
    created_at DATETIME, updated_at DATETIME
);
INSERT INTO departments (id, code, name) VALUES
    (1, 'KSNB', 'Phòng KSNB'), (2, 'TH', 'Phòng Tổng hợp');
INSERT INTO handovers (id, department_id) VALUES (1, 1);
INSERT INTO document_entries (id, handover_id, staff_id, entry_status, entered_by_id, transaction_date)
VALUES (1, 1, 5, 'pending_confirm', 5, '2026-08-20');
INSERT INTO user_tttt (id, full_name, ipcas_code, department_id) VALUES
    (5, 'Chuyên viên TH', 'CV05', 2), (7, 'Trưởng phòng', 'TP07', 1);
INSERT INTO leave_records (id, status, ksv_approver_id, staff_id, start_date, end_date, leave_type, reason)
VALUES (1, 'pending_tong_hop', 7, 7, '2026-08-21', '2026-08-21', 'annual', 'viec rieng');
"""


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    # Chuyên viên phòng Tổng hợp: cả _leave_filter (gác cửa bước TH) lẫn
    # _handover_filter (chứng từ do chính mình nhập) đều trả việc — cần một vai
    # trò có CẢ HAI loại để bài kiểm này còn ý nghĩa.
    app.dependency_overrides[get_current_staff] = lambda: {
        "id": 5, "role": "chuyen_vien", "department_id": 2,
        "username": "cvth", "full_name": "Chuyên viên TH",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_pending_counts_van_dung_khi_so_truc_hong(client, db):
    binh_thuong = client.get("/api/dashboard/pending-counts").json()
    assert binh_thuong["handovers"] == 1 and binh_thuong["leaves"] == 1

    db.execute("DROP TABLE so_truc_records")
    db.commit()

    r = client.get("/api/dashboard/pending-counts")
    assert r.status_code == 200
    data = r.json()
    # Hai module cũ không được suy suyển
    assert data["handovers"] == 1
    assert data["leaves"] == 1
    assert data["handovers_by_dept"] == [{"dept_name": "Phòng KSNB", "count": 1}]
    # Nhánh hỏng trả 0 thay vì làm sập cả response
    assert data["so_truc"] == 0


def test_pending_items_van_dung_khi_so_truc_hong(client, db):
    db.execute("DROP TABLE so_truc_records")
    db.commit()

    r = client.get("/api/dashboard/pending-items")
    assert r.status_code == 200
    data = r.json()
    assert len(data["handovers"]) == 1
    assert data["so_truc"] == []


def test_loi_so_truc_duoc_ghi_log(client, db, caplog):
    """Không nuốt lỗi im lặng — phải còn dấu vết để tìm nguyên nhân."""
    db.execute("DROP TABLE so_truc_records")
    db.commit()

    with caplog.at_level("ERROR", logger="backend.api.dashboard"):
        client.get("/api/dashboard/pending-counts")
    assert any("sổ trực" in rec.message.lower() for rec in caplog.records)
