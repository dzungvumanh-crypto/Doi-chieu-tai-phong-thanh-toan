"""Log `viec_nang` + tên lượt đối chiếu trong `slow.request` — mốc để biết lúc một màn
chậm thì máy chủ đang bận việc gì.

Bối cảnh 14/09/2026: `/api/staff/` chậm 1,5 giây, log không có dòng nào cho biết lúc đó
Song phương đang chạy — phải hỏi người dùng nhớ lại. Lượt đối chiếu đã có mốc bắt đầu /
kết thúc từ `chay_tach()`; file này canh hai chỗ còn hở: việc nặng gắn theo request
(`run_heavy`) và tên đối chiếu trong dòng "Request chậm".
"""
import logging
import re
import sqlite3
import time

import anyio
import pytest

from backend.core import concurrency
from backend.core import slow_request as sr


def _dong(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "viec_nang"]


@pytest.fixture
def be_moi(monkeypatch):
    # Limiter gắn với event loop — mỗi anyio.run() là loop mới, phải dựng lại
    monkeypatch.setattr(concurrency, "_limiter", None)


# ── run_heavy: việc nặng gắn theo request ──

def test_run_heavy_ghi_khi_vuot_nguong(monkeypatch, be_moi, caplog):
    monkeypatch.setattr(concurrency, "HEAVY_LOG_MS", 0)

    def xuat_bao_cao(x):
        return x * 2

    async def _main():
        return await concurrency.run_heavy(xuat_bao_cao, 21)

    with caplog.at_level(logging.INFO, logger="viec_nang"):
        assert anyio.run(_main) == 42

    (dong,) = _dong(caplog)
    assert "test_run_heavy_ghi_khi_vuot_nguong.<locals>.xuat_bao_cao ·" in dong
    assert re.search(r"bắt đầu \d\d:\d\d:\d\d · chạy \d+ ms, chờ suất \d+ ms"
                     r" · việc nặng khác còn chạy 0/\d+$", dong)


def test_run_heavy_ham_boc_kem_ten_ham_duoc_boc(monkeypatch, be_moi, caplog):
    """SWIFT gọi `run_heavy(_xuat_tu_tep, tach.xuat_tong_hop, …)` — chỉ in tên hàm bọc thì
    không biết đang xuất báo cáo nào."""
    monkeypatch.setattr(concurrency, "HEAVY_LOG_MS", 0)

    def xuat_tong_hop(x):
        return x

    def _xuat_tu_tep(ham, *a):
        return ham(*a)

    async def _main():
        return await concurrency.run_heavy(_xuat_tu_tep, xuat_tong_hop, 7)

    with caplog.at_level(logging.INFO, logger="viec_nang"):
        assert anyio.run(_main) == 7
    (dong,) = _dong(caplog)
    assert re.search(r"_xuat_tu_tep\(\S+xuat_tong_hop\) ·", dong), dong


def test_run_heavy_tham_so_dau_la_ket_noi_csdl_khong_in_kem(monkeypatch, be_moi, caplog):
    """CITAD gọi `run_heavy(save_recon_history, db, …)` — `sqlite3.Connection` gọi được
    nhưng không phải hàm, in kèm là ra `<sqlite3.Connection object at 0x…>`."""
    monkeypatch.setattr(concurrency, "HEAVY_LOG_MS", 0)
    db = sqlite3.connect(":memory:")

    def save_recon_history(conn):
        return 1

    async def _main():
        return await concurrency.run_heavy(save_recon_history, db)

    try:
        with caplog.at_level(logging.INFO, logger="viec_nang"):
            anyio.run(_main)
    finally:
        db.close()
    (dong,) = _dong(caplog)
    assert "save_recon_history ·" in dong and "Connection" not in dong


def test_run_heavy_duoi_nguong_khong_ghi(monkeypatch, be_moi, caplog):
    monkeypatch.setattr(concurrency, "HEAVY_LOG_MS", 60_000)

    async def _main():
        return await concurrency.run_heavy(lambda: "ok")

    with caplog.at_level(logging.INFO, logger="viec_nang"):
        assert anyio.run(_main) == "ok"
    assert _dong(caplog) == []


def test_run_heavy_tach_thoi_gian_cho_suat(monkeypatch, be_moi, caplog):
    """Hết suất thì việc sau phải xếp hàng — log phải cho thấy phần CHỜ, không gộp vào CHẠY."""
    monkeypatch.setattr(concurrency, "HEAVY_LOG_MS", 0)
    monkeypatch.setattr(concurrency, "MAX_HEAVY", 1)

    def ngu():
        time.sleep(0.3)

    async def _main():
        async with anyio.create_task_group() as tg:
            tg.start_soon(concurrency.run_heavy, ngu)
            tg.start_soon(concurrency.run_heavy, ngu)

    with caplog.at_level(logging.INFO, logger="viec_nang"):
        anyio.run(_main)

    cho = sorted(int(re.search(r"chờ suất (\d+) ms", d).group(1)) for d in _dong(caplog))
    assert cho[0] < 150 and cho[1] >= 250


def test_run_heavy_loi_van_ghi_va_nem_tiep(monkeypatch, be_moi, caplog):
    monkeypatch.setattr(concurrency, "HEAVY_LOG_MS", 0)

    def hong():
        raise ValueError("file sai")

    async def _main():
        await concurrency.run_heavy(hong)

    with caplog.at_level(logging.INFO, logger="viec_nang"):
        with pytest.raises(ValueError):
            anyio.run(_main)
    assert len(_dong(caplog)) == 1


# ── slow.request: kèm tên lượt đối chiếu đang chạy ──

def _so_lieu(doi_chieu):
    return {
        "loop_chan_max_ms": None, "loop_tre_tong_ms": None,
        "luong_dung": 1, "luong_toi_da": 40, "luong_cho": 0,
        "csdl_dang_muon": 1, "csdl_toi_da": 48, "csdl_xep_cong": 0,
        "dang_xu_ly": 1, "nang_dang_chay": 0, "nang_dang_cho": 0, "nang_toi_da": 4,
        "doi_chieu": doi_chieu,
    }


def test_trang_thai_ke_ten_doi_chieu_dang_chay(monkeypatch):
    monkeypatch.setattr(sr, "so_lieu_tai", lambda tu: _so_lieu([
        {"module": "ach", "ten_module": "ACH", "job_id": "a"},
        {"module": "sp_di", "ten_module": "Song phương ĐI", "job_id": "b"},
    ]))
    assert sr.trang_thai(0).endswith("đối chiếu 2 (ACH, Song phương ĐI)")


def test_trang_thai_ranh_khong_them_ngoac(monkeypatch):
    monkeypatch.setattr(sr, "so_lieu_tai", lambda tu: _so_lieu([]))
    assert sr.trang_thai(0).endswith("đối chiếu 0")
