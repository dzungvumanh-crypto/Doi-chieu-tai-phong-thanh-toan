"""Lấy mẫu tải máy chủ mỗi phút, lưu vào CSDL — để màn Giám sát xem lại 24 giờ qua.

Bản đầu của màn Giám sát cố ý **không đo gì chạy nền**: mọi con số là ảnh chụp đúng
lúc mở trang. Nhưng người vận hành không ngồi canh 24/24, nên "10h sáng RAM đã lên
93 %" là thứ không cách nào biết được — mở trang lúc 3h chiều thì chỉ thấy 40 %.
Module này đổi điều đó, và đây là bộ đo chạy nền DUY NHẤT của dự án.

Bốn quyết định:

* **Ghi vào bảng CSDL, không phải bộ nhớ.** Restart backend (deploy, mất điện, treo)
  là mất sạch lịch sử — mà vừa restart xong lại đúng là lúc cần xem trước đó đã xảy ra
  chuyện gì. Một dòng/phút, giữ 7 ngày ≈ 10.000 dòng.
* **CPU là trung bình CẢ PHÚT**, tính bằng hiệu hai lần đọc đồng hồ CPU của Windows,
  không phải ảnh chụp 0,3 giây. Đúng câu hỏi "có lúc nào cận ngưỡng".
* **Task chạy trên event loop** (bộ đếm luồng / bể kết nối của anyio chỉ đọc được ở
  đó), phần GHI đẩy sang luồng riêng để không chặn loop.
* **Kết nối CSDL riêng, ngắn**, không mượn bể — cùng lý do với backup/log_cleanup:
  bể là của request, một task nền giữ suất trong đó là lấy mất chỗ của người dùng.
"""
import asyncio
import logging
import sqlite3
import time
from datetime import timedelta

import anyio.to_thread

from backend.database import _vn_now

_log = logging.getLogger(__name__)

CHU_KY_GIAY = 60            # một dòng mỗi phút
GIU_NGAY = 7                # xoá dòng cũ hơn; màn hình chỉ xem 24 giờ, giữ thêm để còn đối chiếu
_DON_MOI = 60               # cứ 60 lần ghi (≈1 giờ) thì dọn một lần

_task: "asyncio.Task | None" = None
_cpu_truoc: "tuple[int, int, int] | None" = None    # đồng hồ CPU lần đọc trước
_moc_truoc: float = 0.0                              # monotonic lần lấy mẫu trước


# ── Chụp một mẫu (gọi TRÊN event loop) ──
def _cpu_trung_binh() -> "float | None":
    """CPU cả máy kể từ lần gọi trước. Lần gọi đầu trả None (chưa có mốc để trừ)."""
    global _cpu_truoc
    from backend.api.monitor import _doc_dong_ho_cpu

    now = _doc_dong_ho_cpu()
    truoc, _cpu_truoc = _cpu_truoc, now
    if not now or not truoc:
        return None
    idle, kernel, user = (now[i] - truoc[i] for i in range(3))
    tong = kernel + user        # kernel time đã GỒM idle
    return round(100 * (tong - idle) / tong, 1) if tong > 0 else None


def chup() -> dict:
    """Một mẫu. Gọi trên event loop — `so_lieu_tai` đọc bộ đếm gắn theo loop."""
    global _moc_truoc
    from backend.api.monitor import _ram_backend, _ram_may
    from backend.core import slow_request

    tai = slow_request.so_lieu_tai(_moc_truoc or time.monotonic() - CHU_KY_GIAY)
    _moc_truoc = time.monotonic()
    ram = _ram_may()

    def pct(dung, toi_da):
        return round(100 * dung / toi_da, 1) if toi_da else None

    return {
        "ts": _vn_now().strftime("%Y-%m-%d %H:%M:%S"),
        "cpu": _cpu_trung_binh(),
        "ram_pct": float(ram["phan_tram"]) if ram else None,
        "ram_backend": _ram_backend(),
        "luong_pct": pct(tai["luong_dung"], tai["luong_toi_da"]),
        "csdl_pct": pct(tai["csdl_dang_muon"], tai["csdl_toi_da"]),
        "nang_pct": pct(tai["nang_dang_chay"], tai["nang_toi_da"]),
        "doi_chieu": len(tai["doi_chieu"]),
        # Đỉnh trong phút vừa rồi, không phải trung bình: một cú chặn 1,2 s bị chia
        # cho 60 giây thành 20 ms là mất đúng thứ cần thấy. `so_lieu_tai` đã đo sẵn
        # đúng khoảng này — gọi lại `tre_loop_ms` là đo hai lần cùng một thứ.
        "loop_ms": tai["loop_chan_max_ms"],
    }


# ── Ghi / dọn (chạy trong luồng riêng) ──
_COT = ("ts", "cpu", "ram_pct", "ram_backend", "luong_pct", "csdl_pct", "nang_pct",
        "doi_chieu", "loop_ms")


def ghi(db_path: str, mau: dict, don: bool = False) -> None:
    con = sqlite3.connect(db_path, timeout=10)
    try:
        con.execute(
            f"INSERT OR REPLACE INTO monitor_samples ({', '.join(_COT)}) "
            f"VALUES ({', '.join('?' * len(_COT))})",
            tuple(mau.get(c) for c in _COT))
        if don:
            han = (_vn_now() - timedelta(days=GIU_NGAY)).strftime("%Y-%m-%d %H:%M:%S")
            con.execute("DELETE FROM monitor_samples WHERE ts < ?", (han,))
        con.commit()
    finally:
        con.close()


# ── Đọc lại cho biểu đồ ──
def doc_lich_su(db: sqlite3.Connection, gio: int = 24, buoc_phut: int = 10) -> "list[dict] | None":
    """Các ô `buoc_phut` phút trong `gio` giờ gần nhất, cũ → mới. None = chưa có bảng.

    Mỗi ô lấy **giá trị lớn nhất** của từng chỉ số, không lấy trung bình: câu hỏi là
    "có lúc nào cận ngưỡng", mà trung bình 10 phút thì một phút chạm 95 % biến thành 45 %.

    Ô không có mẫu nào trả `None` (không phải 0) — backend tắt trong khoảng đó thì
    đường biểu đồ ĐỨT ở đúng chỗ, chứ tô số 0 là nói dối rằng máy lúc ấy rảnh.
    """
    # Ô phải NẰM ĐÚNG LƯỚI `buoc_phut` (10:00, 10:10, …), không phải tính lùi từ phút
    # hiện tại: mở trang lúc 10:37 thì các mốc thành 10:37 / 10:27 / … và KHÔNG mốc nào
    # rơi vào giờ tròn → trục thời gian của cả ba biểu đồ trống trơn (phản biện đo: 90 %
    # số lần mở trang). Cắt xuống lưới còn làm biểu đồ đứng yên giữa các lượt làm mới 30 s.
    now = _vn_now()
    den = now.replace(minute=(now.minute // buoc_phut) * buoc_phut, second=0, microsecond=0)
    tu = den - timedelta(hours=gio)
    try:
        rows = db.execute(
            f"SELECT {', '.join(_COT)} FROM monitor_samples WHERE ts >= ? ORDER BY ts",
            (tu.strftime("%Y-%m-%d %H:%M:%S"),)).fetchall()
    except sqlite3.Error as e:
        # Bảng chưa có (CSDL cũ chưa chạy migration) là bình thường — màn hình tự ẩn biểu đồ.
        # Mọi lỗi khác (CSDL khoá, file hỏng) phải kêu, nếu không biểu đồ trống mà không ai biết vì sao.
        if "no such table" not in str(e).lower():
            _log.warning("Không đọc được lịch sử giám sát", exc_info=True)
        return None

    so_o = (gio * 60) // buoc_phut
    # Nhãn của một ô là mốc ĐẦU ô đó; ô cuối cùng bắt đầu tại `den` và còn đang chạy dở
    moc = [den - timedelta(minutes=buoc_phut * i) for i in range(so_o - 1, -1, -1)]
    o = [{"luc": m.strftime("%H:%M"), **{c: None for c in _COT[1:]}} for m in moc]
    for r in rows:
        d = dict(zip(_COT, r))
        try:
            khi = _vn_now().strptime(d["ts"], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue        # dòng hỏng (sửa tay / CSDL lỗi) — bỏ qua một dòng, không hỏng cả biểu đồ
        # max(0): `den` cắt xuống đầu phút, còn mẫu vừa ghi có phần giây nên "mới hơn
        # den" — không kẹp thì nó rơi ra ngoài mảng và ô cuối luôn trống, đúng cái ô
        # người xem nhìn đầu tiên.
        i = so_o - 1 - int(max(0.0, (den - khi).total_seconds()) // (buoc_phut * 60))
        if not 0 <= i < so_o:
            continue
        for c in _COT[1:]:
            v = d[c]
            if v is not None and (o[i][c] is None or v > o[i][c]):
                o[i][c] = v
    return o


# ── Vòng đời ──
async def _vong_lap(db_path: str) -> None:
    lan = 0
    try:
        chup()                   # mẫu mồi: đặt mốc CPU + mốc thời gian, KHÔNG ghi
    except Exception:
        # NGOÀI try của vòng lặp thì lỗi ở đây giết task ngay lúc khởi động mà không log
        # gì tới tận lúc tắt máy: biểu đồ trống vĩnh viễn trong khi /health vẫn xanh.
        _log.warning("Mẫu mồi của bộ lấy mẫu giám sát lỗi — vẫn chạy tiếp", exc_info=True)
    while True:
        await asyncio.sleep(CHU_KY_GIAY)
        try:
            mau = chup()
            lan += 1
            await anyio.to_thread.run_sync(ghi, db_path, mau, lan % _DON_MOI == 0)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Một lần ghi hỏng (CSDL khoá, đĩa đầy) không được giết cả bộ lấy mẫu —
            # nhưng phải kêu, im lặng ở đây nghĩa là biểu đồ thủng mà không ai biết vì sao
            _log.warning("Lấy mẫu giám sát thất bại một lượt", exc_info=True)


def bat_dau(db_path: str) -> None:
    """Gọi trong lifespan, sau khi event loop đã chạy."""
    global _task
    if _task is not None and not _task.done():
        _task.cancel()           # gọi hai lần: không để task cũ chạy mồ côi
    _task = asyncio.get_running_loop().create_task(_vong_lap(db_path))


async def dung() -> None:
    global _task, _cpu_truoc, _moc_truoc
    if _task is None:
        return
    task, _task = _task, None
    _cpu_truoc, _moc_truoc = None, 0.0
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        if asyncio.current_task().cancelling():
            raise                # chính lúc tắt máy bị huỷ từ ngoài — không nuốt
    except Exception:
        _log.warning("Task lấy mẫu giám sát đã chết vì lỗi", exc_info=True)
