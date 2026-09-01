"""Chính sách file tạm: ghi thẳng ra folder máy chủ, 23h hằng ngày xoá sạch.

Hai thứ đáng canh, vì cả hai đều hỏng theo kiểu KHÔNG có lỗi nào:

1. Mốc dọn. Nếu ranh giới trượt vào trong ngày đang chạy thì `_cleanup_old_*()`
   — vốn được gọi ngay giữa request — sẽ xoá kết quả của phiên vừa chạy sáng
   nay. Người dùng bấm tải về và nhận 404, không hiểu vì sao.

2. Chỗ trả lại khi upload hỏng. Job ACH được đăng ký TRƯỚC khi nhận byte đầu
   tiên (để chặn hai lượt upload lớn cùng lúc); quên `bo_job()` ở đường lỗi là
   một job 'pending' ma khoá chết tính năng cho tới khi hết CLEANUP_TTL.

Chạy: .venv/Scripts/python.exe -m pytest tests/test_don_file_tam_23h.py -v
"""
import io
import time
from datetime import datetime

import pytest

from backend.core.don_dep import GIO_DON, giay_toi_moc_ke_tiep, moc_don_gan_nhat
from backend.services import ach_service


def _luc(chuoi: str) -> float:
    return datetime.strptime(chuoi, "%Y-%m-%d %H:%M").timestamp()


# ── Mốc dọn ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bay_gio, moc_mong_doi", [
    ("2026-08-27 00:01", "2026-08-26 23:00"),   # ngay sau nửa đêm — mốc là tối qua
    ("2026-08-27 09:15", "2026-08-26 23:00"),   # giữa buổi làm
    ("2026-08-27 22:59", "2026-08-26 23:00"),   # sát giờ dọn, chưa tới
    ("2026-08-27 23:00", "2026-08-27 23:00"),   # đúng giờ dọn
    ("2026-08-27 23:30", "2026-08-27 23:00"),
])
def test_moc_luon_la_23h_gan_nhat_da_troi_qua(bay_gio, moc_mong_doi):
    assert moc_don_gan_nhat(_luc(bay_gio)) == _luc(moc_mong_doi)


def test_moc_khong_bao_gio_roi_vao_trong_ngay_dang_chay():
    """Điều kiện sống còn: hàm dọn được gọi giữa request, mốc mà trượt lên sau
    lúc file được tạo là xoá mất kết quả người ta vừa chạy."""
    tao_file_luc = _luc("2026-08-27 08:00")
    for gio in ("2026-08-27 08:01", "2026-08-27 13:00", "2026-08-27 22:59"):
        assert moc_don_gan_nhat(_luc(gio)) < tao_file_luc


def test_giay_toi_moc_ke_tiep_luon_duong_va_khop_gio_don():
    for gio in ("2026-08-27 00:01", "2026-08-27 22:59", "2026-08-27 23:00"):
        con_lai = giay_toi_moc_ke_tiep(_luc(gio))
        assert 0 < con_lai <= 24 * 3600
        assert datetime.fromtimestamp(_luc(gio) + con_lai).hour == GIO_DON


# ── Dọn thật trên đĩa ────────────────────────────────────────────────────────

def test_don_xoa_thu_muc_hom_qua_giu_thu_muc_hom_nay(tmp_path, monkeypatch):
    monkeypatch.setattr(ach_service, "TEMP_DIR", tmp_path)
    cutoff = moc_don_gan_nhat()

    hom_qua = tmp_path / "job_cu"
    hom_nay = tmp_path / "job_moi"
    for d in (hom_qua, hom_nay):
        d.mkdir()
        (d / "input.zip").write_bytes(b"x")
    import os
    os.utime(hom_qua, (cutoff - 3600, cutoff - 3600))

    ach_service._cleanup_old_jobs(cutoff)

    assert not hom_qua.exists(), "thư mục của ngày trước phải bị dọn"
    assert hom_nay.exists(), "file trong ngày KHÔNG được đụng tới"


# ── Upload ACH ghi thẳng ra folder máy chủ ───────────────────────────────────

def _file(ten: str, noi_dung: bytes):
    return ("files", (ten, io.BytesIO(noi_dung), "application/octet-stream"))


def test_upload_ghi_vao_thu_muc_job_va_chay_pipeline(admin_client, tmp_path, monkeypatch):
    """Đường đi thật: byte của client phải nằm trong `<job>/input` trên đĩa."""
    monkeypatch.setattr(ach_service, "TEMP_DIR", tmp_path)
    da_chay = {}
    monkeypatch.setattr(ach_service, "chay_job",
                        lambda job_id, ngay, **kw: da_chay.update(job_id=job_id, ngay=ngay))

    r = admin_client.post("/api/ach/start", files=[_file("GL02.zip", b"noi dung that")])
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    ghi_ra = tmp_path / job_id / "input" / "GL02.zip"
    assert ghi_ra.read_bytes() == b"noi dung that"
    assert da_chay["job_id"] == job_id


def test_upload_qua_tran_khong_de_lai_job_ma_khoa_tinh_nang(admin_client, tmp_path, monkeypatch):
    monkeypatch.setattr(ach_service, "TEMP_DIR", tmp_path)
    monkeypatch.setattr("backend.api.ach._MAX_UPLOAD", 10)

    r = admin_client.post("/api/ach/start", files=[_file("to.zip", b"x" * 100)])
    assert r.status_code == 413

    # Không còn job nào chiếm máy chủ, và không để lại file cụt trên đĩa.
    assert ach_service.job_dang_chay() is None
    assert not list(tmp_path.iterdir())


def test_job_dang_upload_da_chan_luot_thu_hai(admin_client, tmp_path, monkeypatch):
    """Trước đây cửa 409 bỏ trống suốt lúc upload: hai lượt vài trăm MB cùng lọt
    qua rồi mới tranh nhau RAM, backend chết giữa chừng."""
    monkeypatch.setattr(ach_service, "TEMP_DIR", tmp_path)
    ach_service.tao_job()

    r = admin_client.post("/api/ach/start", files=[_file("GL02.zip", b"x")])
    assert r.status_code == 409

