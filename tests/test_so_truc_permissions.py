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
    # KSV giữ chức danh 'pho_phong' TRONG BẢNG user_tttt (khác _dang_nhap(role=...) chỉ set
    # role của phiên đăng nhập/JWT) — list_ksv_candidates() từ 23/09/2026 lọc thêm theo đúng
    # cột này (chỉ trưởng/phó phòng), thiếu dòng này KSV sẽ rớt khỏi danh sách chọn.
    for uid, name, role in (
        (GDV1, "GDV 1", "chuyen_vien"), (GDV2, "GDV 2", "chuyen_vien"),
        (KSV, "KSV", "pho_phong"), (NGOAI, "Người ngoài", "chuyen_vien"),
    ):
        conn.execute(
            "INSERT INTO user_tttt (id, full_name, department_id, role) VALUES (?, ?, 1, ?)", (uid, name, role)
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
        ("GET", "/api/so-truc/gdv-only-candidates"),
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


def test_gdv_only_candidates_loai_truong_pho_phong(client, db):
    """Người dùng chốt 23/09/2026: "gdv là chỉ hiện tên những người không có
    chức danh trong phòng", "ksv mới là có chức danh" — GDV1/GDV2 (dùng
    /gdv-only-candidates) phải loại trưởng/phó phòng, đối xứng với điều kiện
    role đã áp cho KSV. Ô "Trực phụ" (/gdv-candidates) KHÔNG đổi — vẫn hiện
    cả trưởng/phó phòng như trước (người dùng chốt giữ nguyên)."""
    _dang_nhap(GDV1)
    r_gdv_only = client.get("/api/so-truc/gdv-only-candidates")
    r_truc_phu = client.get("/api/so-truc/gdv-candidates")
    assert r_gdv_only.status_code == 200 and r_truc_phu.status_code == 200
    ids_gdv_only = [c["id"] for c in r_gdv_only.json()]
    ids_truc_phu = [c["id"] for c in r_truc_phu.json()]
    # KSV (id=3) trong fixture db mang role='pho_phong', cùng Phòng Thanh toán.
    assert KSV not in ids_gdv_only
    assert KSV in ids_truc_phu
    assert GDV1 in ids_gdv_only and GDV2 in ids_gdv_only


def test_ksv_candidates_khong_hien_nguoi_phong_khac(client, db):
    """`so_truc.ksv_confirm` gán cho 1 nhóm lỡ có người phòng khác (department_id
    khác PAYMENT) — người đó KHÔNG được hiện trong danh sách chọn KSV của Phòng
    Thanh toán, dù đúng quyền VÀ đúng chức danh (cô lập đúng 1 biến: phòng ban).
    KSV cùng phòng (fixture `db`) vẫn phải còn."""
    db.execute("INSERT INTO departments (id, code, name) VALUES (2, 'OTHER', 'Phòng khác')")
    db.execute(
        "INSERT INTO user_tttt (id, full_name, department_id, role) VALUES (88, 'Truong phong khac', 2, 'pho_phong')"
    )
    db.execute("INSERT INTO group_members (group_id, staff_id) VALUES (2, 88)")  # nhóm 'KSV Thanh toan'
    db.commit()
    _dang_nhap(GDV1)
    r = client.get("/api/so-truc/ksv-candidates")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert 88 not in ids
    assert KSV in ids


def test_ksv_candidates_khong_hien_chuyen_vien_du_co_quyen(client, db):
    """Người dùng chốt 23/09/2026: "KSV chỉ cho chọn trưởng phòng và các phó phòng
    thôi". Một chuyên viên cùng Phòng Thanh toán, có đủ quyền `so_truc.ksv_confirm`
    (lỡ gán nhầm hoặc gán chung nhóm) vẫn KHÔNG được hiện — thiếu đúng chức danh."""
    db.execute(
        "INSERT INTO user_tttt (id, full_name, department_id, role) VALUES (77, 'Chuyen vien co quyen', 1, 'chuyen_vien')"
    )
    db.execute("INSERT INTO group_members (group_id, staff_id) VALUES (2, 77)")  # nhóm 'KSV Thanh toan'
    db.commit()
    _dang_nhap(GDV1)
    r = client.get("/api/so-truc/ksv-candidates")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert 77 not in ids
    assert KSV in ids


def test_ksv_candidates_truong_phong_cung_hop_le(client, db):
    """Cả 'truong_phong' lẫn 'pho_phong' đều hợp lệ, không chỉ 1 trong 2."""
    db.execute(
        "INSERT INTO user_tttt (id, full_name, department_id, role) VALUES (66, 'Truong phong', 1, 'truong_phong')"
    )
    db.execute("INSERT INTO group_members (group_id, staff_id) VALUES (2, 66)")
    db.commit()
    _dang_nhap(GDV1)
    r = client.get("/api/so-truc/ksv-candidates")
    ids = [c["id"] for c in r.json()]
    assert 66 in ids


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


def test_save_draft_chan_gdv_trung_nhau(client, db):
    """Frontend đã chặn (do_save_draft) nhưng gọi thẳng API là bỏ qua được —
    khác forward-ksv/ksv-finalize-edit, save-draft từng thiếu kiểm ở backend.
    Ca lưu nháp LẦN ĐẦU (chưa có bản ghi nào, đi qua _insert_new_draft) phải
    chặn được, không chỉ ca sửa bản ghi đã có."""
    _dang_nhap(GDV1)
    r = client.post(
        f"/api/so-truc/{_NGAY}/save-draft",
        json={"gdv1_id": GDV1, "gdv2_id": GDV1, "ghi_chu": "", "truc_phu_ids": []},
    )
    assert r.status_code == 400
    assert "không được trùng nhau" in r.json()["detail"]


def test_save_draft_de_trong_1_gdv_van_luu_duoc(client, db):
    """Chỉ chặn khi CẢ HAI đều có giá trị và trùng nhau — để trống 1 trong 2
    (soạn nháp dở, chưa chọn xong) không bị chặn oan."""
    _dang_nhap(GDV1)
    r = client.post(
        f"/api/so-truc/{_NGAY}/save-draft",
        json={"gdv1_id": GDV1, "gdv2_id": None, "ghi_chu": "", "truc_phu_ids": []},
    )
    assert r.status_code == 200


def test_save_draft_chan_trung_ksv_da_khoa(client, db):
    """Rà soát 23/09/2026 phát hiện: sau khi KSV đã bị khoá (vd sau reject_fix),
    save_draft() không hề kiểm gdv1_id/gdv2_id với ksv_id — lưu êm 1 bản ghi
    tự mâu thuẫn (GDV trùng KSV), chỉ lộ ra khi forward_to_ksv() kế tiếp báo
    lỗi. Tái hiện bằng script thật rồi mới vá — cùng câu kiểm với
    forward_to_ksv()/ksv_finalize_edit()."""
    _seed_record(db, status="draft", ksv_id=KSV, ksv_decision="reject_fix")
    _dang_nhap(GDV1)
    r = client.post(
        f"/api/so-truc/{_NGAY}/save-draft",
        json={"gdv1_id": GDV1, "gdv2_id": KSV, "ghi_chu": "sua nham", "truc_phu_ids": []},
    )
    assert r.status_code == 400
    assert "không được trùng" in r.json()["detail"]


def test_save_draft_ksv_da_khoa_nhung_gdv_khac_van_luu_duoc(client, db):
    """Câu kiểm mới không được chặn oan — GDV không trùng KSV đã khoá vẫn lưu
    bình thường."""
    _seed_record(db, status="draft", ksv_id=KSV, ksv_decision="reject_fix")
    _dang_nhap(GDV1)
    r = client.post(
        f"/api/so-truc/{_NGAY}/save-draft",
        json={"gdv1_id": GDV1, "gdv2_id": GDV2, "ghi_chu": "sua dung", "truc_phu_ids": []},
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


def test_ksv_finalize_edit_chan_ksv_trung_gdv(client, db):
    """ksv_finalize_edit() có thêm kiểm KSV không được trùng GDV1/GDV2 (cùng lý
    do forward_to_ksv() — chặn tự phê duyệt chính mình) nhưng ban đầu thiếu
    test riêng — bổ sung theo đúng cặp dương/âm như forward_to_ksv."""
    _seed_record(db, status="approved", ksv_id=KSV, ksv_decided_by=KSV,
                 ksv_decided_at=datetime.now().isoformat())
    _dang_nhap(KSV, role="pho_phong")
    r1 = client.post(f"/api/so-truc/{_NGAY}/request-edit", json={"reason": "KSV tu sua lai"})
    assert r1.status_code == 200

    r2 = client.post(
        f"/api/so-truc/{_NGAY}/ksv-finalize-edit",
        json={"gdv1_id": KSV, "gdv2_id": GDV2, "ghi_chu": "", "truc_phu_ids": []},
    )
    assert r2.status_code == 400
    assert "không thể tự xác nhận" in r2.json()["detail"].lower()


def test_ksv_finalize_edit_ksv_khac_gdv_van_binh_thuong(client, db):
    """Đối chứng — KSV khác cả 2 GDV thì không bị chặn bởi ràng buộc mới."""
    _seed_record(db, status="approved", ksv_id=KSV, ksv_decided_by=KSV,
                 ksv_decided_at=datetime.now().isoformat())
    _dang_nhap(KSV, role="pho_phong")
    r1 = client.post(f"/api/so-truc/{_NGAY}/request-edit", json={"reason": "KSV tu sua lai"})
    assert r1.status_code == 200

    r2 = client.post(
        f"/api/so-truc/{_NGAY}/ksv-finalize-edit",
        json={"gdv1_id": GDV1, "gdv2_id": GDV2, "ghi_chu": "", "truc_phu_ids": []},
    )
    assert r2.status_code == 200


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


def test_forward_ksv_chan_ksv_trung_gdv(client, db):
    """Ảnh người dùng gửi: 1 phó phòng vừa hợp lệ làm GDV (cán bộ trong phòng) vừa
    hợp lệ làm KSV (đúng chức danh + đúng quyền) — không được chọn CHÍNH MÌNH làm
    KSV cho bản ghi mà mình đứng tên GDV, mất tác dụng kiểm soát chéo."""
    _dang_nhap(KSV)  # chính KSV đứng tên GDV1 trong payload — phải là 1 trong 2 GDV mới qua được lớp "người ngoài"
    r = client.post(
        f"/api/so-truc/{_NGAY}/forward-ksv",
        json={"gdv1_id": KSV, "gdv2_id": GDV2, "ghi_chu": "", "ksv_id": KSV, "truc_phu_ids": []},
    )
    assert r.status_code == 400
    assert "không thể tự xác nhận" in r.json()["detail"].lower()


def test_forward_ksv_ksv_khac_gdv_van_binh_thuong(client, db):
    """Đối chứng — KSV khác cả 2 GDV thì không bị chặn bởi ràng buộc mới."""
    _dang_nhap(GDV1)
    r = client.post(
        f"/api/so-truc/{_NGAY}/forward-ksv",
        json={"gdv1_id": GDV1, "gdv2_id": GDV2, "ghi_chu": "", "ksv_id": KSV, "truc_phu_ids": []},
    )
    assert r.status_code == 200


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
