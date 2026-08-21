"""
Test phân quyền + state machine module Sổ trực cuối ngày (Phòng Thanh toán).

Viết theo góp ý review PR #35 (Người 1): state machine đã phức tạp gấp đôi
bản đầu (thêm draft_cancel, gdv_ack, request_edit, ksv_finalize_edit,
ksv_decision 3 giá trị) mà chưa có test nào — 1 blocker thật (endpoint
citad-status gọi hàm không tồn tại) đáng lẽ bắt được ngay bởi 1 test gọi
GET /api/so-truc/{ngay}/citad-status, nhưng vì 0 test nên lọt tới tận khi
người review chạy tay mới phát hiện.

Theo đúng pattern có sẵn ở tests/test_duty_permissions.py: TestClient +
dependency_overrides cho get_current_staff/get_db, DB SQLite in-memory tự
tạo schema tối thiểu (KHÔNG chạy migrations thật — nhanh, cô lập).
"""
import json
import sqlite3
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.database import get_db
from backend.main import app

_NGAY = "2026-08-20"

_SCHEMA = """
CREATE TABLE departments (id INTEGER PRIMARY KEY, code TEXT, name TEXT);
CREATE TABLE user_tttt (
    id INTEGER PRIMARY KEY,
    full_name TEXT,
    username TEXT,
    role TEXT DEFAULT 'chuyen_vien',
    department_id INTEGER,
    is_active INTEGER DEFAULT 1,
    is_deleted INTEGER DEFAULT 0
);
CREATE TABLE user_groups   (id INTEGER PRIMARY KEY, name TEXT, is_active INTEGER DEFAULT 1);
CREATE TABLE group_members (group_id INTEGER, staff_id INTEGER);
CREATE TABLE group_features(group_id INTEGER, feature_code TEXT);
CREATE TABLE doi_chieu_citad_sessions (
    ngay TEXT PRIMARY KEY, data TEXT, updated_at DATETIME, updated_by INTEGER,
    status TEXT NOT NULL DEFAULT 'final', created_by INTEGER
);
CREATE TABLE so_truc_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    truc_date         TEXT    NOT NULL,
    gdv1_id           INTEGER,
    gdv2_id           INTEGER,
    ghi_chu           TEXT    DEFAULT '',
    status            TEXT    NOT NULL DEFAULT 'draft',
    initiated_by      INTEGER,
    initiated_at      DATETIME,
    ksv_id            INTEGER,
    confirmed_by      INTEGER,
    confirmed_at      DATETIME,
    ksv_decided_by    INTEGER,
    ksv_decided_at    DATETIME,
    reject_reason     TEXT,
    ksv_decision      TEXT,
    gdv_decided_by    INTEGER,
    gdv_decided_at    DATETIME,
    truc_phu_ids      TEXT    DEFAULT '[]',
    created_at        DATETIME NOT NULL,
    updated_at        DATETIME NOT NULL
);
"""

# staff_id cố định dùng xuyên suốt: 1 GDV1, 2 GDV2, 3 KSV, 9 người ngoài
GDV1, GDV2, KSV, NGOAI = 1, 2, 3, 9


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO departments (id, code, name) VALUES (1, 'PAYMENT', 'Phòng Thanh toán')")
    for uid, name in ((GDV1, "GDV 1"), (GDV2, "GDV 2"), (KSV, "KSV"), (NGOAI, "Người ngoài")):
        conn.execute(
            "INSERT INTO user_tttt (id, full_name, department_id) VALUES (?, ?, 1)", (uid, name)
        )
    # Nhóm quyền, đúng cách require_feature() thật sự kiểm tra (join 3 bảng
    # group_*) — "lớp NGOÀI" (menu.so_truc, ai cũng cần để vào module) cấp
    # cho CẢ 4 người kể cả NGOAI (test 403 ở đây phải là 403 từ "lớp TRONG"
    # — NotAllowedError vì không phải gdv1/gdv2/ksv của ĐÚNG bản ghi này —
    # chứ không phải 403 vì thiếu quyền vào module). "lớp TRONG"
    # (so_truc.ksv_confirm, riêng vai KSV) chỉ cấp cho KSV.
    conn.execute("INSERT INTO user_groups (id, name) VALUES (1, 'Nhan vien Thanh toan')")
    for uid in (GDV1, GDV2, KSV, NGOAI):
        conn.execute("INSERT INTO group_members (group_id, staff_id) VALUES (1, ?)", (uid,))
    conn.execute("INSERT INTO group_features (group_id, feature_code) VALUES (1, 'menu.so_truc')")
    conn.execute("INSERT INTO user_groups (id, name) VALUES (2, 'KSV Thanh toan')")
    conn.execute("INSERT INTO group_members (group_id, staff_id) VALUES (2, ?)", (KSV,))
    conn.execute("INSERT INTO group_features (group_id, feature_code) VALUES (2, 'so_truc.ksv_confirm')")
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _dang_nhap(staff_id: int, role: str = "chuyen_vien"):
    app.dependency_overrides[get_current_staff] = lambda: {
        "id": staff_id, "role": role, "username": f"u{staff_id}", "full_name": "Người dùng",
    }


def _seed_record(db, **overrides) -> int:
    """Chèn thẳng 1 dòng so_truc_records qua SQL — dùng cho test CHỈ quan
    tâm hành vi ở 1 bước chuyển trạng thái cụ thể, không cần đi lại từ đầu
    luồng draft->pending_ksv->approved qua API."""
    now = datetime.now().isoformat()
    row = {
        "truc_date": _NGAY, "gdv1_id": GDV1, "gdv2_id": GDV2, "ghi_chu": "",
        "status": "draft", "initiated_by": None, "initiated_at": None,
        "ksv_id": None, "confirmed_by": None, "confirmed_at": None,
        "ksv_decided_by": None, "ksv_decided_at": None, "reject_reason": None,
        "ksv_decision": None, "gdv_decided_by": None, "gdv_decided_at": None,
        "truc_phu_ids": "[]", "created_at": now, "updated_at": now,
    }
    row.update(overrides)
    cols = ", ".join(row.keys())
    ph = ", ".join("?" * len(row))
    cur = db.execute(f"INSERT INTO so_truc_records ({cols}) VALUES ({ph})", list(row.values()))
    db.commit()
    return cur.lastrowid


# ══════════════════════════════════════════════════════════════
# CẤU TRÚC — mọi endpoint /api/so-truc phải gắn require_feature
# ══════════════════════════════════════════════════════════════

def _ma_tinh_nang(ham) -> str | None:
    for cell in (ham.__closure__ or ()):
        try:
            v = cell.cell_contents
        except ValueError:
            continue
        if isinstance(v, str) and (v == "menu.so_truc" or v.startswith("so_truc.")):
            return v
    return None


def _route_so_truc():
    ra = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if not path.startswith("/api/so-truc"):
            continue
        ma = next((m for d in r.dependant.dependencies
                   if (m := _ma_tinh_nang(d.call))), None)
        for method in (r.methods or set()) - {"HEAD", "OPTIONS"}:
            ra.append((method, path, ma))
    return ra


def test_moi_endpoint_so_truc_deu_enforce_require_feature():
    thieu = [(m, p) for m, p, ma in _route_so_truc() if ma is None]
    assert not thieu, f"Endpoint chưa gắn require_feature: {thieu}"


# ══════════════════════════════════════════════════════════════
# SMOKE TEST — mọi route KHÔNG được trả 500/503 (đúng lớp lỗi của
# blocker citad-status: hàm/import bị thiếu chỉ lộ ra khi CHẠY THẬT,
# không phải lỗi 400/403 nghiệp vụ bình thường)
# ══════════════════════════════════════════════════════════════

def test_khong_route_nao_tra_ve_500(client, db):
    _dang_nhap(GDV1)
    calls = [
        ("GET", "/api/so-truc/history"),
        ("GET", "/api/so-truc/gdv-candidates"),
        ("GET", "/api/so-truc/ksv-candidates"),
        ("GET", f"/api/so-truc/{_NGAY}"),
        ("GET", f"/api/so-truc/{_NGAY}/citad-status"),
    ]
    loi = [(m, p, r.status_code) for m, p in calls
           if (r := client.request(m, p)).status_code >= 500]
    assert not loi, f"Route trả lỗi server thật (không phải 400/403): {loi}"


def test_gdv_candidates_tra_dung_nguoi_phong_thanh_toan(client, db):
    _dang_nhap(GDV1)
    r = client.get("/api/so-truc/gdv-candidates")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert GDV1 in ids and GDV2 in ids


# ══════════════════════════════════════════════════════════════
# HÀNH VI — 403 cho người ngoài
# ══════════════════════════════════════════════════════════════

def test_nguoi_ngoai_bi_chan_403_khi_sua_ban_ghi_da_khoa(client, db):
    """Đã khoá gdv1_id/gdv2_id (bất kỳ ai KHÔNG phải 2 người đó) không được
    save-draft tiếp — NotAllowedError -> 403, không phải lỗi khác. Phải
    seed sẵn 1 bản ghi đã khoá — draft TRỐNG (chưa ai chọn gì) thì AI có
    menu.so_truc cũng tạo mới được, không rơi vào nhánh 403 đang test."""
    _seed_record(db, status="draft")
    _dang_nhap(NGOAI)
    r = client.post(
        f"/api/so-truc/{_NGAY}/save-draft",
        json={"gdv1_id": GDV1, "gdv2_id": GDV2, "ghi_chu": "sua lai", "truc_phu_ids": []},
    )
    assert r.status_code == 403


def test_nguoi_ngoai_bi_chan_403_khi_huy_phien(client, db):
    _seed_record(db, status="draft")
    _dang_nhap(NGOAI)
    r = client.post(f"/api/so-truc/{_NGAY}/draft-cancel", json={"reason": "huy ho"})
    assert r.status_code == 403


def test_dung_gdv_thi_sua_duoc(client, db):
    """Đối chứng — đúng 1 trong 2 GDV thì KHÔNG bị 403 (qua được lớp quyền,
    dù trạng thái cuối có lỗi nghiệp vụ khác cũng không phải vấn đề ở đây)."""
    _dang_nhap(GDV1)
    r = client.post(
        f"/api/so-truc/{_NGAY}/save-draft",
        json={"gdv1_id": GDV1, "gdv2_id": GDV2, "ghi_chu": "cap nhat", "truc_phu_ids": []},
    )
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════
# HÀNH VI — KSV bị khoá, không đổi được sau khi đã chọn
# ══════════════════════════════════════════════════════════════

def test_khong_doi_duoc_ksv_da_chon(client, db):
    _seed_record(db, status="pending_ksv", ksv_id=KSV, initiated_by=GDV1)
    _dang_nhap(GDV1)
    r = client.post(
        f"/api/so-truc/{_NGAY}/forward-ksv",
        json={"gdv1_id": GDV1, "gdv2_id": GDV2, "ghi_chu": "", "ksv_id": NGOAI, "truc_phu_ids": []},
    )
    assert r.status_code == 400
    assert "không được đổi ksv" in r.json()["detail"].lower() or "khong duoc doi ksv" in r.json()["detail"].lower()


# ══════════════════════════════════════════════════════════════
# HÀNH VI — reject_cancel khoá form, chỉ còn draft_cancel
# ══════════════════════════════════════════════════════════════

def test_reject_cancel_chan_save_draft(client, db):
    _seed_record(db, status="draft", ksv_id=KSV, ksv_decision="reject_cancel",
                 reject_reason="KSV yeu cau huy")
    _dang_nhap(GDV1)
    r = client.post(
        f"/api/so-truc/{_NGAY}/save-draft",
        json={"gdv1_id": GDV1, "gdv2_id": GDV2, "ghi_chu": "van co sua", "truc_phu_ids": []},
    )
    assert r.status_code == 400


def test_reject_cancel_chan_forward_ksv(client, db):
    _seed_record(db, status="draft", ksv_id=KSV, ksv_decision="reject_cancel",
                 reject_reason="KSV yeu cau huy")
    _dang_nhap(GDV1)
    r = client.post(
        f"/api/so-truc/{_NGAY}/forward-ksv",
        json={"gdv1_id": GDV1, "gdv2_id": GDV2, "ghi_chu": "", "ksv_id": KSV, "truc_phu_ids": []},
    )
    assert r.status_code == 400


def test_reject_cancel_van_huy_duoc(client, db):
    """Đối chứng — draft-cancel vẫn hợp lệ khi ksv_decision='reject_cancel'
    (đây là ĐƯỜNG DUY NHẤT còn mở, khác 2 test trên)."""
    _seed_record(db, status="draft", ksv_id=KSV, ksv_decision="reject_cancel",
                 reject_reason="KSV yeu cau huy")
    _dang_nhap(GDV1)
    r = client.post(f"/api/so-truc/{_NGAY}/draft-cancel", json={"reason": "dong y huy"})
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


# ══════════════════════════════════════════════════════════════
# HÀNH VI — draft_cancel xong thì mở được phiên MỚI cùng ngày
# ══════════════════════════════════════════════════════════════

def test_sau_khi_huy_mo_duoc_phien_moi_cung_ngay(client, db):
    _seed_record(db, status="draft")
    _dang_nhap(GDV1)
    r1 = client.post(f"/api/so-truc/{_NGAY}/draft-cancel", json={"reason": "huy phien nay"})
    assert r1.status_code == 200
    assert r1.json()["status"] == "cancelled"

    # get_active_by_date bỏ qua dòng 'cancelled' -> save_draft tạo dòng MỚI,
    # không vướng lỗi "đã ở trạng thái khác" hay vi phạm ràng buộc nào.
    r2 = client.post(
        f"/api/so-truc/{_NGAY}/save-draft",
        json={"gdv1_id": GDV1, "gdv2_id": GDV2, "ghi_chu": "phien lam lai", "truc_phu_ids": []},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "draft"

    rows = db.execute(
        "SELECT COUNT(*) c FROM so_truc_records WHERE truc_date=?", (_NGAY,)
    ).fetchone()["c"]
    assert rows == 2, "phải có 2 dòng riêng biệt cho cùng 1 ngày (1 cancelled + 1 draft mới)"


# ══════════════════════════════════════════════════════════════
# HÀNH VI — request_edit 2 nhánh (GDV / KSV)
# ══════════════════════════════════════════════════════════════

def test_request_edit_nhanh_gdv(client, db):
    _seed_record(db, status="approved", ksv_id=KSV, ksv_decided_by=KSV,
                 ksv_decided_at=datetime.now().isoformat())
    _dang_nhap(GDV1)
    r = client.post(f"/api/so-truc/{_NGAY}/request-edit", json={"reason": "nhap sai so lieu"})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "draft"
    assert d["gdv_decided_by"] == GDV1
    assert d["ksv_decided_by"] is None
    assert d["ksv_decision"] is None


def test_request_edit_nguoi_ngoai_bi_chan(client, db):
    _seed_record(db, status="approved", ksv_id=KSV, ksv_decided_by=KSV,
                 ksv_decided_at=datetime.now().isoformat())
    _dang_nhap(NGOAI)
    r = client.post(f"/api/so-truc/{_NGAY}/request-edit", json={"reason": "toi muon sua"})
    assert r.status_code == 403


def test_request_edit_nhanh_ksv_roi_tu_chot_lai_approved(client, db):
    _seed_record(db, status="approved", ksv_id=KSV, ksv_decided_by=KSV,
                 ksv_decided_at=datetime.now().isoformat())
    _dang_nhap(KSV, role="pho_phong")
    r1 = client.post(f"/api/so-truc/{_NGAY}/request-edit", json={"reason": "KSV tu sua lai"})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["status"] == "draft"
    assert d1["ksv_decision"] == "self_edit"

    # GDV bị chặn không cho chen vào lúc KSV đang tự sửa
    _dang_nhap(GDV1)
    r_blocked = client.post(
        f"/api/so-truc/{_NGAY}/save-draft",
        json={"gdv1_id": GDV1, "gdv2_id": GDV2, "ghi_chu": "gdv chen vao", "truc_phu_ids": []},
    )
    assert r_blocked.status_code == 400

    # Đúng KSV tự chốt thẳng lại approved, không qua vòng duyệt nào khác
    _dang_nhap(KSV, role="pho_phong")
    r2 = client.post(
        f"/api/so-truc/{_NGAY}/ksv-finalize-edit",
        json={"gdv1_id": GDV1, "gdv2_id": GDV2, "ghi_chu": "da sua xong", "truc_phu_ids": []},
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["status"] == "approved"
    assert d2["ksv_decision"] is None
    assert d2["reject_reason"] is None


# ══════════════════════════════════════════════════════════════
# HÀNH VI — is_deleted=1 không được xuất hiện/dùng làm KSV (fix review)
# ══════════════════════════════════════════════════════════════

def test_ksv_da_xoa_khong_hien_trong_danh_sach_chon(client, db):
    db.execute("INSERT INTO user_tttt (id, full_name, is_deleted) VALUES (99, 'KSV Da Nghi', 1)")
    db.execute("INSERT INTO group_members (group_id, staff_id) VALUES (2, 99)")
    db.commit()
    _dang_nhap(GDV1)
    r = client.get("/api/so-truc/ksv-candidates")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert 99 not in ids
    assert KSV in ids


def test_forward_ksv_chan_ksv_da_xoa(client, db):
    db.execute("INSERT INTO user_tttt (id, full_name, is_deleted) VALUES (99, 'KSV Da Nghi', 1)")
    db.execute("INSERT INTO group_members (group_id, staff_id) VALUES (2, 99)")
    db.commit()
    _seed_record(db, status="draft")
    _dang_nhap(GDV1)
    r = client.post(
        f"/api/so-truc/{_NGAY}/forward-ksv",
        json={"gdv1_id": GDV1, "gdv2_id": GDV2, "ghi_chu": "", "ksv_id": 99, "truc_phu_ids": []},
    )
    assert r.status_code == 400
    assert "không còn quyền" in r.json()["detail"].lower()


# ══════════════════════════════════════════════════════════════
# HÀNH VI — trang không được chết vì citad-status (blocker vừa sửa)
# ══════════════════════════════════════════════════════════════

def test_citad_status_endpoint_khong_500(client, db):
    """Test tối thiểu đáng lẽ bắt được blocker `get_reconciliation_status`
    thiếu hàm — bảng `doi_chieu_citad_sessions` đã có sẵn trong _SCHEMA
    (dùng chung cho mọi test, không riêng test này) nên lỗi thật sự đo
    được ở đây chỉ có thể là hàm/import bị thiếu, không lẫn lỗi thiếu
    bảng."""
    _dang_nhap(GDV1)
    r = client.get(f"/api/so-truc/{_NGAY}/citad-status")
    assert r.status_code == 200
    assert r.json() == {"exists": False, "matched": False}
