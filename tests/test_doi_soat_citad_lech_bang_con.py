# -*- coding: utf-8 -*-
"""Lệnh lệch của Đối soát CITAD lưu ở bảng con, không nhồi vào một ô JSON.

Canh ba thứ dễ hỏng âm thầm khi tách bảng:
  1. Bản ghi đọc lại phải GIỐNG HỆT lúc lưu — kể cả khoá tuỳ chọn vắng mặt.
     Bản ghi lệch dựng bằng `{**r, ...}` nên bộ khoá theo dòng nguồn: đếm trên
     dữ liệu thật có 4 bộ khoá khác nhau, `cong`/`ghi_chu` lúc có lúc không.
  2. Khoá LẠ (parser tương lai thêm field) không được rơi mất — `extra_json`.
  3. Phân trang phải cắt đúng dải, không trả thừa và không bỏ sót.
"""
import sqlite3

import pytest

from backend.services.doi_soat_citad.history_service import (
    canh_bao_lech_bat_thuong, get_recon_detail, iter_lech, list_recon_history,
    save_recon_history,
)


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE user_tttt (id INTEGER PRIMARY KEY, full_name TEXT);
        CREATE TABLE doi_soat_citad_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ngay_cham VARCHAR(10) NOT NULL, recon_date DATETIME NOT NULL,
            performed_by_id INTEGER, citad_file_names TEXT, ipcas_file_names TEXT,
            hub_file_names TEXT, total_citad INTEGER, total_ipcas INTEGER,
            total_hub INTEGER, n_khop INTEGER, n_lech INTEGER,
            lech_json TEXT, created_at DATETIME);
        CREATE TABLE doi_soat_citad_lech (
            history_id INTEGER NOT NULL, seq INTEGER NOT NULL,
            so_gd TEXT, dich_vu TEXT, loai TEXT, chieu TEXT, loai_tien TEXT,
            so_tien INTEGER, ngay TEXT, status TEXT, key_agri TEXT,
            nh_nhan TEXT, trang_thai TEXT, cong TEXT, ghi_chu TEXT,
            extra_json TEXT, PRIMARY KEY (history_id, seq)) WITHOUT ROWID;
        """
    )
    yield conn
    conn.close()


def _luu(db, lech_rows):
    return save_recon_history(
        db, ngay_cham="09/09/2026", performed_by_id=None,
        citad_file_names=["a.txt"], ipcas_file_names=[], hub_file_names=[],
        total_citad=10, total_ipcas=10, total_hub=0,
        n_khop=1, lech_rows=lech_rows,
    )


def _ban_ghi(i, **them):
    r = {
        "so_gd": f"GD{i:05d}", "dich_vu": "CITAD", "loai": "di", "chieu": "di",
        "loai_tien": "VND", "so_tien": 1000 + i, "ngay": "09/09/2026",
        "status": "only_citad", "key_agri": "", "nh_nhan": "", "trang_thai": "",
    }
    r.update(them)
    return r


# ── 1. Đọc lại phải giống hệt lúc lưu ────────────────────────────────────────
def test_ban_ghi_doc_lai_giong_het_luc_luu(db):
    goc = [
        _ban_ghi(1),                                  # không có cong/ghi_chu
        _ban_ghi(2, cong="+"),                        # có cong
        _ban_ghi(3, cong="-", ghi_chu="trùng khoá"),  # có cả hai
    ]
    hid = _luu(db, goc)
    doc = get_recon_detail(db, hid, 0, 100)["lech_records"]
    assert doc == goc


def test_khoa_vang_mat_khong_bi_bia_them(db):
    """Cột NULL nghĩa là bản gốc KHÔNG có khoá đó — trả kèm None là bịa field
    mà bản đã ký không có, Excel xuất ra sẽ khác bản audit."""
    hid = _luu(db, [_ban_ghi(1)])
    rec = get_recon_detail(db, hid, 0, 100)["lech_records"][0]
    assert "cong" not in rec
    assert "ghi_chu" not in rec


def test_khoa_la_khong_roi_mat(db):
    """Parser tương lai thêm field → phải đi vào extra_json, không biến mất."""
    goc = [_ban_ghi(1, field_moi_toanh="giá trị", so_hieu=42)]
    hid = _luu(db, goc)
    assert get_recon_detail(db, hid, 0, 100)["lech_records"] == goc


# ── 2. Không còn ghi vào lech_json ───────────────────────────────────────────
def test_khong_con_ghi_vao_lech_json(db):
    hid = _luu(db, [_ban_ghi(i) for i in range(5)])
    assert db.execute(
        "SELECT lech_json FROM doi_soat_citad_history WHERE id=?", (hid,)
    ).fetchone()[0] is None
    assert db.execute(
        "SELECT COUNT(*) FROM doi_soat_citad_lech WHERE history_id=?", (hid,)
    ).fetchone()[0] == 5


# ── 3. Phân trang ────────────────────────────────────────────────────────────
def test_phan_trang_cat_dung_dai_va_du_dong(db):
    goc = [_ban_ghi(i) for i in range(250)]
    hid = _luu(db, goc)

    t1 = get_recon_detail(db, hid, 0, 200)
    assert t1["lech_records"] == goc[:200]
    assert t1["lech_total"] == 250 and t1["lech_offset"] == 0

    t2 = get_recon_detail(db, hid, 200, 200)
    assert t2["lech_records"] == goc[200:]     # trang cuối chỉ còn 50
    assert t2["lech_total"] == 250

    # Ghép các trang lại phải ra đúng bản gốc, không sót không lặp
    ghep = []
    for off in range(0, 250, 50):
        ghep += get_recon_detail(db, hid, off, 50)["lech_records"]
    assert ghep == goc


def test_offset_vuot_qua_cuoi_tra_rong_khong_no(db):
    hid = _luu(db, [_ban_ghi(i) for i in range(10)])
    d = get_recon_detail(db, hid, 999, 50)
    assert d["lech_records"] == [] and d["lech_total"] == 10


def test_thu_tu_giu_nguyen_theo_seq(db):
    """Thứ tự là dữ liệu: Excel audit phải ra đúng thứ tự lúc đối soát."""
    goc = [_ban_ghi(i, so_gd=f"Z{999 - i:05d}") for i in range(120)]
    hid = _luu(db, goc)
    assert get_recon_detail(db, hid, 0, 500)["lech_records"] == goc


# ── 4. Đường xuất Excel: duyệt theo lô ───────────────────────────────────────
def test_iter_lech_duyet_du_va_dung_thu_tu(db):
    goc = [_ban_ghi(i) for i in range(4500)]
    hid = _luu(db, goc)
    assert list(iter_lech(db, hid, lo=1000)) == goc


def test_limit_none_lay_het(db):
    goc = [_ban_ghi(i) for i in range(300)]
    hid = _luu(db, goc)
    assert get_recon_detail(db, hid, 0, None)["lech_records"] == goc


# ── 5. Danh sách lịch sử vẫn nhẹ ─────────────────────────────────────────────
def test_danh_sach_lich_su_khong_keo_theo_lenh_lech(db):
    _luu(db, [_ban_ghi(i) for i in range(1000)])
    rows = list_recon_history(db, limit=10)
    assert len(rows) == 1
    assert "lech_records" not in rows[0] and "lech_json" not in rows[0]
    assert rows[0]["n_lech"] == 1000


def test_khong_tim_thay_tra_none(db):
    assert get_recon_detail(db, 12345) is None


# ── 6. Cảnh báo lượt đối soát bất thường ─────────────────────────────────────
def test_luot_binh_thuong_khong_canh_bao():
    """Số thật đo trên máy chủ: các lượt bình thường lệch 6, 14, 15, 39 lệnh."""
    for n_lech in (6, 14, 15, 39, 121, 999):
        assert canh_bao_lech_bat_thuong(n_lech, 5000, 5000, 0) is None


def test_luot_ghep_nham_file_bi_canh_bao():
    """Số thật: các lượt hỏng có 22 202 / 60 542 / 75 921 / 93 781 lệnh lệch."""
    for n_lech in (22202, 60542, 75921, 93781):
        cb = canh_bao_lech_bat_thuong(n_lech, n_lech, n_lech, 0)
        assert cb and "KHÔNG cùng một ngày" in cb


def test_ngay_it_giao_dich_khong_bi_keu_oan():
    """Lệch 2/3 lệnh là 67% nhưng hoàn toàn bình thường — không có ngưỡng số
    tuyệt đối thì cảnh báo kêu suốt và người dùng học cách bỏ qua nó."""
    assert canh_bao_lech_bat_thuong(2, 3, 3, 0) is None


def test_nhieu_lech_nhung_ty_le_thap_khong_canh_bao():
    """1 500 lệch trên 100 000 giao dịch — nhiều nhưng chỉ 1,5%, là nghiệp vụ."""
    assert canh_bao_lech_bat_thuong(1500, 100000, 100000, 0) is None


def test_tong_bang_khong_khong_no():
    assert canh_bao_lech_bat_thuong(5000, 0, 0, 0) is None
