"""
Test module Đối chiếu CITAD - PaymentHub (Phòng QLTK Nostro, Vostro).

Viết sau review PR #57: 2182 dòng thêm mà 0 test, trong đó có 1 blocker thật
(`get_reconciliation_days` gọi thẳng `datetime.strptime` trên chuỗi người
dùng GÕ TAY → ValueError → 500 làm sập tab Lịch sử). Mỗi test dưới đây gắn
với đúng một lỗi đã sửa, để không tái diễn.

Test ở tầng service với SQLite in-memory (không chạy migrations thật, không
dựng TestClient) — logic cần canh là công thức + parse ngày + quy tắc
created_by, không dính RBAC.
"""
import json
import sqlite3

import pytest

from backend.services import doi_chieu_citad_nostro_service as svc

_SCHEMA = """
CREATE TABLE user_tttt (id INTEGER PRIMARY KEY, username TEXT, full_name TEXT);
CREATE TABLE doi_chieu_citad_nostro_sessions (
    ky         TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    updated_at DATETIME,
    updated_by INTEGER,
    created_by INTEGER
);
CREATE TABLE doi_chieu_citad_nostro_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ky         TEXT NOT NULL,
    staff_id   INTEGER NOT NULL,
    data       TEXT NOT NULL,
    created_at DATETIME NOT NULL
);
INSERT INTO user_tttt (id, username, full_name) VALUES
    (1, 'anlv', 'Lê Văn An'),
    (2, 'binhpt', 'Phạm Thị Bình');
"""


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    yield conn
    conn.close()


def _sess(ky):
    return {"ky": ky, "lap_bang": "", "kiem_soat": "", "cD": {}, "phD": {}}


# ══════════════════════════════════════════════════════════════
# Lọc lịch sử — ngày do người dùng gõ tay, sai định dạng KHÔNG được sập
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("xau", ["2026-08-01", "01/08", "", "hôm qua", "32/13/2026"])
def test_loc_ngay_sai_dinh_dang_khong_sap(db, xau):
    """Blocker PR #57: ô lọc "Từ ngày"/"Đến ngày" là input gõ tự do, gõ dở
    rồi bấm Tìm thì `strptime` ném ValueError → 500. Phải trả danh sách
    bình thường (coi như không lọc), không ném."""
    svc.session_save(db, "01/08/2026-05/08/2026", 1, _sess("01/08/2026-05/08/2026"))
    assert svc.get_reconciliation_days(db, tu_ngay=xau) is not None
    assert svc.get_reconciliation_days(db, den_ngay=xau) is not None


def test_loc_ngay_dung_dinh_dang_van_loc_that(db):
    for ky in ("01/07/2026-05/07/2026", "01/08/2026-05/08/2026"):
        svc.session_save(db, ky, 1, _sess(ky))
    ket_qua = svc.get_reconciliation_days(db, tu_ngay="15/07/2026")
    assert [r["ky"] for r in ket_qua] == ["01/08/2026-05/08/2026"]


def test_sap_xep_theo_thoi_gian_khong_theo_chuoi(db):
    """"01/12/2026" < "05/01/2027" theo chuỗi nhưng đến TRƯỚC theo thời gian."""
    for ky in ("01/12/2026-05/12/2026", "05/01/2027-06/01/2027"):
        svc.session_save(db, ky, 1, _sess(ky))
    assert [r["ky"] for r in svc.get_reconciliation_days(db)][0] == "05/01/2027-06/01/2027"
    assert [s["ky"] for s in svc.session_list(db)][0] == "05/01/2027-06/01/2027"


# ══════════════════════════════════════════════════════════════
# Người lập bảng cố định, không đổi theo người lưu sau cùng
# ══════════════════════════════════════════════════════════════

def test_nguoi_lap_bang_khong_bi_nguoi_luu_sau_chiem_cho(db):
    ky = "01/08/2026-05/08/2026"
    svc.session_save(db, ky, 1, _sess(ky))          # An lập bảng
    svc.session_save(db, ky, 2, _sess(ky))          # Bình lưu đè

    dong = svc.get_reconciliation_days(db)[0]
    assert dong["created_by_username"] == "anlv"    # vẫn là người lập bảng
    assert dong["so_lan_luu"] == 2                  # lịch sử ghi đủ cả 2 lượt

    row = db.execute("SELECT updated_by FROM doi_chieu_citad_nostro_sessions WHERE ky=?", (ky,)).fetchone()
    assert row["updated_by"] == 2                   # người lưu sau cùng là Bình


def test_loc_theo_ten_nguoi_cham_khop_ca_username_lan_ho_ten(db):
    ky = "01/08/2026-05/08/2026"
    svc.session_save(db, ky, 1, _sess(ky))
    assert len(svc.get_reconciliation_days(db, nguoi_cham="anlv")) == 1
    assert len(svc.get_reconciliation_days(db, nguoi_cham="văn an")) == 1
    assert len(svc.get_reconciliation_days(db, nguoi_cham="binhpt")) == 0


# ══════════════════════════════════════════════════════════════
# Kỳ đối chiếu — không cho lưu kỳ rỗng/sai (bản ghi vô hình, không xoá được)
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("ky_hong", ["-", "", "01/08/2026", "abc-xyz", "01/08/2026-"])
def test_ky_hong_bi_tu_choi(ky_hong):
    with pytest.raises(ValueError):
        svc.normalize_ky(ky_hong)


def test_ky_dao_nguoc_duoc_chuan_hoa_ve_mot_dang():
    assert svc.normalize_ky("05/08/2026-01/08/2026") == "01/08/2026-05/08/2026"
    assert svc.normalize_ky("01/08/2026-01/08/2026") == "01/08/2026-01/08/2026"


# ══════════════════════════════════════════════════════════════
# Cảnh báo chồng ngày / hở ngày giữa các kỳ
# ══════════════════════════════════════════════════════════════

def test_bao_chong_ngay_va_ho_ngay(db):
    svc.session_save(db, "01/08/2026-05/08/2026", 1, _sess("01/08/2026-05/08/2026"))

    chong = svc.check_period_overlap(db, "04/08/2026", "08/08/2026")
    assert chong["overlaps"] == ["01/08/2026-05/08/2026"]

    ho = svc.check_period_overlap(db, "09/08/2026", "12/08/2026")
    assert ho["overlaps"] == []
    assert ho["gap_before"] == {"tu_ngay": "06/08/2026", "den_ngay": "08/08/2026", "so_ngay": 3}

    ke_tiep = svc.check_period_overlap(db, "06/08/2026", "10/08/2026")
    assert ke_tiep["gap_before"] is None

    # Lưu đè đúng kỳ đang sửa thì không tự báo trùng với chính nó
    tu_bao = svc.check_period_overlap(db, "01/08/2026", "05/08/2026", exclude_ky="01/08/2026-05/08/2026")
    assert tu_bao["overlaps"] == []


# ══════════════════════════════════════════════════════════════
# Công thức đối chiếu
# ══════════════════════════════════════════════════════════════

def test_tong_citad_cong_du_5_cong_va_tong_hub_gop_2_khung_gio():
    sess = {
        "cD": {c: {"gtt": {"soMon": 10, "soTien": 1_000_000},
                   "gtc": {"soMon": 2, "soTien": 5_000_000}} for c in svc.CONGS},
        "phD": {"gtt":       {"soMon": 50, "soTien": 5_000_000},
                "gtc_truoc": {"soMon": 6,  "soTien": 15_000_000},
                "gtc_tu":    {"soMon": 4,  "soTien": 10_000_000}},
    }
    ci, hub = svc.compute_totals(sess)
    assert (ci["gtt"]["soMon"], ci["gtt"]["soTien"]) == (50, 5_000_000)
    assert (ci["gtc"]["soMon"], ci["gtc"]["soTien"]) == (10, 25_000_000)
    assert (hub["gtt"]["soMon"], hub["gtt"]["soTien"]) == (50, 5_000_000)
    assert (hub["gtc"]["soMon"], hub["gtc"]["soTien"]) == (10, 25_000_000)
    assert svc.is_reconciliation_matched(sess) is True


def test_lech_mot_mon_thi_bao_khong_khop():
    sess = {
        "cD": {c: {"gtt": {"soMon": 10, "soTien": 0}, "gtc": {"soMon": 0, "soTien": 0}} for c in svc.CONGS},
        "phD": {"gtt": {"soMon": 49, "soTien": 0}, "gtc_truoc": {}, "gtc_tu": {}},
    }
    assert svc.is_reconciliation_matched(sess) is False


def test_o_trong_va_chuoi_rong_tinh_la_0_khong_ne_ngoai_le():
    sess = {"cD": {"1": {"gtt": {"soMon": "", "soTien": None}}}, "phD": {}}
    ci, hub = svc.compute_totals(sess)
    assert ci["gtt"] == {"soMon": 0.0, "soTien": 0.0}
    assert hub["gtc"] == {"soMon": 0.0, "soTien": 0.0}
