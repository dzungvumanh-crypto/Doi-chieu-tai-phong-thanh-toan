# -*- coding: utf-8 -*-
"""Chốt chặn số lượt đối chiếu nặng chạy cùng lúc — 4 module dùng chung.

Canh hai luật cố ý khác nhau (xem backend/core/phien_doi_chieu.py):
  - cùng MỘT module: luôn 1 lượt, không nới được;
  - toàn hệ thống: `MAX_SONG_SONG` lượt, vì khác menu thì vài người chạy song
    song là chuyện bình thường.

Trước file này chỉ ACH có chốt, và nó cũng chỉ tự canh mình.
"""
import threading
import time

import pytest

from backend.core import phien_doi_chieu


@pytest.fixture(autouse=True)
def _don_nguon():
    """Mỗi test tự dựng nguồn riêng — không đụng vào 4 module thật đã khai lúc import."""
    goc = dict(phien_doi_chieu._NGUON)
    phien_doi_chieu._NGUON.clear()
    yield
    phien_doi_chieu._NGUON.clear()
    phien_doi_chieu._NGUON.update(goc)


def _khai(ma: str, job: dict | None):
    phien_doi_chieu.dang_ky_nguon(ma, f"Module {ma}", lambda: job)


def _job(job_id="j1", status="running", tuoi=0):
    return {"job_id": job_id, "status": status, "tuoi_giay": tuoi}


# ── Luật 1: cùng module luôn 1 lượt ──────────────────────────────────────────
def test_module_ranh_thi_cho_chay():
    _khai("ach", None)
    assert phien_doi_chieu.kiem_tra("ach") is None


def test_cung_module_dang_chay_thi_chan():
    _khai("ach", _job("abc", "running", 125))
    nghen = phien_doi_chieu.kiem_tra("ach")
    assert nghen is not None
    assert "abc" in nghen["message"]
    assert "2 phút" in nghen["message"]


def test_chan_cung_module_giu_nguyen_hinh_dang_job_cho_trang_ach():
    """Trang ACH đọc job_id/status/tuoi_giay để hiện nút "Dừng" — đổi hình dạng
    này là nút đó im lặng không hiện, không lỗi nào."""
    _khai("ach", _job("abc", "awaiting_confirmation", 60))
    job = phien_doi_chieu.kiem_tra("ach")["job"]
    assert job["job_id"] == "abc"
    assert job["status"] == "awaiting_confirmation"
    assert job["tuoi_giay"] == 60


def test_module_khac_dang_chay_khong_chan_module_nay():
    """Khác menu thì vẫn chạy được — đây là điểm khác chốt "1 lượt toàn hệ thống"."""
    _khai("ach", _job())
    _khai("ilo1000", None)
    assert phien_doi_chieu.kiem_tra("ilo1000") is None


# ── Luật 2: trần toàn hệ thống ───────────────────────────────────────────────
def test_cham_tran_toan_he_thong_thi_chan(monkeypatch):
    monkeypatch.setattr(phien_doi_chieu, "MAX_SONG_SONG", 2)
    _khai("ach", _job("a"))
    _khai("ilo1000", _job("b"))
    _khai("cham459901", None)
    nghen = phien_doi_chieu.kiem_tra("cham459901")
    assert nghen is not None
    assert "giới hạn 2" in nghen["message"]
    assert len(nghen["dang_chay"]) == 2


def test_duoi_tran_thi_van_cho_chay(monkeypatch):
    monkeypatch.setattr(phien_doi_chieu, "MAX_SONG_SONG", 3)
    _khai("ach", _job("a"))
    _khai("ilo1000", _job("b"))
    _khai("cham459901", None)
    assert phien_doi_chieu.kiem_tra("cham459901") is None


def test_tran_khong_noi_duoc_luat_cung_module(monkeypatch):
    """Đặt trần cao tới mấy thì hai lượt CÙNG module vẫn bị chặn."""
    monkeypatch.setattr(phien_doi_chieu, "MAX_SONG_SONG", 99)
    _khai("ach", _job("a"))
    assert phien_doi_chieu.kiem_tra("ach") is not None


# ── Nguồn báo cáo lỗi ────────────────────────────────────────────────────────
def test_mot_module_bao_cao_loi_khong_lam_chet_cua_kiem_tra(caplog):
    """Đếm hụt là chốt tự nới ra âm thầm — phải ghi log ERROR, nhưng không được
    làm hỏng cửa kiểm tra của ba module còn lại."""
    def _no():
        raise RuntimeError("store hỏng")

    phien_doi_chieu.dang_ky_nguon("hong", "Module hỏng", _no)
    _khai("ach", None)
    assert phien_doi_chieu.kiem_tra("ach") is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


# ── Bốn module thật đều đã khai ──────────────────────────────────────────────
def test_moi_cua_that_deu_da_khai(_don_nguon):
    """Thiếu một cửa trong sổ khai = nó không bị đếm, chốt hụt một suất mà không
    ai biết. Đã dính hai lần: "Phân loại dữ liệu" (chiều ĐI) bị bỏ sót lúc viết
    chốt, và module chiều ĐI vào develop qua PR #86 SAU khi chốt được viết.
    Test này là thứ duy nhất bắt được cửa thứ N+1 khi có người thêm module mới."""
    phien_doi_chieu._NGUON.clear()
    import importlib
    for ten in (
        "backend.services.ach_service",
        "backend.services.ilo1000_service",
        "backend.services.cham459901_service",
        "backend.services.doi_chieu_song_phuong_service",
        "backend.services.doi_chieu_song_phuong_kenh_core_service",
        "backend.services.doi_chieu_song_phuong_kenh_core_di_service",
    ):
        importlib.reload(importlib.import_module(ten))
    assert set(phien_doi_chieu._NGUON) == {
        "ach", "ilo1000", "cham459901",
        "song_phuong", "song_phuong_di", "song_phuong_kenh_core_di",
    }


# ── gianh_cho(): kiểm tra + đăng ký phải là MỘT thao tác nguyên tử ───────────
def test_gianh_cho_chan_dua_luong(_don_nguon):
    """Hai bước rời (`kiem_tra()` rồi `tao_job()`) để lọt nhiều lượt cùng lúc.

    Đo thật qua HTTP trước khi sửa: bắn 5 request ILO1000 đồng thời thì 2 lọt
    thay vì 1. Hai người cùng bấm "Chạy" đúng lúc chính là kịch bản đã làm sập
    backend 26/08/2026, nên đây không phải lỗi lý thuyết.
    """
    dang_chay: list[str] = []          # đóng vai sổ job của service
    lock_so = threading.Lock()

    def _bao_cao():
        with lock_so:
            return {"job_id": dang_chay[0], "status": "running"} if dang_chay else None

    phien_doi_chieu.dang_ky_nguon("m", "Module m", _bao_cao)

    thang: list[str] = []
    rao = threading.Barrier(12)

    def _chay(i):
        rao.wait()                     # ép 12 luồng vào cửa cùng một lúc
        with phien_doi_chieu.gianh_cho("m") as nghen:
            if nghen:
                return
            # `tao_job()` thật có tạo thư mục — mất mili-giây, và ĐÓ chính là khe
            # hở. Không mô phỏng độ trễ này thì test qua với CẢ cách cũ lẫn cách
            # mới, tức là không canh được gì (đã đo: cả hai đều ra 1).
            # Có độ trễ: cách cũ cho lọt 12/12, cách mới đúng 1.
            time.sleep(0.01)
            with lock_so:
                dang_chay.append(f"job{i}")
            thang.append(f"job{i}")

    ts = [threading.Thread(target=_chay, args=(i,)) for i in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=10)

    assert len(thang) == 1, f"{len(thang)} lượt cùng lọt qua cửa, đáng lẽ đúng 1"


def test_gianh_cho_nha_khoa_khi_than_khoi_nem(_don_nguon):
    """Lỗi giữa chừng mà không nhả khoá thì cả bốn module treo vĩnh viễn."""
    _khai("m", None)
    with pytest.raises(ValueError):
        with phien_doi_chieu.gianh_cho("m"):
            raise ValueError("hỏng lúc tạo job")
    # Vào lại được ngay là khoá đã nhả
    with phien_doi_chieu.gianh_cho("m") as nghen:
        assert nghen is None
