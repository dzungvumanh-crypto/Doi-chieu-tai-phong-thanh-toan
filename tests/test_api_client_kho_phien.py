"""api_client sửa app.storage.user trên event loop, kể cả khi được gọi từ to_thread.

Trước 23/09/2026: 401 → `clear_auth()` chạy ngay trong luồng của `asyncio.to_thread`,
NiceGUI lên lịch lưu xuống đĩa từ sai luồng → `RuntimeError: There is no current event
loop` (1.638 lần trong logs/frontend.log). `load_my_features()` sau đăng nhập cũng vậy.
"""
import asyncio
import threading
from types import SimpleNamespace

import pytest

import frontend.api_client as api


class _KhoGhiLuong(dict):
    """dict ghi lại luồng nào đã sửa nó."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.luong_sua: set[int] = set()

    def __setitem__(self, k, v):
        self.luong_sua.add(threading.get_ident())
        super().__setitem__(k, v)

    def pop(self, *a):
        self.luong_sua.add(threading.get_ident())
        return super().pop(*a)


@pytest.fixture
def kho(monkeypatch):
    k = _KhoGhiLuong(token="t", user_data={"id": 1}, features=["x"])
    monkeypatch.setattr(api, "app", SimpleNamespace(storage=SimpleNamespace(user=k)))
    return k


def _chay_tren_loop(monkeypatch, ham):
    """Chạy `ham` trong to_thread khi loop đang chạy; trả kho ngay sau await."""
    async def chinh():
        monkeypatch.setattr(api.core, "loop", asyncio.get_running_loop())
        await asyncio.to_thread(ham)
        return threading.get_ident()
    return asyncio.run(chinh())


def test_clear_auth_tu_luong_phu_sua_tren_loop(monkeypatch, kho):
    luong_loop = _chay_tren_loop(monkeypatch, api.clear_auth)
    assert dict(kho) == {}                  # đã xoá xong khi await trả về
    assert kho.luong_sua == {luong_loop}    # và xoá trên luồng của loop


def test_load_my_features_tu_luong_phu_sua_tren_loop(monkeypatch, kho):
    monkeypatch.setattr(api, "get", lambda path, *a, **kw: {"features": ["menu.leaves"]})
    luong_loop = _chay_tren_loop(monkeypatch, api.load_my_features)
    assert kho["features"] == ["menu.leaves"]
    assert kho.luong_sua == {luong_loop}


def test_khong_co_loop_thi_sua_thang(monkeypatch, kho):
    monkeypatch.setattr(api.core, "loop", None)
    api.set_token("moi", {"id": 2})
    assert kho["token"] == "moi" and kho["user_data"] == {"id": 2}
