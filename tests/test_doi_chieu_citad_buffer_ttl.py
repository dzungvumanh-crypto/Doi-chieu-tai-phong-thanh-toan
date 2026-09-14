# -*- coding: utf-8 -*-
"""
test_doi_chieu_citad_buffer_ttl.py
------------------------------------
Bug thật (14/09/2026, Phòng Thanh toán báo): quét EUR trên CITAD ra 0 giao
dịch (Extension không gửi gì lên — xem content.js autoSaveIfNew(), tránh
nhầm "trang chưa load xong" với "thật sự không có"), sau đó quét USD (có
giao dịch) rồi bấm "Nạp CITAD" — bảng hiện SỐ CẢ EUR LẪN USD, dù EUR hôm đó
không có gì. Nguyên nhân: buffer server (`_citad_buffer`/`_ph_buffer`) là
dict RAM không có hạn dùng — 1 mục EUR gửi lên từ rất lâu trước đó (hôm
khác, lúc test) nằm lại vô thời hạn, bị nạp nhầm cùng lượt với mục USD mới.

Sửa: gắn mốc thời gian server-side (`_scan_ts`, dùng `_vn_now()`) lúc lưu,
tự loại mục quá `_BUFFER_TTL` (4 giờ) mỗi khi đọc buffer (`buffer_get_citad`/
`buffer_get_ph`) — khoá lại đúng hành vi đó ở đây.
"""
from datetime import timedelta

from backend.services import doi_chieu_citad_service as svc

OWNER = "_test_ttl_owner"


def setup_function():
    svc._citad_buffer.pop(OWNER, None)
    svc._ph_buffer.pop(OWNER, None)


def test_muc_qua_han_bi_loai_khoi_buffer_citad(monkeypatch):
    now = svc._vn_now()
    monkeypatch.setattr(svc, "_vn_now", lambda: now - timedelta(hours=5))
    svc.buffer_save_citad(OWNER, {
        "key": "citad_1_EUR_di_ih", "cong": "1", "loai": "ih", "chieu": "di",
        "tien": "EUR", "soMon": 3, "soTien": 1000.0,
    })

    monkeypatch.setattr(svc, "_vn_now", lambda: now)
    svc.buffer_save_citad(OWNER, {
        "key": "citad_1_USD_di_ih", "cong": "1", "loai": "ih", "chieu": "di",
        "tien": "USD", "soMon": 2, "soTien": 500.0,
    })

    items = svc.buffer_get_citad(OWNER)
    assert [i["tien"] for i in items] == ["USD"]


def test_muc_con_han_van_giu_nguyen_trong_buffer_citad(monkeypatch):
    now = svc._vn_now()
    monkeypatch.setattr(svc, "_vn_now", lambda: now - timedelta(hours=1))
    svc.buffer_save_citad(OWNER, {
        "key": "citad_1_EUR_di_ih", "cong": "1", "loai": "ih", "chieu": "di",
        "tien": "EUR", "soMon": 3, "soTien": 1000.0,
    })

    monkeypatch.setattr(svc, "_vn_now", lambda: now)
    items = svc.buffer_get_citad(OWNER)
    assert [i["tien"] for i in items] == ["EUR"]


def test_muc_qua_han_bi_loai_khoi_buffer_paymenthub(monkeypatch):
    now = svc._vn_now()
    monkeypatch.setattr(svc, "_vn_now", lambda: now - timedelta(hours=5))
    svc.buffer_save_ph(OWNER, [{
        "key": "ph_di_ih_EUR", "loai": "ih", "chieu": "di", "tien": "EUR",
        "soMon": 1, "soTien": 100.0,
    }])

    monkeypatch.setattr(svc, "_vn_now", lambda: now)
    svc.buffer_save_ph(OWNER, [{
        "key": "ph_di_ih_USD", "loai": "ih", "chieu": "di", "tien": "USD",
        "soMon": 1, "soTien": 50.0,
    }])

    items = svc.buffer_get_ph(OWNER)
    assert [i["tien"] for i in items] == ["USD"]


def test_buffer_get_rong_khi_chua_tung_luu():
    assert svc.buffer_get_citad(OWNER) == []
    assert svc.buffer_get_ph(OWNER) == []
