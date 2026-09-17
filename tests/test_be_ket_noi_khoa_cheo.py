# -*- coding: utf-8 -*-
"""Bể kết nối + threadpool khoá chéo nhau khi nhiều request tới cùng lúc.

Đo trên máy dev (16/09/2026): 78 request đồng thời chậm nhất 268 ms, 90 request
thì MỌI request đứng 31 giây rồi ~40 cái ăn 500 "Hết kết nối CSDL". Ngưỡng ≈
48 kết nối + 40 luồng: request đã cầm kết nối cần thêm luồng để chạy tiếp, còn
cả 40 luồng bị giữ bởi request đang đứng chờ kết nối trong `_muon()`.

Ở đây thu nhỏ về 2 kết nối + 2 luồng để tái hiện trong vài giây.
"""
import asyncio
import time

import anyio.to_thread
import httpx
import pytest
from fastapi import Depends, FastAPI

from backend import database as db_mod

_SO_REQUEST = 10


@pytest.fixture()
def be_nho(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "DB_PATH", str(tmp_path / "thu.db"))
    monkeypatch.setattr(db_mod, "_pool", db_mod.queue.LifoQueue())
    monkeypatch.setattr(db_mod, "_da_tao", 0)
    monkeypatch.setattr(db_mod, "_POOL_MAX", 2)
    monkeypatch.setattr(db_mod, "_POOL_CHO_GIAY", 3.0)
    monkeypatch.setattr(db_mod, "_cong_db", None, raising=False)
    db_mod.khoi_tao_pool()
    yield db_mod
    db_mod.dong_pool()


def _app():
    app = FastAPI()

    # Dependency đồng bộ thứ hai = một lượt xin luồng nữa SAU KHI đã cầm kết nối,
    # đúng như get_current_staff / require_feature ở hệ thống thật.
    def nguoi_dung(db=Depends(db_mod.get_db)):
        return db.execute("SELECT 1").fetchone()[0]

    @app.get("/x")
    def x(_=Depends(nguoi_dung), db=Depends(db_mod.get_db)):
        time.sleep(0.01)
        return {"ok": db.execute("SELECT 1").fetchone()[0]}

    return app


async def _ban_dong_thoi(app):
    anyio.to_thread.current_default_thread_limiter().total_tokens = 2
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as cl:
        t = time.perf_counter()
        kq = await asyncio.gather(*(cl.get("/x") for _ in range(_SO_REQUEST)))
        return [r.status_code for r in kq], time.perf_counter() - t


def test_nhieu_request_hon_ket_noi_cong_luong_khong_dung_ca_he_thong(be_nho):
    ma, giay = asyncio.run(_ban_dong_thoi(_app()))
    assert ma == [200] * _SO_REQUEST, f"Có request lỗi: {ma}"
    # Kẹt thì phải chờ hết _POOL_CHO_GIAY (3 s) mới gỡ được — không kẹt thì ~0,1 s
    assert giay < 1.5, f"{_SO_REQUEST} request mất {giay:.1f} s — bể và threadpool đang chờ nhau"


def test_ket_noi_tra_du_ve_be_sau_dot_tai(be_nho):
    asyncio.run(_ban_dong_thoi(_app()))
    tt = be_nho.pool_stats()
    assert tt["dang_muon"] == 0, f"Còn kết nối chưa trả: {tt}"
    assert tt["da_tao"] <= 2


def test_cho_qua_cong_qua_han_tra_503_va_ghi_log(be_nho, monkeypatch, caplog):
    # Lỗi ném trong dependency chỉ ra console uvicorn, không vào logs/app.log —
    # bản cũ để người vận hành không bao giờ thấy "Hết kết nối CSDL".
    monkeypatch.setattr(db_mod, "_POOL_MAX", 1)
    monkeypatch.setattr(db_mod, "_POOL_CHO_GIAY", 0.3)
    app = FastAPI()

    @app.get("/giu")
    def giu(db=Depends(db_mod.get_db)):
        time.sleep(1.0)
        return {"ok": 1}

    async def chay():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as cl:
            kq = await asyncio.gather(cl.get("/giu"), cl.get("/giu"))
            return sorted(r.status_code for r in kq)

    with caplog.at_level("WARNING", logger="backend.database"):
        ma = asyncio.run(chay())
    assert ma == [200, 503]
    assert any("Hết lượt vào CSDL" in r.getMessage() for r in caplog.records)
