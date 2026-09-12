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
