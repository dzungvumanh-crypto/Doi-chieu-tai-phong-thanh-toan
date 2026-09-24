"""Ghi chú ô bàn giao chứng từ (21/09/2026).

Người dùng chốt: chỉ ô có dữ liệu, chỉ giao dịch viên viết (qua mã quyền
handovers.edit_note), sửa không giới hạn nhưng lưu lịch sử, hiện tên người nhập;
ô quá hạn thì nội dung tự sang Báo cáo bàn giao — KHÔNG kèm tên người nhập.
"""
import io
import sqlite3

import pytest
from docx import Document
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.database import get_db
from backend.main import app
from backend.services.handover_report_docx import build_report_docx

GDV_ID = 9
GDV_KHAC_PHONG = 11
HKV_ID = 5

_SCHEMA = """
    CREATE TABLE user_groups (id INTEGER PRIMARY KEY, name TEXT, is_active BOOLEAN DEFAULT 1);
    CREATE TABLE group_members (group_id INTEGER, staff_id INTEGER);
    CREATE TABLE group_features (group_id INTEGER, feature_code TEXT);
    CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE user_tttt (
        id INTEGER PRIMARY KEY, full_name TEXT, username TEXT, ipcas_code TEXT,
        payment_username TEXT, role TEXT, department_id INTEGER, is_active INTEGER DEFAULT 1);
    CREATE TABLE handovers (
        id INTEGER PRIMARY KEY, department_id INTEGER, handover_date TEXT,
        received_by_id INTEGER, status TEXT, created_at TEXT);
    CREATE TABLE document_entries (
        id INTEGER PRIMARY KEY, handover_id INTEGER, staff_id INTEGER,
        source_user_id INTEGER, transaction_date TEXT, sheet_count INTEGER,
        notes TEXT, entry_status TEXT, entered_by_id INTEGER,
        confirmed_by_id INTEGER, confirmed_at TEXT, borrowed_at TEXT, borrow_reason TEXT,
        note_by_id INTEGER, note_at TEXT);
    CREATE TABLE entry_change_logs (
        id INTEGER PRIMARY KEY, entry_id INTEGER, action TEXT, performed_by_id INTEGER,
        timestamp TEXT, old_sheet_count INTEGER, new_sheet_count INTEGER, notes TEXT);

    INSERT INTO departments (id, name) VALUES (3, 'Phong KHDN'), (4, 'Phong KHCN');
    INSERT INTO user_tttt (id, full_name, username, role, department_id) VALUES
        (5,  'Tran Hau Kiem', 'hkv01', 'hau_kiem_vien', 1),
        (9,  'Nguyen Van A',  'gdv01', 'chuyen_vien',   3),
        (10, 'Le Thi B',      'gdv02', 'chuyen_vien',   3),
        (11, 'Pham Van C',    'gdv03', 'chuyen_vien',   4);
    INSERT INTO user_groups (id, name) VALUES (1, 'GDV'), (2, 'Hau kiem');
    INSERT INTO group_members VALUES (1, 9), (1, 10), (1, 11), (2, 5);
    INSERT INTO group_features VALUES
        (1, 'menu.handovers'), (1, 'handovers.edit_note'), (1, 'handovers.borrow'),
        (2, 'menu.handovers'), (2, 'handovers.confirm_entry'), (2, 'handovers.reject_entry');
    INSERT INTO handovers (id, department_id, handover_date) VALUES (1, 3, '2026-08-13');
    INSERT INTO document_entries (id, handover_id, staff_id, transaction_date, sheet_count,
                                  entry_status) VALUES (100, 1, 9, '2026-08-13', 25, 'confirmed');
    INSERT INTO entry_change_logs (entry_id, action, performed_by_id, new_sheet_count, timestamp)
        VALUES (100, 'handover', 9, 25, '2026-08-13 16:00:00');
"""

_USERS = {
    GDV_ID:         {"id": 9,  "role": "chuyen_vien",   "department_id": 3},
    10:             {"id": 10, "role": "chuyen_vien",   "department_id": 3},
    GDV_KHAC_PHONG: {"id": 11, "role": "chuyen_vien",   "department_id": 4},
    HKV_ID:         {"id": 5,  "role": "hau_kiem_vien", "department_id": 1},
    "admin":        {"id": 1,  "role": "admin",         "department_id": None},
}


@pytest.fixture
def ctx():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    who = {"u": _USERS[GDV_ID]}
    app.dependency_overrides[get_current_staff] = lambda: who["u"]

    def _db():
        yield conn
    app.dependency_overrides[get_db] = _db

    def dang_nhap(key):
        who["u"] = _USERS[key]
    yield TestClient(app), conn, dang_nhap
    app.dependency_overrides.clear()


def _ghi(client, note, eid=100):
    return client.put(f"/api/handovers/entries/{eid}/note", json={"note": note})


# ─── Ghi / sửa ────────────────────────────────────────────────────────────────
def test_ghi_chu_o_da_chot_khong_doi_trang_thai(ctx):
    client, conn, _ = ctx
    r = _ghi(client, "  Nộp chậm do mất điện  ")
    assert r.status_code == 200, r.text
    row = conn.execute("SELECT * FROM document_entries WHERE id=100").fetchone()
    assert row["notes"] == "Nộp chậm do mất điện"
    assert row["note_by_id"] == GDV_ID and row["note_at"]
    # Ghi chú không phải số liệu — ô đã chốt vẫn là đã chốt
    assert row["entry_status"] == "confirmed" and row["sheet_count"] == 25


def test_sua_nhieu_lan_giu_du_lich_su(ctx):
    client, conn, dang_nhap = ctx
    assert _ghi(client, "Lần 1").json()["changed"] is True
    dang_nhap(10)
    assert _ghi(client, "Lần 2").status_code == 200
    assert _ghi(client, "Lần 2").json()["changed"] is False     # trùng → không thêm dòng
    assert _ghi(client, "").status_code == 200                   # xoá

    logs = conn.execute(
        "SELECT performed_by_id, notes FROM entry_change_logs"
        " WHERE action='note_edited' ORDER BY id").fetchall()
    assert [(l[0], l[1]) for l in logs] == [(9, "Lần 1"), (10, "Lần 2"), (10, None)]
    assert conn.execute("SELECT notes FROM document_entries WHERE id=100").fetchone()[0] is None


def test_lich_su_hien_nguoi_nhap_va_khong_gan_nhan_ly_do(ctx):
    client, _, _ = ctx
    _ghi(client, "Giải trình ABC")
    h = client.get("/api/handovers/entries/100/history").json()
    assert h["note"] == "Giải trình ABC"
    assert h["note_by_name"] == "Nguyen Van A"
    labels = [l["action_label"] for l in h["logs"] if l["action"] == "note_edited"]
    assert labels == ["Sửa ghi chú: Giải trình ABC"]


# ─── Ai được ghi ─────────────────────────────────────────────────────────────
def test_khong_co_ma_quyen_thi_403(ctx):
    client, _, dang_nhap = ctx
    dang_nhap(HKV_ID)       # nhóm hậu kiểm không được tick handovers.edit_note
    assert _ghi(client, "x").status_code == 403


def test_admin_cung_bi_chan(ctx):
    """Admin đi qua mọi require_feature — màn bàn giao chặn riêng vai trò chỉ đọc."""
    client, _, dang_nhap = ctx
    dang_nhap("admin")
    assert _ghi(client, "x").status_code == 403


def test_gdv_phong_khac_bi_chan(ctx):
    client, _, dang_nhap = ctx
    dang_nhap(GDV_KHAC_PHONG)
    assert _ghi(client, "x").status_code == 403


def test_o_khong_ton_tai_404(ctx):
    client, _, _ = ctx
    assert _ghi(client, "x", eid=999).status_code == 404


def test_ky_tu_dieu_khien_bi_loc_de_word_xuat_duoc(ctx):
    """python-docx ném ValueError với \x0b, \x0c… → file Word báo cáo cả tháng hỏng."""
    client, conn, _ = ctx
    assert _ghi(client, "dòng 1\r\ndòng\x0b2\x01\tcuối").status_code == 200
    note = conn.execute("SELECT notes FROM document_entries WHERE id=100").fetchone()[0]
    assert note == "dòng 1\ndòng2\tcuối"
    data = {"overall": {}, "by_dept": [], "late_entries": [{
        "dept_name": "P", "staff_id": 9, "staff_name": "A", "transaction_date": "2026-08-03",
        "submitted_date": "2026-08-06", "days_late": 1, "sheet_count": 1, "notes": note}]}
    build_report_docx(data, 2026, 8)


def test_qua_1000_ky_tu_bi_tu_choi(ctx):
    client, _, _ = ctx
    assert _ghi(client, "a" * 1001).status_code == 422


# ─── Ghi chú không được làm lệch luồng trạng thái ────────────────────────────
def test_tu_choi_ban_giao_lai_sau_khi_ghi_chu_van_quay_ve_dang_muon(ctx):
    """reject_entry đọc log CUỐI để biết đang từ chối lần bàn giao lại hay chứng từ mới.
    Không bỏ qua note_edited thì ô rơi vào 'Bị từ chối' và mất số tờ cũ."""
    client, conn, dang_nhap = ctx
    conn.execute("UPDATE document_entries SET entry_status='pending_confirm', sheet_count=30 WHERE id=100")
    conn.execute(
        "INSERT INTO entry_change_logs (entry_id, action, performed_by_id, old_sheet_count,"
        " new_sheet_count, timestamp) VALUES (100, 'returned', 9, 25, 30, '2026-08-20 09:00:00')")
    conn.commit()
    assert _ghi(client, "Bổ sung 5 tờ").status_code == 200

    dang_nhap(HKV_ID)
    r = client.post("/api/handovers/entries/100/reject", json={"reason": "Thiếu chữ ký"})
    assert r.status_code == 200, r.text
    row = conn.execute("SELECT entry_status, sheet_count FROM document_entries WHERE id=100").fetchone()
    assert (row[0], row[1]) == ("borrowed", 25)


# ─── Sang báo cáo: chỉ nội dung ──────────────────────────────────────────────
def test_word_co_cot_ghi_chu_chi_noi_dung():
    data = {
        "overall": {"total": 1, "on_time": 0, "late": 1, "rate": 0.0},
        "by_dept": [{"dept_name": "Phòng KHDN", "total": 1, "on_time": 0, "late": 1, "rate": 0.0}],
        "late_entries": [{
            "dept_name": "Phòng KHDN", "staff_id": 9, "staff_name": "Nguyễn Văn A",
            "transaction_date": "2026-08-03", "submitted_date": "2026-08-06",
            "days_late": 2, "sheet_count": 79, "notes": "Mất điện cả buổi chiều",
        }],
    }
    doc = Document(io.BytesIO(build_report_docx(data, 2026, 8)))
    detail = doc.tables[1]
    assert detail.rows[0].cells[-1].text == "Ghi chú"
    assert detail.rows[1].cells[-1].text == "Mất điện cả buổi chiều"


def test_bao_cao_lay_ghi_chu_khong_kem_ten(ctx):
    """compute_period chỉ trả nội dung; tên người nhập không có trong late_entries."""
    from backend.services import handover_report_service as svc
    _, conn, _ = ctx
    conn.executescript("""
        ALTER TABLE departments ADD COLUMN code TEXT;
        CREATE TABLE leave_records (id INTEGER PRIMARY KEY, staff_id INTEGER, start_date TEXT,
                                    end_date TEXT, reason TEXT, status TEXT);
        CREATE TABLE public_holidays (id INTEGER PRIMARY KEY, date TEXT, name TEXT);
        CREATE TABLE duty_special_days (id INTEGER PRIMARY KEY, date TEXT, day_type TEXT,
                                        label TEXT, is_confirmed INTEGER);
        UPDATE entry_change_logs SET timestamp='2026-08-18 09:00:00' WHERE entry_id=100;
        UPDATE document_entries SET notes='Giải trình X', note_by_id=10 WHERE id=100;
    """)
    kq = svc.compute_period(conn, 2026, 8)
    assert len(kq["late_entries"]) == 1
    e = kq["late_entries"][0]
    assert e["notes"] == "Giải trình X"
    assert "Le Thi B" not in str(e)
