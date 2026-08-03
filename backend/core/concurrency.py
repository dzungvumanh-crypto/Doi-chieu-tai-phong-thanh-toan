"""Giới hạn số việc NẶNG được chạy đồng thời.

Mọi endpoint khai báo `def` của FastAPI chạy trong threadpool chung của anyio
(`CapacityLimiter` mặc định = 40 token). Việc nặng — sinh Word/Excel, pandas,
giải nén — giữ luồng rất lâu. 40 việc nặng cùng lúc là bể cạn sạch, và request
nhẹ phải xếp hàng: **kể cả `/api/auth/me`**, vì nó cũng là endpoint `def`.

Đo trên hệ thống thật: 40 request nặng đồng thời làm `/api/auth/me` kẹt
**38 giây**; 80 request làm kẹt 59 giây. Trung vị vẫn thấp — nghĩa là phần lớn
người dùng thấy bình thường còn một số ít treo cả phút, đúng kiểu lỗi khó tái hiện.

Bể riêng ở đây chặn điều đó: nhiều nhất `MAX_HEAVY` việc nặng chiếm luồng cùng
lúc, số token còn lại của bể 40 luôn dành cho request nhẹ.

Không mất gì về thông lượng: docxtpl/openpyxl là Python thuần nên giữ GIL suốt.
Đo được 40 việc nặng song song mất 43,3s — đúng bằng 40 × 1,08s chạy nối đuôi,
tức **không hề có song song**. Chạy 4 hay 40 cái cùng lúc thì tổng thời gian như
nhau; khác biệt duy nhất là giới hạn lại thì không ai bị bỏ đói.
"""
import functools
import logging
import os

import anyio
import anyio.to_thread

_log = logging.getLogger(__name__)

MAX_HEAVY = max(1, int(os.getenv("MAX_HEAVY_TASKS", "4")))

# Tạo trễ: anyio.CapacityLimiter cần event loop đang chạy, không dựng được ở
# thời điểm import module.
_limiter: "anyio.CapacityLimiter | None" = None


def _get_limiter() -> "anyio.CapacityLimiter":
    global _limiter
    if _limiter is None:
        # Không có await ở giữa check và gán → không có tranh chấp trên 1 event loop
        _limiter = anyio.CapacityLimiter(MAX_HEAVY)
        _log.info("Giới hạn việc nặng: tối đa %d chạy đồng thời", MAX_HEAVY)
    return _limiter


async def run_heavy(fn, *args, **kwargs):
    """Chạy một hàm đồng bộ tốn CPU trong threadpool, có giới hạn số việc song song.

    Dùng cho mọi endpoint sinh tài liệu / xử lý file. Endpoint phải là `async def`
    để `await` được — nếu để `def`, FastAPI tự đẩy vào bể 40 chung và giới hạn
    này không có tác dụng.
    """
    call = functools.partial(fn, *args, **kwargs) if (args or kwargs) else fn
    return await anyio.to_thread.run_sync(call, limiter=_get_limiter())


def heavy_stats() -> dict:
    """Trạng thái bể việc nặng — để chẩn đoán khi hệ thống có vẻ chậm."""
    if _limiter is None:
        return {"max": MAX_HEAVY, "dang_chay": 0, "dang_cho": 0}
    return {
        "max": MAX_HEAVY,
        "dang_chay": _limiter.borrowed_tokens,
        "dang_cho": _limiter.statistics().tasks_waiting,
    }
