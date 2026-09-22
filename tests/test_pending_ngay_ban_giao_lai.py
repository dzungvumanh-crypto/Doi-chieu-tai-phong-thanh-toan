"""
Màn "Chứng từ chờ xác nhận": chứng từ bàn giao lại sau mượn hiện NGÀY TRẢ, không
hiện ngày nộp lần đầu. Ghi chú nhập ở màn Bàn giao chứng từ đi ra cột Ghi chú.

Báo cáo đúng hạn / quá hạn KHÔNG đổi theo — vẫn tính lần nộp đầu (xem
`_RETURNED_AT_SQL` trong backend/api/dashboard.py).
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
    transaction_date TEXT, notes TEXT, borrow_reason TEXT
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
INSERT INTO departments (id, code, name) VALUES (1, 'KSNB', 'Phòng KSNB');
INSERT INTO handovers (id, department_id) VALUES (1, 1);
INSERT INTO user_tttt (id, full_name, ipcas_code, department_id) VALUES (5, 'GDV', 'CV05', 1);
INSERT INTO document_entries (id, handover_id, staff_id, entry_status, entered_by_id,
                              sheet_count, transaction_date, notes) VALUES
    -- Nộp lần đầu, chưa từng mượn
    (1, 1, 5, 'pending_confirm', 5, 10, '2026-09-01', NULL),
    -- Nộp 02/09, mượn, trả lại 15/09, sau đó sửa ghi chú (log cuối là note_edited)
    (2, 1, 5, 'pending_confirm', 5, 12, '2026-09-01', 'Thiếu 1 tờ UNC'),
    -- Lượt trả cũ đã được xác nhận; nay bị HKV từ chối nộp lại rồi nộp mới 20/09
    (3, 1, 5, 'pending_confirm', 5, 8, '2026-09-03', NULL),
    -- Đã trả lại + xác nhận, nay GDV xin mượn lần 2 → chờ duyệt yêu cầu mượn, không phải bàn giao lại
    (4, 1, 5, 'pending_confirm', 5, 9, '2026-09-05', NULL);
UPDATE document_entries SET borrow_reason = 'Bổ sung chữ ký' WHERE id = 4;
INSERT INTO entry_change_logs (entry_id, action, timestamp) VALUES
    (1, 'handover',          '2026-09-02 09:00:00'),
    (2, 'handover',          '2026-09-02 09:00:00'),
    (2, 'confirmed',         '2026-09-02 10:00:00'),
    (2, 'borrowed',          '2026-09-10 08:00:00'),
    (2, 'returned',          '2026-09-15 14:00:00'),
    (2, 'note_edited',       '2026-09-16 08:00:00'),
    (3, 'handover',          '2026-09-04 09:00:00'),
    (3, 'returned',          '2026-09-06 09:00:00'),
    (3, 'rejected_handover', '2026-09-19 09:00:00'),
    (3, 'handover',          '2026-09-20 09:00:00'),
    (4, 'handover',          '2026-09-06 09:00:00'),
    (4, 'borrowed',          '2026-09-08 09:00:00'),
    (4, 'returned',          '2026-09-09 09:00:00'),
    (4, 'confirmed',         '2026-09-09 10:00:00'),
    (4, 'borrow_requested',  '2026-09-21 09:00:00');
"""


@pytest.fixture
def client():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_current_staff] = lambda: {
        "id": 5, "role": "chuyen_vien", "department_id": 1,
        "username": "gdv", "full_name": "GDV",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()
    conn.close()


def _theo_id(client) -> dict:
    r = client.get("/api/dashboard/pending-items")
    assert r.status_code == 200, r.text
    return {h["entry_id"]: h for h in r.json()["handovers"]}


def test_nop_lan_dau_giu_ngay_nop(client):
    h = _theo_id(client)[1]
    assert h["submit_date"] == "2026-09-02"
    assert h["is_handback"] is False


def test_ban_giao_lai_hien_ngay_tra(client):
    h = _theo_id(client)[2]
    assert h["submit_date"] == "2026-09-15"
    assert h["is_handback"] is True


def test_nop_moi_sau_lan_tra_cu_khong_tinh_la_ban_giao_lai(client):
    h = _theo_id(client)[3]
    assert h["submit_date"] == "2026-09-20"
    assert h["is_handback"] is False


def test_yeu_cau_muon_lan_hai_khong_gan_nhan_ban_giao_lai(client):
    h = _theo_id(client)[4]
    assert h["is_handback"] is False
    assert h["submit_date"] == "2026-09-06"


def test_ghi_chu_o_ban_giao_ra_cot_ghi_chu(client):
    h = _theo_id(client)
    assert h[2]["notes"] == "Thiếu 1 tờ UNC"
    assert h[1]["notes"] == ""
