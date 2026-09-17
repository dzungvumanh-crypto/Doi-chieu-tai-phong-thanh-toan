"""Log "request chậm" — ngưỡng, ngưỡng riêng, và đo tới byte cuối của phản hồi.

Chạy: .venv\Scripts\python.exe -m pytest tests/test_slow_request.py -v
"""
import logging
import time

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from backend.core import slow_request as sr


@pytest.fixture
def app_thu(monkeypatch):
    """App tí hon bọc đúng middleware thật — không đụng backend.main."""
    monkeypatch.setattr(sr.settings, "SLOW_REQUEST_MS", 50, raising=False)
    monkeypatch.setattr(sr.settings, "SLOW_REQUEST_EXCLUDE", ["/api/bo-qua"], raising=False)
    app = FastAPI()

    @app.get("/api/nhanh")
    def nhanh():
        return {"ok": True}

    @app.get("/api/cham")
    def cham():
        time.sleep(0.12)
        return {"ok": True}

    @app.get("/api/bo-qua/x")
    def bo_qua():
        time.sleep(0.12)
        return {"ok": True}

    @app.get("/api/leaves/preview")
    def preview():
        time.sleep(0.12)                      # < 8000 ms nên KHÔNG được kêu
        return {"ok": True}

    @app.get("/api/no")
    def no():
        time.sleep(0.12)
        raise RuntimeError("vỡ giữa chừng")

    @app.get("/api/tai-file")
    def tai_file():
        # Header trả về ngay, thân mất 0,12 s — BaseHTTPMiddleware sẽ đo hụt chỗ này
        def sinh():
            yield b"x"
            time.sleep(0.12)
            yield b"y"
        return StreamingResponse(sinh(), media_type="application/octet-stream")

    app.add_middleware(sr.SlowRequestMiddleware)
    return TestClient(app)


def _canh_bao(caplog):
    return [r for r in caplog.records if r.name == "slow.request"]


def test_nhanh_thi_khong_ghi_gi(app_thu, caplog):
    with caplog.at_level(logging.WARNING, logger="slow.request"):
        assert app_thu.get("/api/nhanh").status_code == 200
    assert _canh_bao(caplog) == []


def test_vuot_nguong_thi_ghi_warning_kem_duong_dan(app_thu, caplog):
    with caplog.at_level(logging.WARNING, logger="slow.request"):
        app_thu.get("/api/cham")
    (r,) = _canh_bao(caplog)
    assert "/api/cham" in r.getMessage() and "GET" in r.getMessage()


def test_duong_dan_loai_tru_thi_khong_ghi(app_thu, caplog):
    with caplog.at_level(logging.WARNING, logger="slow.request"):
        app_thu.get("/api/bo-qua/x")
    assert _canh_bao(caplog) == []


def test_duong_cham_co_chu_dich_dung_nguong_rieng(app_thu, caplog):
    # Dựng bản in qua Word lâu 5–7 s là đúng thiết kế → ngưỡng 8 s, không kêu
    with caplog.at_level(logging.WARNING, logger="slow.request"):
        app_thu.get("/api/leaves/preview")
    assert _canh_bao(caplog) == []


def test_tinh_ca_thoi_gian_gui_than_phan_hoi(app_thu, caplog):
    # Điểm chính của việc dùng ASGI thuần: header ra ngay nhưng thân mất 0,12 s
    with caplog.at_level(logging.WARNING, logger="slow.request"):
        assert app_thu.get("/api/tai-file").content == b"xy"
    (r,) = _canh_bao(caplog)
    assert "/api/tai-file" in r.getMessage()


def test_route_nem_loi_van_duoc_ghi(app_thu, caplog):
    # Phản hồi 500 do ServerErrorMiddleware (nằm NGOÀI middleware này) dựng nên không
    # mảnh thân nào đi qua — "chạy lâu rồi sập" là ca cần thấy nhất, không được bỏ sót.
    with caplog.at_level(logging.WARNING, logger="slow.request"):
        with pytest.raises(RuntimeError):
            app_thu.get("/api/no")
    (r,) = _canh_bao(caplog)
    assert "/api/no" in r.getMessage() and "ngoại lệ" in r.getMessage()


def test_khong_ghi_hai_lan_cho_mot_request(app_thu, caplog):
    with caplog.at_level(logging.WARNING, logger="slow.request"):
        app_thu.get("/api/cham")
    assert len(_canh_bao(caplog)) == 1


def test_scope_khong_phai_http_thi_cho_qua(app_thu):
    # lifespan chạy qua middleware; vào được là không chặn scope lạ
    with app_thu as c:
        assert c.get("/api/nhanh").status_code == 200


def test_nguong_theo_duong_dan(monkeypatch):
    monkeypatch.setattr(sr.settings, "SLOW_REQUEST_MS", 1500, raising=False)
    monkeypatch.setattr(sr.settings, "SLOW_REQUEST_EXCLUDE", ["/health"], raising=False)
    assert sr._nguong_ms("/api/leaves") == 1500
    assert sr._nguong_ms("/api/leaves/preview") == 8000
    assert sr._nguong_ms("/api/leaves/7/download") == 8000
    assert sr._nguong_ms("/api/ilo1000/start") == 10000
    assert sr._nguong_ms("/health") is None
    # Tên route thật đủ kiểu gạch nối — đây là chỗ bản đầu tính nhầm thành 1500
    assert sr._nguong_ms("/api/staff/export-db") == 8000
    assert sr._nguong_ms("/api/swift-recon/parse-preview") == 10000
    assert sr._nguong_ms("/api/doi-chieu-citad/extension-download") == 10000
    assert sr._nguong_ms("/api/doi-chieu-citad-nostro/month-summary/export") == 10000
    # Khớp theo ĐOẠN: /api/ach không được nuốt một module khác trùng đầu chữ
    assert sr._nguong_ms("/api/achilles/x") == 1500
    # Đoạn riêng, KHÔNG nằm trong tiền tố _kenh_core — khớp theo đoạn từng làm rơi mất module này
    assert sr._nguong_ms("/api/doi_chieu_song_phuong_kenh_core_di/start_upload") == 10000


# ── Trạng thái kèm theo dòng cảnh báo ──
def test_canh_bao_kem_trang_thai_luong_ket_noi_tai(app_thu, caplog):
    with caplog.at_level(logging.WARNING, logger="slow.request"):
        app_thu.get("/api/cham")
    (r,) = _canh_bao(caplog)
    msg = r.getMessage()
    for chu in ("luồng ", "kết nối CSDL ", "xếp cổng ", "đang xử lý ", "việc nặng ", "đối chiếu "):
        assert chu in msg, f"thiếu {chu!r}: {msg}"
    # Không bật đo trễ (app thử không chạy lifespan) thì phải nói rõ, không in số giả
    assert "loop trễ không đo" in msg


def test_chup_trang_thai_hong_van_ghi_duoc_canh_bao(app_thu, caplog, monkeypatch):
    from backend import database as _db

    def vo():
        raise RuntimeError("bể hỏng")
    monkeypatch.setattr(_db, "pool_stats", vo)
    with caplog.at_level(logging.WARNING, logger="slow.request"):
        r = app_thu.get("/api/cham")
    assert r.status_code == 200
    (w,) = _canh_bao(caplog)
    assert "/api/cham" in w.getMessage() and "không lấy được trạng thái" in w.getMessage()


def test_do_duoc_event_loop_bi_chan():
    import asyncio

    async def chay():
        sr.bat_do_tre()
        try:
            await asyncio.sleep(0.12)
            tu = time.monotonic()
            time.sleep(0.3)                  # chặn loop — đúng kiểu async def gọi hàm đồng bộ
            await asyncio.sleep(0.12)        # cho task đo kịp thức dậy ghi mẫu
            return sr.tre_loop_ms(tu)
        finally:
            await sr.tat_do_tre()

    tre = asyncio.run(chay())
    assert tre is not None and tre[0] >= 200, tre
    assert sr.tre_loop_ms(0) is None, "tắt rồi mà vẫn báo số"


def test_luong_nen_giu_gil_hien_o_tong_tre_du_max_nho():
    # Đúng ca nghi ngờ trên máy chủ: luồng đối chiếu thuần Python tranh GIL. Loop bị đói
    # thành nhiều quãng ngắn — max nhỏ, tổng lớn. Chỉ số max một mình sẽ bỏ sót.
    import asyncio
    import threading

    dung = threading.Event()

    def ton_cpu():
        while not dung.is_set():
            sum(i * i for i in range(2000))

    async def chay():
        sr.bat_do_tre()
        try:
            await asyncio.sleep(0.2)
            tu = time.monotonic()
            ts = [threading.Thread(target=ton_cpu) for _ in range(3)]
            [t.start() for t in ts]
            try:
                await asyncio.sleep(1.5)
            finally:
                dung.set()
                [t.join() for t in ts]
            return sr.tre_loop_ms(tu)
        finally:
            await sr.tat_do_tre()

    toi_da, tong = asyncio.run(chay())
    assert tong >= 150, (toi_da, tong)   # đo: 3 luồng × 2 s ≈ 790–890 ms; rảnh ≈ 12 ms


def test_luc_ranh_tong_tre_gan_0():
    import asyncio

    async def chay():
        sr.bat_do_tre()
        try:
            tu = time.monotonic()
            await asyncio.sleep(1.0)
            return sr.tre_loop_ms(tu)
        finally:
            await sr.tat_do_tre()

    toi_da, tong = asyncio.run(chay())
    assert tong < 80, (toi_da, tong)


def test_tat_do_tre_khi_task_da_chet_vi_loi_khong_nem():
    import asyncio

    async def chay():
        async def vo():
            raise RuntimeError("chết")
        sr._task_do_tre = asyncio.get_running_loop().create_task(vo())
        await asyncio.sleep(0)
        await sr.tat_do_tre()               # không được ném
        return sr._task_do_tre

    assert asyncio.run(chay()) is None


def test_async_def_chan_loop_hien_trong_canh_bao(monkeypatch, caplog):
    from contextlib import asynccontextmanager

    monkeypatch.setattr(sr.settings, "SLOW_REQUEST_MS", 50, raising=False)
    monkeypatch.setattr(sr.settings, "SLOW_REQUEST_EXCLUDE", [], raising=False)

    @asynccontextmanager
    async def lifespan(_app):
        sr.bat_do_tre()
        try:
            yield
        finally:
            await sr.tat_do_tre()

    app = FastAPI(lifespan=lifespan)

    @app.get("/api/chan-loop")
    async def chan_loop():
        time.sleep(0.3)
        return {"ok": True}

    app.add_middleware(sr.SlowRequestMiddleware)
    with TestClient(app) as cl, caplog.at_level(logging.WARNING, logger="slow.request"):
        cl.get("/api/chan-loop")
    (w,) = [r for r in _canh_bao(caplog) if "/api/chan-loop" in r.getMessage()]
    import re
    so = int(re.search(r"loop chặn tối đa (\d+) ms", w.getMessage()).group(1))
    assert so >= 150, w.getMessage()


def test_dem_dang_xu_ly_ve_0_ke_ca_khi_route_nem_loi(app_thu):
    try:
        app_thu.get("/api/no")
    except RuntimeError:
        pass
    app_thu.get("/api/nhanh")
    assert sr._dang_xu_ly == 0
