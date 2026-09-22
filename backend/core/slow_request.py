"""Ghi WARNING cho request chạy lâu hơn ngưỡng — để biết chỗ nào cần tối ưu.

Vì sao cần: hệ thống có log `db.contention` cho lỗi khoá CSDL, nhưng KHÔNG có gì
đo thời gian của request bình thường. Không có số thì mọi việc "tối ưu hiệu năng"
đều là đoán (xem mục 1.2 kế hoạch cải tiến).

Hai điểm thiết kế:

* **ASGI thuần, đo tới lúc gửi xong THÂN phản hồi.** `BaseHTTPMiddleware` chỉ đo
  tới lúc có header — file tải về 100 MB stream trong 30 giây sẽ hiện ra như một
  request 20 ms. Ở đây mốc dừng là `http.response.body` cuối cùng.
* **Ngưỡng riêng cho việc chậm CÓ CHỦ ĐÍCH.** Một ngưỡng phẳng 1,5 giây sẽ kêu
  liên tục ở những đường vốn dĩ lâu (dựng bản in qua Word 5–7 giây lần đầu, nộp
  file đối chiếu hàng trăm MB), và log kêu liên tục thì không ai đọc nữa.
"""
import asyncio
import collections
import logging
import time

import anyio.to_thread

from backend.core.config import settings

_log = logging.getLogger("slow.request")

# (tiền tố đường dẫn, ngưỡng ms, vì sao) — khớp theo tiền tố DÀI NHẤT.
# Đây là những đường CHẬM LÀ BÌNH THƯỜNG; chậm hơn cả mức này mới đáng kêu.
_NGUONG_RIENG = (
    ("/api/leaves/preview", 8000),               # Word dựng bản in: lần đầu 5–7 s (DESIGN.md)
    ("/api/admin/monitor", 5000),                # đo CPU 0,3 s + hỏi NTP khi hết cache (tới 3 s)
    ("/api/ach", 10000),                         # nộp + chạy đối chiếu, file hàng trăm MB
    ("/api/ilo1000", 10000),
    ("/api/cham459901", 10000),
    ("/api/cham459901_000000000", 10000),        # đoạn riêng, KHÔNG nằm trong tiền tố trên
    ("/api/doi_chieu_song_phuong", 10000),
    ("/api/doi_chieu_song_phuong_kenh_core", 10000),
    ("/api/doi_chieu_song_phuong_kenh_core_di", 10000),   # đoạn riêng, KHÔNG nằm trong tiền tố trên
    ("/api/doi-chieu-citad", 10000),
    ("/api/doi-chieu-citad-nostro", 10000),
    ("/api/doi-soat-citad", 10000),
    ("/api/swift-recon", 10000),
)

# Đoạn đường dẫn chứa một trong các từ này = dựng file (Excel/Word/PDF/ZIP) — việc
# nặng có chủ đích ở bất kỳ module nào. Xét theo TỪNG ĐOẠN và dùng "chứa" chứ không
# "bắt đầu bằng": tên route thật có đủ kiểu — `/export-db`, `/export-summary`,
# `/parse-preview`, `/extension-download`, `/month-summary/export`.
_TU_VIEC_NANG = ("export", "preview", "download")
_MS_NANG = 8000


def _khop_tien_to(path: str, pre: str) -> bool:
    """Khớp theo ĐOẠN, không theo ký tự: `/api/ach` không được nuốt `/api/achilles`."""
    return path == pre or path.startswith(pre + "/")


def _nguong_ms(path: str) -> int | None:
    """Ngưỡng cho đường dẫn này, None = không theo dõi."""
    for p in settings.SLOW_REQUEST_EXCLUDE:
        if _khop_tien_to(path, p):      # cùng luật đoạn: khai /api/ach không tắt /api/achilles
            return None
    # Tiền tố DÀI NHẤT thắng — không phải ngưỡng lớn nhất: thêm một tiền tố con có
    # ngưỡng thấp hơn thì phải là cái đó quyết định.
    khop = [(len(pre), ms) for pre, ms in _NGUONG_RIENG if _khop_tien_to(path, pre)]
    if khop:
        return max(khop)[1]
    if any(tu in doan for doan in path.split("/") for tu in _TU_VIEC_NANG):
        return _MS_NANG
    return settings.SLOW_REQUEST_MS


# ── Trạng thái kèm theo mỗi dòng cảnh báo ──
# Chỉ biết "request X mất 2 giây" thì không biết nó bận hay đứng chờ, và chờ cái gì.
# 17/09/2026 đã loại lần lượt khoá CSDL, job đối chiếu, bcrypt, CPU, Defender mà
# vẫn không ra nguyên nhân các cảnh báo 1,5–2,5 s — đoán từ ngoài vào hết đường.
# Nên mỗi dòng tự chụp tình trạng bên trong backend đúng lúc nó chậm.
#
# Chỉ số quan trọng nhất là EVENT LOOP BỊ CHẶN: một `async def` gọi hàm đồng bộ nặng
# (giải nén, đọc file, pandas) mà không `await` thì MỌI request đứng theo, 8 lõi rảnh
# cũng vô ích. Không đo từ trong request được — lúc loop bị chặn thì chính middleware
# này cũng không chạy — nên có một task nền ngủ từng nhịp ngắn và ghi độ trễ khi thức.
_NHIP_GIAY = 0.05
# Nền: asyncio.sleep trên Windows tự trễ tới một nhịp timer (15,6 ms) dù máy rảnh. Không
# trừ thì "tổng trễ" của request 2 s lúc rảnh đã ~300 ms — đọc nhầm thành loop bị đói.
_NEN_GIAY = 0.016
_mau_tre: "collections.deque[tuple[float, float]]" = collections.deque(maxlen=6000)  # ~5 phút
_task_do_tre: "asyncio.Task | None" = None
_ngu_tu = 0.0          # lúc task đo bắt đầu nhịp ngủ hiện tại
_dang_xu_ly = 0


async def _do_tre_vong_lap():
    global _ngu_tu
    while True:
        t = _ngu_tu = time.monotonic()
        await asyncio.sleep(_NHIP_GIAY)
        xong = time.monotonic()
        _mau_tre.append((xong, max(0.0, xong - t - _NHIP_GIAY)))


def bat_do_tre() -> None:
    """Gọi trong lifespan, sau khi event loop chạy."""
    global _task_do_tre
    if _task_do_tre is not None and not _task_do_tre.done():
        _task_do_tre.cancel()           # gọi hai lần: không để task cũ chạy mồ côi
    _mau_tre.clear()
    _task_do_tre = asyncio.get_running_loop().create_task(_do_tre_vong_lap())


async def tat_do_tre() -> None:
    global _task_do_tre
    if _task_do_tre is None:
        return
    task, _task_do_tre = _task_do_tre, None
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        if asyncio.current_task().cancelling():
            raise                        # chính lúc tắt máy bị huỷ từ ngoài — không nuốt
    except Exception:
        # Không được ném: lifespan còn xả audit và đóng bể CSDL ngay sau lời gọi này
        _log.warning("Task đo trễ event loop đã chết vì lỗi", exc_info=True)


def tre_loop_ms(tu: float) -> "tuple[float, float] | None":
    """(chặn lâu nhất, tổng trễ trừ nền) tính bằng ms kể từ mốc `tu`. None = không đo.

    Cần CẢ HAI: `async def` gọi hàm đồng bộ là một cú chặn dài → max lớn. Luồng nền
    giữ GIL thì loop bị đói thành nhiều quãng ngắn → max chỉ 120–290 ms trong khi tổng
    trễ ~1 s cho request 2 s (phản biện đo 17/09/2026). Chỉ nhìn max là kết luận nhầm
    "không phải GIL".
    """
    if _task_do_tre is None:
        return None
    # Mẫu ghi lúc THỨC DẬY; lần chặn bắt đầu trước `tu` mà kết thúc sau vẫn tính.
    mau = [tre for luc, tre in _mau_tre if luc >= tu]
    # Dòng cảnh báo được ghi NGAY khi loop vừa thoát chỗ chặn — task đo chưa kịp thức
    # để ghi mẫu. Không cộng phần "đang ngủ quá giờ" này thì đúng ca cần bắt lại báo 0.
    mau.append(max(0.0, time.monotonic() - _ngu_tu - _NHIP_GIAY))
    return max(mau) * 1000, sum(max(0.0, t - _NEN_GIAY) for t in mau) * 1000


def so_lieu_tai(tu: float) -> dict:
    """Số liệu tải bên trong backend kể từ mốc `tu` (monotonic). CÓ THỂ raise.

    Phải gọi trên event loop: bộ đếm luồng của anyio gắn theo loop đang chạy. Dùng
    chung cho dòng "Request chậm" và màn Giám sát hệ thống — một nguồn, hai chỗ đọc.
    """
    from backend import database as _db
    from backend.core import concurrency as _cc, phien_doi_chieu as _pdc

    tre = tre_loop_ms(tu)
    lim = anyio.to_thread.current_default_thread_limiter()
    be = _db.pool_stats()
    cong = _db._cong_db
    xep = cong[1].statistics().tasks_waiting if cong and cong[0] is asyncio.get_running_loop() else 0
    nang = _cc.heavy_stats()
    return {
        "loop_chan_max_ms": None if tre is None else round(tre[0]),
        "loop_tre_tong_ms": None if tre is None else round(tre[1]),
        "luong_dung": lim.borrowed_tokens,
        "luong_toi_da": round(lim.total_tokens),
        "luong_cho": lim.statistics().tasks_waiting,
        "csdl_dang_muon": be["dang_muon"],
        "csdl_toi_da": be["toi_da"],
        "csdl_xep_cong": xep,
        "dang_xu_ly": _dang_xu_ly,
        "nang_dang_chay": nang["dang_chay"],
        "nang_dang_cho": nang["dang_cho"],
        "nang_toi_da": nang["max"],
        "doi_chieu": _pdc.dang_chay(),
    }


def trang_thai(tu: float) -> str:
    """Một dòng ngắn: loop, luồng, kết nối CSDL, tải. Không bao giờ raise."""
    try:
        s = so_lieu_tai(tu)
        phan = [
            "loop trễ không đo" if s["loop_chan_max_ms"] is None
            else f"loop chặn tối đa {s['loop_chan_max_ms']} ms, trễ tổng {s['loop_tre_tong_ms']} ms",
            f"luồng {s['luong_dung']}/{s['luong_toi_da']} chờ {s['luong_cho']}",
            f"kết nối CSDL {s['csdl_dang_muon']}/{s['csdl_toi_da']} xếp cổng {s['csdl_xep_cong']}",
            f"đang xử lý {s['dang_xu_ly']}",
            f"việc nặng {s['nang_dang_chay']}/{s['nang_toi_da']}",
            f"đối chiếu {len(s['doi_chieu'])}",
        ]
        return " · ".join(phan)
    except Exception as exc:
        # Chụp trạng thái chỉ để chẩn đoán — hỏng thì vẫn phải ghi được dòng cảnh báo chính
        # Một dòng: màn Nhật ký đọc app.log theo dòng, xuống dòng là mất phần sau
        return f"không lấy được trạng thái ({type(exc).__name__}: {' '.join(str(exc).split())})"


class SlowRequestMiddleware:
    """Đo từ lúc nhận request tới lúc gửi xong byte cuối của phản hồi."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        global _dang_xu_ly
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        _dang_xu_ly += 1
        try:
            await self._do(scope, receive, send)
        finally:
            _dang_xu_ly -= 1

    async def _do(self, scope, receive, send):
        nguong = _nguong_ms(scope.get("path", ""))
        if nguong is None:
            return await self.app(scope, receive, send)

        t0 = time.perf_counter()
        t0_loop = time.monotonic()
        tt = {"ma": 0, "da_ghi": False}

        def ghi(ket_qua: str):
            ms = (time.perf_counter() - t0) * 1000
            if ms >= nguong:
                _log.warning(
                    "Request chậm: %s %s — %d ms (ngưỡng %d ms, %s) | %s",
                    scope.get("method", "?"), scope.get("path", "?"),
                    round(ms), nguong, ket_qua, trang_thai(t0_loop),
                )

        async def send_do(message):
            if message["type"] == "http.response.start":
                tt["ma"] = message["status"]
            await send(message)
            # Chỉ tính khi đã gửi hết thân
            if message["type"] == "http.response.body" and not message.get("more_body"):
                tt["da_ghi"] = True
                ghi(f"HTTP {tt['ma']}")

        try:
            await self.app(scope, receive, send_do)
        except Exception:
            # Lỗi không ai bắt: phản hồi 500 do ServerErrorMiddleware dựng, mà nó nằm
            # NGOÀI middleware này nên không mảnh thân nào đi qua send_do. "Chạy 30 giây
            # rồi sập" đúng là ca cần thấy nhất — không ghi ở đây thì nó vô hình.
            # Cố ý bắt Exception chứ không BaseException: client ngắt giữa chừng ném
            # CancelledError, đó là lỗi đường truyền chứ không phải request chậm.
            if not tt["da_ghi"]:
                ghi("ném ngoại lệ")
            raise
