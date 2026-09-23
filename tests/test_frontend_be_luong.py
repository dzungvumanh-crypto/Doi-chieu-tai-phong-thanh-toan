"""P1 (23/09/2026): bể luồng cho asyncio.to_thread của frontend.

Bể mặc định = min(32, số lõi + 4) (12 ở máy dev), dùng chung cho mọi lời gọi backend của
mọi người dùng. Vài lượt gửi file dài (tới 600 s) là lời gọi nhẹ của người khác phải xếp hàng.
"""
import asyncio
import contextvars
import logging
import threading
import time

from frontend import be_luong


def _do_cho_viec_ngan(so_luong: int, so_viec_dai: int) -> float:
    """Giữ `so_viec_dai` luồng bận, rồi đo một việc ngắn mất bao lâu mới xong."""
    nha = threading.Event()

    async def chinh():
        loop = asyncio.get_running_loop()
        be = be_luong.BeLuongCoDo(so_luong)
        loop.set_default_executor(be)
        dai = [asyncio.create_task(asyncio.to_thread(nha.wait, 5)) for _ in range(so_viec_dai)]
        await asyncio.sleep(0.05)                  # để các việc dài chiếm luồng trước
        t = time.monotonic()
        # Việc ngắn: không có luồng thì chờ tới lúc việc dài nhả (0,3 s sau)
        loop.call_later(0.3, nha.set)
        await asyncio.to_thread(lambda: None)
        tre = time.monotonic() - t
        await asyncio.gather(*dai)
        be.shutdown(wait=True)
        return tre

    return asyncio.run(chinh())


def test_be_cu_12_luong_bi_viec_dai_chan():
    """Tái hiện: 12 việc dài chiếm hết bể 12 → việc ngắn phải chờ chúng nhả."""
    assert _do_cho_viec_ngan(so_luong=12, so_viec_dai=12) >= 0.25


def test_be_moi_khong_bi_viec_dai_chan():
    assert _do_cho_viec_ngan(so_luong=be_luong.SO_LUONG, so_viec_dai=12) < 0.2


def test_canh_bao_khi_phai_cho_luong(caplog, monkeypatch):
    monkeypatch.setattr(be_luong, "_NGUONG_CHO_GIAY", 0.1)
    with caplog.at_level(logging.WARNING, logger="frontend.be_luong"):
        _do_cho_viec_ngan(so_luong=4, so_viec_dai=4)
    assert any("chờ" in r.getMessage() and "FRONTEND_IO_THREADS" in r.getMessage()
               for r in caplog.records)


def test_contextvar_van_di_qua_to_thread():
    """app.storage.user tra theo contextvar của request — bể mới không được làm mất nó."""
    bien = contextvars.ContextVar("bien")

    async def chinh():
        asyncio.get_running_loop().set_default_executor(be_luong.BeLuongCoDo(4))
        bien.set("request-1")
        return await asyncio.to_thread(bien.get)

    assert asyncio.run(chinh()) == "request-1"


def test_cai_be_luong_dat_bo_thuc_thi_mac_dinh():
    async def chinh():
        be_luong.cai_be_luong()
        # to_thread chạy trên luồng tên "api_…" của bể mới
        return await asyncio.to_thread(lambda: threading.current_thread().name)

    assert asyncio.run(chinh()).startswith("api")


def test_doc_so_luong_tu_env_an_toan(monkeypatch):
    monkeypatch.setenv("FRONTEND_IO_THREADS", "khong-phai-so")
    assert be_luong._doc_so("FRONTEND_IO_THREADS", 64) == 64
    monkeypatch.setenv("FRONTEND_IO_THREADS", "1")
    assert be_luong._doc_so("FRONTEND_IO_THREADS", 64) == 4      # sàn 4, không để bể teo
