"""Chống tràn RAM khi nhiều đối chiếu chạy cùng lúc — card 156.

Hai lớp:
  - Xét RAM ƯỚC TÍNH trước khi cho chạy (`phien_doi_chieu.kiem_tra`, ngân sách 11,5 GB).
  - Trần CỨNG bộ nhớ cam kết cho mọi tiến trình con cộng lại (`tien_trinh_doi_chieu`,
    Windows Job Object, 13 GB) — ước tính sai thì lượt đang xin thêm nhận lỗi rõ ràng,
    backend và Windows không bị kéo theo.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_tran_ram_doi_chieu.py -v
"""
import os

import pytest

from backend.core import phien_doi_chieu as pdc
from backend.core import tien_trinh_doi_chieu as ttdc


# ── Lớp 2: xét RAM ước tính ──

@pytest.fixture
def nguon(monkeypatch):
    """Sổ khai nguồn riêng cho test, ước tính đúng số người dùng chốt 21/09/2026."""
    goc = dict(pdc._NGUON)
    pdc._NGUON.clear()
    monkeypatch.setattr(pdc, "RAM_UOC_TINH", dict(pdc._RAM_UOC_TINH_MAC_DINH))
    monkeypatch.setattr(pdc, "NGAN_SACH_RAM_GB", 11.5)
    monkeypatch.setattr(pdc, "MAX_SONG_SONG", 3)

    def _khai(ma, ten, dang_chay):
        job = {"job_id": ma, "status": "running", "tuoi_giay": 60} if dang_chay else None
        pdc.dang_ky_nguon(ma, ten, lambda: job)

    yield _khai
    pdc._NGUON.clear()
    pdc._NGUON.update(goc)


def test_so_uoc_tinh_dung_so_nguoi_dung_chot():
    assert pdc._RAM_UOC_TINH_MAC_DINH == {
        "ach": 4.5, "song_phuong_kenh_core_di": 4.0, "song_phuong": 3.0, "song_phuong_di": 2.0,
    }


def test_ngan_sach_mac_dinh_11_5_vua_ach_di_den():
    # Người dùng chốt 21/09/2026: 11,5 = 4,5 + 4 + 3 — đổi số này là đổi quyết định đó
    assert pdc.NGAN_SACH_RAM_GB == 11.5


def test_ach_di_den_cung_luc_duoc_chay(nguon):
    nguon("ach", "ACH", True)                                   # 4,5
    nguon("song_phuong_kenh_core_di", "ĐI", True)               # 4
    nguon("song_phuong", "ĐẾN", False)                          # 3 → đúng 11,5: không VƯỢT
    assert pdc.kiem_tra("song_phuong") is None


def test_vuot_ngan_sach_thi_chan_va_noi_ro(nguon, monkeypatch):
    # 4 module đã có số không còn tổ hợp 3 lượt nào vượt 11,5 — ca chặn thật sẽ đến khi
    # khai ước tính cho module chưa đo (ở đây giả định 459901 = 3,5 GB)
    monkeypatch.setitem(pdc.RAM_UOC_TINH, "cham459901", 3.5)
    nguon("ach", "Đối chiếu ACH", True)                          # 4,5
    nguon("song_phuong_kenh_core_di", "Song phương ĐI", True)   # 4
    nguon("cham459901", "Chấm 459901", False)                   # 3,5 → 12 > 11,5
    nghen = pdc.kiem_tra("cham459901")
    assert nghen is not None
    assert "Chấm 459901" in nghen["message"] and "~3,5 GB" in nghen["message"]
    assert "Đối chiếu ACH ~4,5 GB" in nghen["message"] and "11,5 GB" in nghen["message"]


def test_duoi_ngan_sach_thi_cho_chay(nguon):
    nguon("ach", "ACH", True)
    nguon("song_phuong_kenh_core_di", "ĐI", True)
    nguon("song_phuong_di", "Phân loại", False)                 # 4,5 + 4 + 2 = 10,5
    assert pdc.kiem_tra("song_phuong_di") is None


def test_module_chua_co_so_do_khong_xet_ram(nguon):
    # ILO1000/459901/OSB chưa đo — chỉ còn trần số lượt + trần cứng
    nguon("ach", "ACH", True)
    nguon("song_phuong_kenh_core_di", "ĐI", True)
    nguon("ilo1000", "ILO1000", False)
    assert pdc.kiem_tra("ilo1000") is None


def test_module_chua_co_so_dang_chay_tinh_bang_0(nguon):
    nguon("ilo1000", "ILO1000", True)
    nguon("cham459901", "459901", True)
    nguon("ach", "ACH", False)
    assert pdc.kiem_tra("ach") is None


def test_mot_minh_vuot_ngan_sach_van_cho_chay(nguon, monkeypatch):
    # Đặt ngân sách thấp không được khoá chết cả module khi máy đang rảnh
    monkeypatch.setattr(pdc, "NGAN_SACH_RAM_GB", 3.0)
    nguon("ach", "ACH", False)
    assert pdc.kiem_tra("ach") is None


def test_ach_cho_xac_nhan_khong_tinh_ram(nguon):
    # Chờ xác nhận MIS_đi: không còn tiến trình con — cộng 4,5 GB là chặn oan tới 4 giờ.
    # Vẫn tính cho luật cùng module và trần số lượt (không đổi hành vi cũ).
    pdc.dang_ky_nguon("ach", "ACH", lambda: {"job_id": "a", "status": "awaiting_confirmation"})
    nguon("song_phuong_kenh_core_di", "ĐI", True)
    nguon("song_phuong", "ĐẾN", False)                          # 4 + 3 = 7 (không tính ACH)
    assert pdc.kiem_tra("song_phuong") is None


def test_dang_chay_toan_module_chua_co_so_thi_khong_xet_ngan_sach(nguon, monkeypatch):
    # Ngân sách đặt thấp hơn ước tính 1 module, đang chạy toàn module chưa có số → 0 GB đang
    # dùng, không được chặn (và không ra câu báo danh sách rỗng)
    monkeypatch.setattr(pdc, "NGAN_SACH_RAM_GB", 3.0)
    nguon("ilo1000", "ILO1000", True)
    nguon("ach", "ACH", False)
    assert pdc.kiem_tra("ach") is None


def test_tran_so_luot_van_giu(nguon):
    # Xét RAM không thay trần số lượt: 3 lượt nhỏ (chưa có số) vẫn bị chặn
    for ma in ("ilo1000", "cham459901", "doi_chieu_osb"):
        nguon(ma, ma, True)
    nguon("song_phuong_di", "Phân loại", False)
    assert "giới hạn 3" in pdc.kiem_tra("song_phuong_di")["message"]


def test_doc_uoc_tinh_tu_env(monkeypatch, caplog):
    monkeypatch.setenv("DOI_CHIEU_RAM_UOC_TINH", "ilo1000=3.5, sai ,cham459901=abc,doi_chieu_osb=-1,ach=5")
    ra = pdc._doc_uoc_tinh()
    assert ra["ilo1000"] == 3.5 and ra["ach"] == 5.0                  # thêm mới + ghi đè
    assert "cham459901" not in ra and "doi_chieu_osb" not in ra       # sai → bỏ qua
    assert ra["song_phuong"] == 3.0                                   # mặc định giữ nguyên
    assert pdc._doc_gb("11,5", "x") == 11.5                           # dấu phẩy thập phân ở ô đơn


# ── Lớp 1: trần cứng (tiến trình con thật) ──

def _ham_xin_ram(mb, log_callback, cancel_event):
    import numpy as np
    a = np.ones(mb * 2**20, dtype=np.uint8)
    return int(a[-1])


def _ham_boc_loi_bo_nho(mb, log_callback, cancel_event):
    # Đúng kiểu 459901/Song phương/ACH: bắt Exception quanh bước đọc lớn rồi đổi thành
    # "file hỏng" — MemoryError gốc chỉ còn trong vết lỗi
    try:
        return _ham_xin_ram(mb, log_callback, cancel_event)
    except Exception as e:
        raise ValueError(f"file không đọc được như Excel ({e})") from e


@pytest.fixture
def tran(monkeypatch, tien_trinh_that):
    """Nhóm Job Object mới cho mỗi test (nhóm chung được tạo một lần/đời backend)."""
    def _dat(gb: str):
        monkeypatch.setattr(ttdc, "_nhom", None)
        monkeypatch.setenv("DOI_CHIEU_RAM_TRAN_GB", gb)
    yield _dat


@pytest.mark.skipif(os.name != "nt", reason="Job Object chỉ có trên Windows")
def test_vuot_tran_cung_thi_bao_ro_khong_phai_loi_rong(tran):
    tran("0.4")
    with pytest.raises(ttdc.LoiTienTrinhCon, match="vượt bộ nhớ dành cho đối chiếu") as ei:
        ttdc.chay_tach(_ham_xin_ram, ten="thử", mb=800)
    assert "0,4 GB" in str(ei.value)
    # Dưới trần thì chạy bình thường — cùng nhóm, cùng trần
    assert ttdc.chay_tach(_ham_xin_ram, ten="thử", mb=100) == 1


@pytest.mark.skipif(os.name != "nt", reason="Job Object chỉ có trên Windows")
def test_het_bo_nho_bi_pipeline_boc_lai_van_bao_ro(tran):
    # Phản biện 21/09: không nhận ra thì người dùng đi kiểm tra file thay vì chờ lượt khác
    tran("0.4")
    with pytest.raises(ttdc.LoiTienTrinhCon, match="vượt bộ nhớ dành cho đối chiếu"):
        ttdc.chay_tach(_ham_boc_loi_bo_nho, ten="thử", mb=800)


@pytest.mark.skipif(os.name != "nt", reason="Job Object chỉ có trên Windows")
def test_tat_tran_thi_khong_chan(tran):
    # Cặp với test trên: cùng 800 MB mà tắt trần thì chạy được — lỗi ở trên là do TRẦN
    tran("0")
    assert ttdc.chay_tach(_ham_xin_ram, ten="thử", mb=800) == 1


def test_doc_tran_tu_env(monkeypatch):
    monkeypatch.setenv("DOI_CHIEU_RAM_TRAN_GB", "")
    assert ttdc.tran_ram_gb() == 13.0
    monkeypatch.setenv("DOI_CHIEU_RAM_TRAN_GB", "12,5")
    assert ttdc.tran_ram_gb() == 12.5
    monkeypatch.setenv("DOI_CHIEU_RAM_TRAN_GB", "abc")
    assert ttdc.tran_ram_gb() == 13.0
