"""`data/temp_*` phình mãi trên máy chủ — ba tính năng không nằm trong lịch dọn 23h.

ILO1000 và hai chiều Song phương kênh core chỉ tự dọn khi có job vừa xong, và chỉ xoá
job còn nhớ trong RAM. Restart backend là RAM trống → thư mục của mọi job trước đó
không bao giờ bị xoá nữa. Không lỗi, không log — chỉ có ổ đĩa đầy dần.

Chạy: .venv/Scripts/python.exe -m pytest tests/test_don_temp_du_nguon.py -v
"""
import os
import re
import sys
from pathlib import Path

import pytest

from backend.core.don_dep import moc_don_gan_nhat
from backend.services import temp_cleanup_service

GOC = Path(__file__).resolve().parents[1]


def _lui(d: Path, giay: float) -> None:
    t = moc_don_gan_nhat() - giay
    os.utime(d, (t, t))


# ── Mọi thư mục temp_* đều có người dọn ──────────────────────────────────────

def test_moi_thu_muc_temp_trong_ma_deu_nam_trong_lich_don():
    """Thêm tính năng mới có `data/temp_xxx` mà quên khai vào `_nguon_don()` là đỏ."""
    trong_ma = set()
    for f in (GOC / "backend").rglob("*.py"):
        trong_ma |= set(re.findall(r"""["'](?:data/)?(temp_[a-z0-9_]+)["']""",
                                   f.read_text(encoding="utf-8")))
    duoc_don = {
        Path(sys.modules[ham.__module__].TEMP_DIR).name
        for _, ham in temp_cleanup_service._nguon_don()
    }
    # Mốc tối thiểu 24/09/2026: regex mà hụt (ai đổi cách khai TEMP_DIR) thì tập rỗng dần
    # và phép `<=` bên dưới vẫn xanh — chặn bằng số lượng đã biết.
    assert len(trong_ma) >= 10, f"regex chỉ bắt được {sorted(trong_ma)} — kiểm lại cách khai TEMP_DIR"
    assert trong_ma <= duoc_don, f"Thiếu trong lịch dọn 23h: {sorted(trong_ma - duoc_don)}"


# ── Ba service trước đây chỉ dọn theo RAM ────────────────────────────────────

@pytest.mark.parametrize("ten_module", [
    "backend.services.ilo1000_service",
    "backend.services.doi_chieu_song_phuong_kenh_core_service",
    "backend.services.doi_chieu_song_phuong_kenh_core_di_service",
])
def test_don_thu_muc_mo_coi_sau_restart_giu_job_con_song(ten_module, tmp_path, monkeypatch):
    import importlib
    svc = importlib.import_module(ten_module)
    monkeypatch.setattr(svc, "TEMP_DIR", tmp_path)
    monkeypatch.setattr(svc, "_jobs", {})

    mo_coi = tmp_path / "job_truoc_restart"      # RAM không còn nhớ
    hom_nay = tmp_path / "job_sang_nay"
    dang_chay = tmp_path / "job_dang_chay"
    for d in (mo_coi, hom_nay, dang_chay):
        d.mkdir()
        (d / "ket_qua.xlsx").write_bytes(b"x")
    _lui(mo_coi, 3600)
    _lui(dang_chay, 3600)                         # cũ nhưng job còn sống → giữ
    svc._jobs["job_dang_chay"] = {"status": "running", "_ts": 0}

    svc._cleanup_old_jobs(moc_don_gan_nhat())

    assert not mo_coi.exists()
    assert hom_nay.exists(), "file trong ngày KHÔNG được đụng tới"
    assert dang_chay.exists(), "thư mục của job đang chạy KHÔNG được xoá"


def test_lich_don_goi_ca_ba_service_moi(tmp_path, monkeypatch):
    """Đi qua đúng `run_cleanup()` của lịch 23h, không gọi thẳng từng service.

    Vá `TEMP_DIR` của ĐỦ mọi nguồn, không riêng ba service đang xét: `run_cleanup()` gọi cả
    mười hàm dọn, quên vá cái nào là test xoá `data/temp_*` THẬT của máy chạy test.
    """
    from backend.services import (
        doi_chieu_song_phuong_kenh_core_di_service as kc_di,
        doi_chieu_song_phuong_kenh_core_service as kc_den,
        ilo1000_service,
    )
    for i, (_, ham) in enumerate(temp_cleanup_service._nguon_don()):
        monkeypatch.setattr(sys.modules[ham.__module__], "TEMP_DIR", tmp_path / f"khac{i}")
    cu = []
    for i, svc in enumerate((ilo1000_service, kc_den, kc_di)):
        thu_muc = tmp_path / f"s{i}"
        (thu_muc / "job_cu").mkdir(parents=True)
        _lui(thu_muc / "job_cu", 3600)
        monkeypatch.setattr(svc, "TEMP_DIR", thu_muc)
        monkeypatch.setattr(svc, "_jobs", {})
        cu.append(thu_muc / "job_cu")

    temp_cleanup_service.run_cleanup(moc_don_gan_nhat())

    assert not any(d.exists() for d in cu)


# ── Chuẩn hoá văn bản: giữ phiên VB_FORMAT_LUU_NGAY ngày ─────────────────────

def test_phien_chuan_hoa_giu_du_so_ngay(tmp_path, monkeypatch):
    from backend.api import vb_format as vb_api
    from backend.core.config import settings
    monkeypatch.setattr(vb_api, "TEMP_DIR", tmp_path)
    monkeypatch.setattr(settings, "VB_FORMAT_LUU_NGAY", 30)

    moi = tmp_path / "phien_28_ngay"
    cu = tmp_path / "phien_30_ngay"
    for d in (moi, cu):
        d.mkdir()
    _lui(moi, 28 * 86400)            # còn trong hạn 30 ngày
    _lui(cu, 29 * 86400 + 60)        # vừa qua hạn

    vb_api._don_file_cu(moc_don_gan_nhat())

    assert moi.exists()
    assert not cu.exists()


def test_luu_1_ngay_la_hanh_vi_cu_don_luc_23h(tmp_path, monkeypatch):
    from backend.api import vb_format as vb_api
    from backend.core.config import settings
    monkeypatch.setattr(vb_api, "TEMP_DIR", tmp_path)
    monkeypatch.setattr(settings, "VB_FORMAT_LUU_NGAY", 1)

    hom_qua = tmp_path / "hom_qua"
    hom_nay = tmp_path / "hom_nay"
    for d in (hom_qua, hom_nay):
        d.mkdir()
    _lui(hom_qua, 60)

    vb_api._don_file_cu(moc_don_gan_nhat())

    assert not hom_qua.exists()
    assert hom_nay.exists()
