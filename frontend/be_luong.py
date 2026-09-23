"""Bể luồng cho `asyncio.to_thread` của tiến trình frontend (NiceGUI).

Mọi lời gọi backend của MỌI người dùng đi qua `asyncio.to_thread(api.…)` (443 chỗ,
23/09/2026) — tức bể mặc định của event loop: `min(32, số lõi + 4)` luồng, máy dev 8 lõi
là 12. Một lượt gửi file ACH / Song phương giữ 1 luồng tới 600 giây, xem trước đơn nghỉ
phép tới 160 giây, mở trang Nghỉ phép bắn 10 lời gọi cùng lúc. Vài việc dài trùng nhau
là bể cạn: lời gọi nhẹ của người khác (mở trang, bấm nút, nhịp kiểm tra phiên) xếp hàng
chờ luồng — màn hình đứng mà backend vẫn rảnh.

Nới bể ở đây RẺ, khác hẳn backend (docs/DESIGN.md: không nới bể 40 luồng ở backend):
luồng frontend gần như chỉ chờ mạng, nhả GIL suốt lúc chờ. Áp lực đổ về backend, nơi đã
có cổng CSDL chờ bằng `await` và `MAX_HEAVY` cho việc nặng.

Bể có đo: việc nào phải chờ luồng lâu hơn `_NGUONG_CHO_GIAY` thì ghi WARNING (tối đa
một dòng mỗi phút) — có số thật để biết bể đã đủ hay chưa, thay vì đoán.
"""
import asyncio
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

_log = logging.getLogger("frontend.be_luong")

_NGUONG_CHO_GIAY = 0.5
_CACH_LOG_GIAY = 60.0


def _doc_so(ten_bien: str, mac_dinh: int) -> int:
    tho = (os.getenv(ten_bien) or "").strip()
    try:
        return max(4, int(tho)) if tho else mac_dinh
    except ValueError:
        _log.warning("%s=%r không phải số — dùng mặc định %d", ten_bien, tho, mac_dinh)
        return mac_dinh


# 64 < 100 kết nối tối đa của httpx.Client dùng chung (api_client._client) — thêm luồng
# mà hết kết nối thì chỉ dời chỗ xếp hàng vào trong httpx.
SO_LUONG = _doc_so("FRONTEND_IO_THREADS", 64)


class BeLuongCoDo(ThreadPoolExecutor):
    """ThreadPoolExecutor ghi WARNING khi việc phải chờ luồng quá lâu."""

    def __init__(self, max_workers: int):
        super().__init__(max_workers=max_workers, thread_name_prefix="api")
        self._khoa = threading.Lock()
        self._dang_chay = 0
        self._lan_log = 0.0
        self.cho_lau_nhat = 0.0          # giây — để chẩn đoán / test

    def submit(self, fn, /, *args, **kwargs):
        luc_gui = time.monotonic()

        def _chay():
            cho = time.monotonic() - luc_gui
            with self._khoa:
                self._dang_chay += 1
                dang_chay = self._dang_chay
                self.cho_lau_nhat = max(self.cho_lau_nhat, cho)
                ghi = cho >= _NGUONG_CHO_GIAY and luc_gui - self._lan_log >= _CACH_LOG_GIAY
                if ghi:
                    self._lan_log = luc_gui
            if ghi:
                _log.warning(
                    "Lời gọi backend chờ %.0f ms mới có luồng (bể %d luồng, đang chạy %d, "
                    "hàng chờ %d) — nếu lặp lại thường xuyên, nâng FRONTEND_IO_THREADS trong .env",
                    cho * 1000, self._max_workers, dang_chay, self._work_queue.qsize())
            try:
                return fn(*args, **kwargs)
            finally:
                with self._khoa:
                    self._dang_chay -= 1

        return super().submit(_chay)


def cai_be_luong() -> None:
    """Đặt bể cho event loop đang chạy. Gọi trong `app.on_startup`."""
    asyncio.get_running_loop().set_default_executor(BeLuongCoDo(SO_LUONG))
    _log.info("Bể luồng gọi backend: %d luồng", SO_LUONG)
