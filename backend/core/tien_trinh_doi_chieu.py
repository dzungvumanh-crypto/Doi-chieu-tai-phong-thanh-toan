"""Chạy một pipeline đối chiếu trong TIẾN TRÌNH RIÊNG thay vì luồng của backend.

Vì sao: Python chỉ cho một luồng chạy mã Python tại một thời điểm (GIL). Pipeline
pandas/Excel chạy bằng `threading.Thread` trong tiến trình web thì giữ GIL gần như
liên tục — request nhẹ như `/api/auth/me` đứng chờ tới lượt. Đo 17/09/2026: 2 luồng
ghi Excel đẩy request nhẹ lên 2,6–3,4 s; 4 tiến trình con thì loop không trễ thêm gì
(card 150 trong Implementation-notes). Kèm theo: tiến trình con hết RAM thì chỉ nó
chết, backend sống; bấm Dừng thì giết được thật; RAM trả hết về hệ điều hành.

Luồng `_run` của service VẪN nằm trong backend, chỉ đổi chỗ gọi pipeline:

    output_path = chay_tach(main_from_dir, ten='Chấm ILO1000',
                            log_callback=log, cancel_event=job['cancel_event'],
                            input_dir=..., output_dir=...)

Luồng đó chủ yếu ngồi chờ ống dẫn (không giữ GIL), chuyển log về đúng dict job cũ —
API, frontend, poll, `phien_doi_chieu` không đổi gì.

Hợp đồng với hàm được chạy tách (thiếu điều nào là hỏng lặng lẽ, nên ghi ra đây):
  1. Hàm ở cấp module, import được theo tên — tiến trình con tự import lại nó.
  2. Nhận `log_callback` và `cancel_event`; mọi tiến độ phải đi qua hai thứ đó (hoặc
     callback khai thêm trong `callbacks=`). Ghi vào biến toàn cục của module (như
     `_progress[...]` của 459901) là ghi vào BẢN SAO trong tiến trình con — màn hình
     đứng ở 0% mà không lỗi nào.
  3. Tham số và kết quả phải pickle được (chuỗi, số, Path, dict...).
  4. Trả `None` khi bị huỷ — bị giết cưỡng bức sau `HAN_DUNG_GIAY` cũng trả `None`.
  5. Không tự tạo tiến trình con (tiến trình daemon không được phép); luồng thì được.
"""
import functools
import importlib
import logging
import multiprocessing as mp
import os
import pickle
import threading
import time
import traceback
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)

# Bấm Dừng → báo pipeline tự dừng; quá hạn này mà chưa xong thì giết tiến trình.
# Pipeline chỉ kiểm cờ huỷ giữa các bước lớn, một bước có thể dài cả phút.
HAN_DUNG_GIAY = 15

# Mã thoát khi tiến trình con tự thoát vì backend (tiến trình cha) đã chết.
_MA_CHA_CHET = 86

_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

# Trần CỨNG bộ nhớ cam kết cho TẤT CẢ tiến trình con đối chiếu cộng lại (Windows Job Object).
# Lưới an toàn cuối, đứng sau bước xét RAM ước tính của `phien_doi_chieu` (ngân sách 11,5 GB):
# ước tính sai thì lượt đang xin thêm bộ nhớ nhận MemoryError, backend và Windows không bị
# kéo theo. Máy chủ 19,9 GB, lúc rảnh dùng 5,2 GB (21/09/2026) → 13 GB vẫn chừa ~1,7 GB.
# Windows không tự giết tiến trình ăn RAM: không có trần này thì cạn bộ nhớ là cả máy
# chậm vì đẩy ra đĩa, và tiến trình xin cấp phát đúng lúc đó — có thể là backend — hỏng.
_TRAN_RAM_MAC_DINH_GB = 13.0


class LoiTienTrinhCon(RuntimeError):
    """Tiến trình con chết không báo kết quả, hoặc lỗi của nó không mang về được."""


class _VetLoiCon(Exception):
    """Chỉ để chở traceback của tiến trình con làm `__cause__` — `traceback.format_exc()`
    ở luồng `_run` in ra cả vết gốc, không chỉ dòng ném lại phía cha."""


def trong_tien_trinh_con() -> bool:
    """True khi đang chạy BÊN TRONG tiến trình con của `chay_tach()`. Dùng khi module phải
    dựng lại trạng thái cục bộ (mục `_progress`) mà chỉ con cần — chạy trong luồng
    (DOI_CHIEU_TIEN_TRINH=0) thì trạng thái thật đã có, dựng thêm là đẻ ra mục "ma"."""
    return os.getenv("KSNB_TIEN_TRINH_CON") == "1"


def bat() -> bool:
    """`DOI_CHIEU_TIEN_TRINH=0` → chạy trong luồng như cũ. Đọc lúc gọi để test đổi được."""
    return (os.getenv("DOI_CHIEU_TIEN_TRINH") or "1").strip() != "0"


def chay_tach(
    ham: Callable[..., Any],
    *,
    ten: str,
    log_callback: Optional[Callable[[str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    callbacks: Optional[dict[str, Callable[..., None]]] = None,
    **kwargs: Any,
) -> Any:
    """Chạy `ham(**kwargs, log_callback=..., cancel_event=...)` ở tiến trình riêng, chờ tới
    khi xong. Trả kết quả; lỗi của `ham` được ném lại đúng kiểu phía cha.

    `callbacks` — callback khác ngoài log (VD `summary_callback` của ACH): trong con là
    hàm đại diện gửi tham số về, cha gọi hàm thật. Kết quả trả về của callback bị bỏ."""
    callbacks = callbacks or {}
    if not bat():
        return ham(**kwargs, **callbacks, log_callback=log_callback, cancel_event=cancel_event)

    dich = _ten_nap_duoc(ham)
    ctx = mp.get_context("spawn")
    nhan, gui = ctx.Pipe(duplex=False)
    ev_huy = ctx.Event()
    ev_gan = ctx.Event()
    # daemon: backend tắt bình thường thì multiprocessing tự giết con, không đứng chờ
    # nó chạy xong (tiến trình không daemon sẽ chặn backend tắt tới hết job).
    p = ctx.Process(target=_tien_trinh_con,
                    args=(dich, kwargs, list(callbacks), gui, ev_huy, ev_gan),
                    name=f"doi-chieu:{ten}", daemon=True)
    t0 = time.monotonic()
    p.start()
    # Con chờ cờ này rồi mới nạp pipeline: bộ nhớ cấp phát TRƯỚC khi vào nhóm nằm ngoài trần
    try:
        _gan_vao_nhom(p.pid, ten)
    except Exception:
        # Lỗi ở đây mà ném ra là con chạy mồ côi, cha không đọc ống nữa — ghi lại, chạy tiếp
        _log.warning("%s: lỗi khi gắn trần bộ nhớ — chạy không có trần cứng", ten, exc_info=True)
    ev_gan.set()
    # Đóng đầu ghi phía cha — còn giữ thì con chết cũng không bao giờ thấy EOF.
    gui.close()
    _log.info("%s: chạy ở tiến trình riêng (PID %s)", ten, p.pid)

    ket_thuc = None
    han_giet = None
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set() and not ev_huy.is_set():
                ev_huy.set()
                han_giet = time.monotonic() + HAN_DUNG_GIAY
            if han_giet is not None and time.monotonic() > han_giet and p.is_alive():
                _log.warning("%s: quá %d s sau lệnh Dừng vẫn chạy — giết tiến trình PID %s",
                             ten, HAN_DUNG_GIAY, p.pid)
                if log_callback:
                    log_callback("[JOB] Pipeline không tự dừng kịp — đã buộc dừng.")
                p.terminate()
                return None

            try:
                if not nhan.poll(0.25):
                    if not p.is_alive() and not nhan.poll(0):
                        break
                    continue
                tin = nhan.recv()
            except (BrokenPipeError, EOFError):
                # Con đã đóng ống. Windows ném BrokenPipeError từ poll() khi ống đã đóng VÀ rỗng
                # (không trả True như Linux) — gặp khi con chết lúc cha đang xử lý tin cuối.
                break
            if tin[0] == "log":
                if log_callback:
                    log_callback(tin[1])
            elif tin[0] == "ghi_log":
                logging.getLogger(tin[2]).log(tin[1], "%s", tin[3])
            elif tin[0] == "cb":
                callbacks[tin[1]](*tin[2], **tin[3])
            else:
                ket_thuc = tin
                break
    finally:
        p.join(timeout=10)
        if p.is_alive():
            p.terminate()
            p.join(timeout=5)
        nhan.close()

    # ── Diễn giải kết quả ──
    giay = time.monotonic() - t0
    if ket_thuc is None:
        if ev_huy.is_set():
            return None
        _log.error("%s: tiến trình PID %s chết sau %.1f s, mã thoát %s, không báo kết quả",
                   ten, p.pid, giay, p.exitcode)
        raise LoiTienTrinhCon(
            f"Tiến trình {ten} dừng bất thường (mã thoát {p.exitcode}) mà không báo kết "
            f"quả — thường do hết bộ nhớ. Backend vẫn chạy bình thường, có thể thử lại."
        )

    loai, noi_dung, ram = ket_thuc[0], ket_thuc[1:-1], ket_thuc[-1]
    ram_txt = (f"{ram[0] / 2**20:,.0f} MB, bộ nhớ cam kết đỉnh {ram[1] / 2**20:,.0f} MB"
               if ram else "không đo được")
    _log.info("%s: tiến trình con xong sau %.1f s, RAM đỉnh %s (%s)", ten, giay, ram_txt, loai)

    if loai == "xong":
        return noi_dung[0]
    du_lieu, mo_ta, vet = noi_dung
    loi = pickle.loads(du_lieu) if du_lieu is not None else None
    # Xét cả VẾT LỖI, không chỉ kiểu: 459901 / Song phương / ACH bắt Exception quanh bước đọc
    # lớn rồi đổi thành "file hỏng", "sai mật khẩu", "sửa file xác nhận" — người dùng sẽ đi
    # kiểm tra file thay vì chờ lượt khác xong. Pickle không giữ __cause__ nên không dựa vào đó
    # được; vết (traceback.format_exc) còn nguyên chuỗi lỗi gốc, cả _ArrayMemoryError của numpy.
    if isinstance(loi, MemoryError) or "MemoryError" in vet:
        # MemoryError thường không kèm thông điệp — để nguyên thì màn hình báo lỗi rỗng
        tran = tran_ram_gb() if os.name == "nt" else 0.0
        _log.warning("%s: tiến trình PID %s hết bộ nhớ (trần chung %s GB)",
                     ten, p.pid, _so_vn(tran) if tran else "tắt")
        vi_sao = (f"vượt bộ nhớ dành cho đối chiếu (trần chung {_so_vn(tran)} GB, hoặc máy chủ "
                  f"đang thiếu RAM)" if tran else "hết bộ nhớ — máy chủ đang thiếu RAM")
        raise LoiTienTrinhCon(
            f"Lượt {ten} {vi_sao}. Có thể do nhiều lượt đối chiếu chạy cùng lúc — chờ một "
            f"lượt xong rồi chạy lại. Backend vẫn chạy bình thường."
        ) from _VetLoiCon(vet)
    if loi is not None:
        raise loi from _VetLoiCon(vet)
    raise LoiTienTrinhCon(mo_ta) from _VetLoiCon(vet)


def _so_vn(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def tran_ram_gb() -> float:
    """Trần cứng (GB) — `DOI_CHIEU_RAM_TRAN_GB`; 0 = tắt. Đọc lúc tạo nhóm (lượt đầu tiên),
    đổi thì khởi động lại backend. Ô trống/sai → mặc định, không làm backend chết."""
    tho = (os.getenv("DOI_CHIEU_RAM_TRAN_GB") or "").strip().replace(",", ".")
    try:
        return max(0.0, float(tho)) if tho else _TRAN_RAM_MAC_DINH_GB
    except ValueError:
        _log.warning("DOI_CHIEU_RAM_TRAN_GB=%r không phải số — dùng %s GB", tho, _TRAN_RAM_MAC_DINH_GB)
        return _TRAN_RAM_MAC_DINH_GB


# ─── Nhóm tiến trình (Windows Job Object) mang trần cứng ───────────────────────

_nhom = None          # handle Job Object, tạo lần đầu cần, giữ suốt đời backend
_khoa_nhom = threading.Lock()


def _winapi():
    import ctypes
    from ctypes import wintypes as w

    class _IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("R", "W", "O", "RB", "WB", "OB")]

    class _CoBan(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]

    class _MoRong(ctypes.Structure):   # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        _fields_ = [("Basic", _CoBan), ("Io", _IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = w.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k32.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    k32.OpenProcess.restype = w.HANDLE
    k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k32.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    k32.CloseHandle.argtypes = [w.HANDLE]
    return ctypes, k32, _MoRong


def _lay_nhom():
    """Job Object dùng chung cho mọi tiến trình con; None nếu tắt / không phải Windows /
    không tạo được (đã ghi cảnh báo)."""
    global _nhom
    if os.name != "nt":
        return None
    with _khoa_nhom:
        if _nhom is not None:
            return _nhom
        tran = tran_ram_gb()
        if not tran:
            return None
        ctypes, k32, _MoRong = _winapi()
        nhom = k32.CreateJobObjectW(None, None)
        if not nhom:
            _log.warning("Không tạo được nhóm giới hạn bộ nhớ đối chiếu (lỗi Windows %d) — "
                         "chạy KHÔNG có trần cứng", ctypes.get_last_error())
            return None
        info = _MoRong()
        info.Basic.LimitFlags = 0x00000200            # JOB_OBJECT_LIMIT_JOB_MEMORY
        info.JobMemoryLimit = int(tran * 2**30)
        if not k32.SetInformationJobObject(nhom, 9, ctypes.byref(info), ctypes.sizeof(info)):
            _log.warning("Không đặt được trần bộ nhớ đối chiếu (lỗi Windows %d) — chạy KHÔNG có "
                         "trần cứng", ctypes.get_last_error())
            k32.CloseHandle(nhom)
            return None
        _nhom = nhom
        _log.info("Trần bộ nhớ chung cho đối chiếu: %s GB", _so_vn(tran))
        return _nhom


def _gan_vao_nhom(pid: int, ten: str) -> None:
    """Gán tiến trình con vào nhóm có trần. Thất bại thì CẢNH BÁO rồi cho chạy tiếp: đây là
    lưới an toàn, không phải điều kiện để đối chiếu được chạy."""
    nhom = _lay_nhom()
    if nhom is None:
        return
    ctypes, k32, _ = _winapi()
    h = k32.OpenProcess(0x0100 | 0x0001, False, pid)   # PROCESS_SET_QUOTA | PROCESS_TERMINATE
    if not h:
        _log.warning("%s: không mở được tiến trình PID %s để gắn trần bộ nhớ (lỗi Windows %d)",
                     ten, pid, ctypes.get_last_error())
        return
    try:
        if not k32.AssignProcessToJobObject(nhom, h):
            _log.warning("%s: không gắn được PID %s vào nhóm trần bộ nhớ (lỗi Windows %d)",
                         ten, pid, ctypes.get_last_error())
    finally:
        k32.CloseHandle(h)


def _ten_nap_duoc(ham: Callable) -> str:
    """'module:qualname' mà tiến trình con import lại đúng hàm này; không được thì ném.

    Cố ý ném chứ không lặng lẽ chạy trong luồng: hàm lồng/lambda lọt vào đây nghĩa
    là cả tính năng quay về tranh GIL mà không ai biết."""
    mod = getattr(ham, "__module__", None)
    qual = getattr(ham, "__qualname__", "")
    if mod and mod != "__main__" and "<" not in qual:
        obj: Any = importlib.import_module(mod)
        for phan in qual.split("."):
            obj = getattr(obj, phan, None)
        if obj is ham:
            return f"{mod}:{qual}"
    raise TypeError(
        f"{ham!r} không import lại được theo tên nên không chạy tách tiến trình được. "
        f"Dùng hàm cấp module, hoặc đặt DOI_CHIEU_TIEN_TRINH=0 (test dùng hàm giả)."
    )


# ─── Phía tiến trình con ─────────────────────────────────────────────────────

class _LogVeCha(logging.Handler):
    """`logging` trong con gửi về cha ghi hộ. Con KHÔNG tự mở logs/app.log: nhiều
    tiến trình cùng xoay một RotatingFileHandler trên Windows là PermissionError."""

    def __init__(self, gui_tin: Callable[..., None]):
        super().__init__(logging.INFO)
        self._gui = gui_tin
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._gui("ghi_log", record.levelno, record.name, self.format(record))
        except Exception:
            self.handleError(record)


def _tien_trinh_con(dich: str, kwargs: dict, ten_cb: list, gui, ev_huy, ev_gan) -> None:
    # Trước mọi import của backend — xem backend/core/config.py (không nạp đè .env)
    os.environ["KSNB_TIEN_TRINH_CON"] = "1"
    _ep_utf8()
    khoa = threading.Lock()   # pipeline log từ nhiều luồng; Connection.send không an toàn luồng

    def gui_tin(*tin):
        with khoa:
            gui.send(tin)

    # Gắn bộ chuyển log TRƯỚC mọi bước khác — cảnh báo của chúng mới tới được app.log
    goc = logging.getLogger()
    goc.handlers[:] = [_LogVeCha(gui_tin)]
    goc.setLevel(logging.INFO)

    try:
        # Trong try: lỗi ở đây phải về cha đúng nguyên nhân, không thành "thường do hết bộ nhớ"
        _canh_cha_chet()
        _ha_uu_tien()
        # Chờ cha gán vào nhóm có trần bộ nhớ rồi mới nạp pipeline (pandas...) — cấp phát
        # trước lúc vào nhóm không bị tính vào trần. Quá 10 s thì chạy tiếp, cha đã cảnh báo.
        ev_gan.wait(10)
        mod, qual = dich.split(":", 1)
        ham: Any = importlib.import_module(mod)
        for phan in qual.split("."):
            ham = getattr(ham, phan)
        dai_dien = {ten: functools.partial(_goi_ve_cha, gui_tin, ten) for ten in ten_cb}
        kq = ham(**kwargs, **dai_dien, log_callback=lambda m: gui_tin("log", m),
                 cancel_event=ev_huy)
        gui_tin("xong", kq, _ram_dinh())
    except Exception as exc:
        vet = traceback.format_exc()
        # Thử cả chiều mở gói: lỗi tự định nghĩa có __init__ đòi tham số đóng gói được
        # mà mở không được — để phía cha vấp thì mất luôn thông báo lỗi.
        try:
            du_lieu = pickle.dumps(exc)
            pickle.loads(du_lieu)
        except Exception:
            du_lieu = None
        gui_tin("loi", du_lieu, f"{type(exc).__name__}: {exc}", vet, _ram_dinh())
    finally:
        gui.close()


def _goi_ve_cha(gui_tin, ten: str, *args, **kw) -> None:
    gui_tin("cb", ten, args, kw)


def _ep_utf8() -> None:
    """Con không import backend/main.py nên không có đoạn ép UTF-8 ở đó. Backend khởi động
    thẳng (không qua run.py → không có PYTHONIOENCODING) thì stdout là cp1252 và mọi
    `print()` tiếng Việt của pipeline (ACH có) ném UnicodeEncodeError — job chết."""
    import sys
    for s in (sys.stdout, sys.stderr):
        if s is not None and (getattr(s, "encoding", "") or "").lower() not in ("utf-8", "utf8"):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError, OSError):
                pass   # stream bị thay/không hỗ trợ — không đáng chặn job


def _canh_cha_chet() -> None:
    """Backend bị `taskkill /F` thì không ai dọn con — nó chạy tiếp, giữ vài GB RAM.
    Luồng canh chờ trên handle của cha, cha chết là con tự thoát."""
    cha = mp.parent_process()
    if cha is None:
        return

    def _canh():
        cha.join()
        os._exit(_MA_CHA_CHET)

    threading.Thread(target=_canh, daemon=True, name="canh-tien-trinh-cha").start()


def _ha_uu_tien() -> None:
    """CPU đầy thì web, Word, SQLite được chạy trước pipeline."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    if not k32.SetPriorityClass(k32.GetCurrentProcess(), _BELOW_NORMAL_PRIORITY_CLASS):
        _log.warning("Không hạ được ưu tiên CPU của tiến trình đối chiếu (lỗi Windows %d)",
                     ctypes.get_last_error())


def _ram_dinh() -> Optional[tuple[int, int]]:
    """(RAM đỉnh, bộ nhớ cam kết đỉnh) — byte — số đo để quyết định nới DOI_CHIEU_MAX_SONG_SONG.

    Cần CẢ HAI: máy thiếu RAM thì Windows cắt working set nên RAM đỉnh đo THẤP đúng lúc số đo
    quan trọng nhất; bộ nhớ cam kết (PeakPagefileUsage) là phần tiến trình thật sự đã chiếm."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class _PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(pmc)
    if k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return pmc.PeakWorkingSetSize, pmc.PeakPagefileUsage
    return None
