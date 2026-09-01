"""Đơn nghỉ phép bản PDF — Word chuyển .docx → .pdf, pypdfium2 dán chữ ký + dựng ảnh xem trước.

Chia việc ba tầng, mỗi tầng cắt đi một phần thời gian chờ:

1. **Word chạy thường trú** — mở rồi đóng Word tốn ~3,5 giây, còn chuyển một file
   chỉ tốn ~0,25 giây. Giữ một bản Word sống giữa các lần gọi nên chỉ người đầu
   tiên trong ngày phải chờ; những người sau gần như không chờ.
2. **Cache bản PDF gốc trong RAM** — cùng một nội dung đơn thì không gọi Word lại.
3. **Chữ ký dán thẳng lên trang PDF** (~0,02 giây) nên mỗi lần ký lại không đụng Word.
"""
import atexit
import hashlib
import logging
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

PT_PER_MM = 72.0 / 25.4
_PS_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docx_to_pdf.ps1")
_CONVERT_TIMEOUT = 150          # giây — Word khởi động nguội có thể mất 10s
_CACHE_MAX = 24                 # số bản PDF gốc giữ trong RAM


class PdfConvertError(RuntimeError):
    """Word không chuyển được docx → pdf (chưa cài Word, treo, hoặc bị timeout)."""


# ── Word: docx → pdf ─────────────────────────────────────────────────────────
# Serialize: hai request cùng gọi Word một lúc sẽ đẻ ra hai tiến trình WINWORD
# tranh nhau, mà lợi ích song song thì không có (Word vốn không chạy song song tốt).
# Khoá này giữ luôn cả bản Word thường trú bên dưới.
_word_lock = threading.RLock()


def _env_int(ten: str, mac_dinh: int) -> int:
    """Ô để trống trong .env (`WORD_IDLE_SECONDS=`) không được làm chết lúc import."""
    tho = (os.getenv(ten) or "").strip()
    try:
        return max(1, int(tho)) if tho else mac_dinh
    except ValueError:
        return mac_dinh


_SERVER_ON = (os.getenv("WORD_SERVER") or "1").strip().lower() not in ("0", "false", "no")
_IDLE_SECONDS = _env_int("WORD_IDLE_SECONDS", 900)   # rảnh bao lâu thì tắt Word, trả lại RAM
_MAX_JOBS = _env_int("WORD_MAX_JOBS", 100)           # thay Word mới sau ngần này lần chuyển
_READY_TIMEOUT = 90                                  # giây chờ Word báo sẵn sàng


def _kiem_truoc_khi_diet(pid: str) -> Tuple[bool, str]:
    """(diệt được không, lý do). Chỉ diệt WINWORD **không có cửa sổ nào**.

    Hai cái bẫy, cái thứ hai mới là cái nguy hiểm:

    1. PID trong file cũ có thể đã được Windows cấp lại cho tiến trình khác —
       `taskkill /F /PID` không kiểm gì cả, bắn nhầm là mất việc của người ta.
    2. Nếu bản Word ngầm của mình là WINWORD **duy nhất** đang chạy, người vận hành
       double-click một file .docx là Windows điều tài liệu đó vào **đúng tiến trình
       này**. Đo thật: PID không đổi, nhưng `MainWindowHandle` từ 0 nhảy lên khác 0
       và tiêu đề cửa sổ thành tên tài liệu của họ. Diệt lúc đó = giết bản Word có
       người đang gõ dở.

    Có cửa sổ thì để nguyên. Bỏ mặc một WINWORD chạy tiếp còn hơn làm mất bài của
    người ta — và người vận hành nhìn thấy nó trong Task Manager, còn dữ liệu mất
    thì không lấy lại được.
    """
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command",
             f"$p = Get-Process -Id {pid} -ErrorAction SilentlyContinue; "
             "if ($null -eq $p) { 'KHONG_CON' } "
             "elseif ($p.ProcessName -ne 'WINWORD') { 'KHONG_PHAI_WORD' } "
             "elseif ($p.MainWindowHandle -ne 0) { 'CO_CUA_SO ' + $p.MainWindowTitle } "
             "else { 'DIET_DUOC' }"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as e:                          # noqa: BLE001 — không tra được thì KHÔNG diệt
        return False, f"không tra được ({e})"
    ra = (r.stdout or "").strip()
    return ra.startswith("DIET_DUOC"), ra or "không rõ"


def _kill_pids(pid_file: str) -> None:
    """Diệt bản Word ngầm của mình khi nó treo hoặc còn sót từ lần chạy trước."""
    try:
        with open(pid_file, encoding="ascii") as f:
            pids = [p.strip() for p in f.read().split(",") if p.strip()]
    except OSError:
        return
    for pid in pids:
        duoc, ly_do = _kiem_truoc_khi_diet(pid)
        if not duoc:
            if ly_do.startswith("CO_CUA_SO"):
                logger.warning(
                    "leave_pdf: KHÔNG diệt WINWORD pid=%s — nó đang mở cửa sổ %r, nhiều khả "
                    "năng người vận hành đã mở tài liệu vào đúng bản Word này. Để nguyên cho "
                    "họ; nếu đây là bản treo thì tự đóng bằng tay.", pid, ly_do[10:].strip())
            continue
        try:
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=15)
            logger.warning("leave_pdf: đã diệt WINWORD treo (pid=%s)", pid)
        except Exception as e:                      # noqa: BLE001 — dọn rác, lỗi không chặn luồng
            logger.warning("leave_pdf: không diệt được pid=%s: %s", pid, e)


# ── Word thường trú ──────────────────────────────────────────────────────────
_SERVER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docx_pdf_server.ps1")
_STALE_PID_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "word_server.pid",
)


class _ServerDown(Exception):
    """Word thường trú không dùng được lúc này — lui về cách chạy một lần."""


class _WordServer:
    """Một tiến trình PowerShell giữ sẵn một bản Word, nhận việc qua stdin.

    Mọi phương thức đều được gọi khi ĐANG giữ `_word_lock`, nên bên trong không
    cần khoá riêng.
    """

    def __init__(self):
        self.proc = None
        self.dir = None
        self.lines = None       # hàng đợi từng dòng stdout do luồng bơm đẩy vào
        self.jobs = 0
        self.timer = None
        self.seq = 0

    # ── Vòng đời ──
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        if self.alive():
            return
        self.stop()                                  # dọn xác lần trước nếu có
        if not os.path.exists(_SERVER_SCRIPT):
            raise _ServerDown("thiếu docx_pdf_server.ps1")
        # Lần chạy trước bị tắt cứng (taskkill, mất điện) để lại WINWORD mồ côi: nó
        # vô hình, không ai đóng, và cứ mỗi lần khởi động lại thêm một cái nữa.
        _kill_pids(_STALE_PID_FILE)
        try:
            os.makedirs(os.path.dirname(_STALE_PID_FILE), exist_ok=True)
        except OSError:
            pass
        self.dir = tempfile.mkdtemp(prefix="wordsrv_")
        try:
            self.proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", _SERVER_SCRIPT, "-PidFile", _STALE_PID_FILE],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as e:
            self.proc = None
            raise _ServerDown(f"không chạy được PowerShell: {e}") from e
        self.lines = queue.Queue()
        threading.Thread(target=self._bom_stdout, args=(self.proc, self.lines),
                         name="word-stdout", daemon=True).start()
        if self._doc(_READY_TIMEOUT) != "READY":
            self.stop()
            raise _ServerDown("Word không báo sẵn sàng")
        self.jobs = 0
        logger.info("leave_pdf: đã bật Word thường trú (powershell pid=%s)", self.proc.pid)

    @staticmethod
    def _bom_stdout(proc, q) -> None:
        """Đọc stdout ở luồng riêng: `readline()` trên Windows không có hạn giờ —
        gọi thẳng mà Word treo là kẹt luôn luồng đang phục vụ request."""
        try:
            for line in proc.stdout:
                q.put(line.strip())
        except Exception:                            # noqa: BLE001 — ống đóng giữa chừng
            pass
        finally:
            q.put(None)                              # None = tiến trình đã chết

    def _doc(self, timeout: float):
        """Một dòng trả lời; None nếu tiến trình chết, chuỗi rỗng nếu quá hạn."""
        try:
            return self.lines.get(timeout=timeout)
        except queue.Empty:
            return ""

    def stop(self) -> None:
        self.huy_hen()
        p, self.proc = self.proc, None
        if p is not None:
            try:
                if p.poll() is None:
                    p.stdin.write("QUIT\n")
                    p.stdin.flush()
                    p.wait(timeout=15)
            except Exception:                        # noqa: BLE001 — đằng nào cũng kill bên dưới
                pass
            if p.poll() is None:
                _kill_pids(_STALE_PID_FILE)
                try:
                    p.kill()
                except Exception:                    # noqa: BLE001
                    pass
            for s in (p.stdin, p.stdout):
                try:
                    s.close()
                except Exception:                    # noqa: BLE001
                    pass
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)
        self.dir = None
        self.lines = None

    # ── Hẹn giờ tắt khi rảnh ──
    def huy_hen(self) -> None:
        t, self.timer = self.timer, None
        if t is not None:
            t.cancel()

    def hen_tat(self) -> None:
        self.huy_hen()
        t = threading.Timer(_IDLE_SECONDS, _tat_khi_ranh)
        t.daemon = True
        t.args = (t,)                                # tự truyền mình vào để so danh tính
        self.timer = t
        t.start()

    # ── Chuyển đổi ──
    def convert(self, docx_bytes: bytes) -> bytes:
        self.start()
        self.huy_hen()
        self.seq += 1
        src = os.path.join(self.dir, f"j{self.seq}.docx")
        dst = os.path.join(self.dir, f"j{self.seq}.pdf")
        with open(src, "wb") as f:
            f.write(docx_bytes)
        try:
            try:
                self.proc.stdin.write(f"{src}|{dst}\n")
                self.proc.stdin.flush()
            except (OSError, ValueError) as e:
                self.stop()
                raise _ServerDown(f"mất kết nối tới Word: {e}") from e

            ans = self._doc(_CONVERT_TIMEOUT)
            if ans is None:
                self.stop()
                raise _ServerDown("Word thường trú tắt giữa chừng")
            if ans == "":
                # Treo thật (thường là Word đang hiện hộp thoại chờ trả lời). Chạy lại
                # bằng đường cũ cũng treo y thế, nên báo lỗi luôn thay vì bắt chờ hai lượt.
                self.stop()
                raise PdfConvertError(
                    f"Word không phản hồi sau {_CONVERT_TIMEOUT}s — có thể đang hiện hộp thoại chờ trả lời"
                )
            if not ans.startswith("OK"):
                err = ans[4:].strip() if ans.startswith("ERR") else ans
                logger.error("leave_pdf: Word chuyển đổi thất bại — %s", err[:400])
                raise PdfConvertError(f"Word chuyển đổi thất bại: {err[:400] or 'không rõ nguyên nhân'}")
            if not os.path.exists(dst):
                raise PdfConvertError("Word báo xong nhưng không thấy file PDF")
            with open(dst, "rb") as f:
                return f.read()
        finally:
            for f_ in (src, dst):
                try:
                    os.remove(f_)
                except OSError:
                    pass
            self.jobs += 1
            if self.alive():
                # Word chạy lâu sẽ phình bộ nhớ và thỉnh thoảng dở chứng — thay bản mới
                # định kỳ, giá phải trả chỉ là ~1 giây cho người kế tiếp.
                if self.jobs >= _MAX_JOBS:
                    logger.info("leave_pdf: thay Word mới sau %d lần chuyển đổi", self.jobs)
                    self.stop()
                else:
                    self.hen_tat()


_server = _WordServer()


def _tat_khi_ranh(t) -> None:
    with _word_lock:
        # `Timer.cancel()` không chặn được callback đã bắt đầu chạy; so danh tính để
        # lượt hẹn cũ không tắt nhầm bản Word vừa được dùng lại.
        if _server.timer is t and _server.alive():
            logger.info("leave_pdf: Word rảnh %ds — tắt để trả lại bộ nhớ", _IDLE_SECONDS)
            _server.stop()


_WARM_COOLDOWN = 60         # giây nghỉ giữa hai lần bật sẵn thất bại
_warm_fail_at = 0.0


def warm_up() -> bool:
    """Bật sẵn Word để lần xem trước đầu tiên khỏi chờ ~3,5 giây khởi động.

    Gọi lúc người dùng mở màn nghỉ phép: họ còn điền form vài chục giây, thừa đủ
    để Word sẵn sàng trước khi bấm xem trước.
    """
    global _warm_fail_at
    if not _SERVER_ON:
        return False
    with _word_lock:
        if _server.alive():
            return True
        # Máy chủ không có Word: mỗi lượt bật sẵn vẫn đẻ một tiến trình PowerShell.
        # Ai cũng mở màn nghỉ phép thì thành đập liên tục vô ích — nghỉ một phút
        # sau mỗi lần hỏng. Người bấm "xem trước" thật vẫn đi đường riêng, không
        # bị cửa này chặn.
        if time.monotonic() - _warm_fail_at < _WARM_COOLDOWN:
            return False
        try:
            _server.start()
            _server.hen_tat()
            return True
        except _ServerDown as e:
            _warm_fail_at = time.monotonic()
            logger.info("leave_pdf: chưa bật sẵn được Word — %s", e)
            return False


def shutdown() -> None:
    """Đóng Word thường trú khi backend tắt."""
    with _word_lock:
        _server.stop()


atexit.register(shutdown)


def _docx_to_pdf_mot_lan(docx_bytes: bytes) -> bytes:
    """Đường lui: mở Word — chuyển — đóng Word, mỗi lần gọi một lượt (~4 giây).

    Giữ lại vì Word thường trú có thể không dựng được (chính sách chạy script,
    quyền COM, bản Word lạ) — thà chậm còn hơn tính năng chết hẳn.
    """
    if not os.path.exists(_PS_SCRIPT):
        raise PdfConvertError("Thiếu script chuyển đổi docx_to_pdf.ps1")

    tmpdir = tempfile.mkdtemp(prefix="leavepdf_")
    src = os.path.join(tmpdir, "don.docx")
    dst = os.path.join(tmpdir, "don.pdf")
    pid_file = os.path.join(tmpdir, "word.pid")
    with open(src, "wb") as f:
        f.write(docx_bytes)

    try:
        with _word_lock:
            try:
                proc = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                     "-File", _PS_SCRIPT, "-In", src, "-Out", dst, "-PidFile", pid_file],
                    capture_output=True, text=True, timeout=_CONVERT_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                _kill_pids(pid_file)
                raise PdfConvertError(
                    f"Word không phản hồi sau {_CONVERT_TIMEOUT}s — có thể đang hiện hộp thoại chờ trả lời"
                )
        if proc.returncode != 0 or not os.path.exists(dst):
            err = (proc.stderr or proc.stdout or "").strip()[:400]
            logger.error("leave_pdf: Word chuyển đổi thất bại — %s", err)
            raise PdfConvertError(f"Word chuyển đổi thất bại: {err or 'không rõ nguyên nhân'}")
        with open(dst, "rb") as f:
            return f.read()
    finally:
        for p in (src, dst, pid_file):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass


def docx_to_pdf(docx_bytes: bytes) -> bytes:
    if _SERVER_ON:
        with _word_lock:
            try:
                return _server.convert(docx_bytes)
            except _ServerDown as e:
                # Không dựng được / mất kết nối — KHÔNG phải lỗi của file đơn, nên
                # vẫn còn cửa chạy lại bằng đường cũ.
                logger.warning("leave_pdf: Word thường trú hỏng (%s) — lui về cách chạy một lần", e)
    return _docx_to_pdf_mot_lan(docx_bytes)


# ── Cache bản PDF gốc (chưa có chữ ký) ───────────────────────────────────────
_cache: "OrderedDict[str, bytes]" = OrderedDict()
_cache_lock = threading.Lock()


def cache_key(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()


def base_pdf(key: str, build_docx) -> bytes:
    """PDF gốc theo `key`; chỉ gọi Word khi chưa có trong cache.

    `build_docx` là hàm không tham số trả về bytes .docx — truyền hàm chứ không
    truyền sẵn bytes để khi trúng cache thì khỏi phải dựng docx.
    """
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit
    pdf = docx_to_pdf(build_docx())
    with _cache_lock:
        _cache[key] = pdf
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return pdf


def drop_cache(prefix: str = "") -> None:
    with _cache_lock:
        for k in [k for k in _cache if not prefix or k.startswith(prefix)]:
            _cache.pop(k, None)


# ── pypdfium2: render + dán ảnh ──────────────────────────────────────────────
def _pdfium():
    try:
        import pypdfium2 as pdfium
    except ImportError as e:
        raise PdfConvertError(
            "Chưa cài thư viện pypdfium2 — chạy: pip install -r requirements.txt"
        ) from e
    return pdfium


def _bo_mau_thua(pil):
    """Ảnh không có màu thì lưu 1 kênh thay vì 3 — nhẹ đi hơn hai lần rưỡi.

    Phiếu nghỉ phép in đen trắng, nhưng pdfium luôn trả ảnh RGB nên ba kênh giống
    hệt nhau vẫn bị nén và gửi đủ ba. Ảnh xem trước đi qua websocket dưới dạng
    base64 nhúng thẳng vào HTML, nên 107KB hay 43KB là khác biệt người dùng thấy
    được — nhất là khi vào từ mạng chậm.

    So từng kênh chứ không đoán theo mẫu đơn: mẫu nào có logo hoặc dấu đỏ thì giữ
    nguyên màu. Phép so tốn dưới 1 mili-giây.
    """
    if pil.mode not in ("RGB", "RGBA"):
        return pil
    try:
        from PIL import ImageChops
        r, g, b = pil.convert("RGB").split()
        if (ImageChops.difference(r, g).getbbox() is None
                and ImageChops.difference(g, b).getbbox() is None):
            return pil.convert("L")
    except Exception as e:                          # noqa: BLE001 — không bỏ được màu thì cứ gửi bản màu
        logger.warning("leave_pdf: không kiểm được màu ảnh xem trước: %s", e)
    return pil


def page_png(pdf_bytes: bytes, page_no: int = 0, dpi: int = 110) -> Tuple[bytes, float, float, int]:
    """Trang PDF → (PNG bytes, rộng mm, cao mm, tổng số trang)."""
    import io

    pdfium = _pdfium()
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        n = len(doc)
        page = doc[max(0, min(page_no, n - 1))]
        w_pt, h_pt = page.get_size()
        pil = _bo_mau_thua(page.render(scale=dpi / 72).to_pil())
        buf = io.BytesIO()
        pil.save(buf, "PNG")
        return buf.getvalue(), w_pt / PT_PER_MM, h_pt / PT_PER_MM, n
    finally:
        doc.close()


def find_text_box(pdf_bytes: bytes, needle: str, match_case: bool = False) -> Optional[dict]:
    """Tìm chuỗi trong PDF → khung chữ nhật (mm, gốc toạ độ góc TRÊN-TRÁI trang).

    Dùng để đoán chỗ đặt chữ ký: neo theo nhãn "NGƯỜI ĐỀ NGHỊ" / "GIÁM ĐỐC TTTT"
    trên chính bản in, nên mẫu đơn đổi bố cục thì vị trí gợi ý vẫn đi theo.
    """
    pdfium = _pdfium()
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        for pno in range(len(doc)):
            page = doc[pno]
            _, h_pt = page.get_size()
            tp = page.get_textpage()
            searcher = tp.search(needle, match_case=match_case, match_whole_word=False)
            idx = searcher.get_next()
            if idx is None:
                continue
            rects = [tp.get_rect(i) for i in range(tp.count_rects(idx[0], idx[1]))]
            rects = [r for r in rects if r]
            if not rects:
                continue
            left = min(r[0] for r in rects)
            right = max(r[2] for r in rects)
            top = max(r[3] for r in rects)
            bottom = min(r[1] for r in rects)
            return {
                "page": pno,
                "x_mm": left / PT_PER_MM,
                "y_mm": (h_pt - top) / PT_PER_MM,
                "w_mm": (right - left) / PT_PER_MM,
                "h_mm": (top - bottom) / PT_PER_MM,
            }
        return None
    finally:
        doc.close()


def stamp(pdf_bytes: bytes, placements: List[dict]) -> bytes:
    """Dán ảnh chữ ký lên PDF.

    placements: [{page, x_mm, y_mm, w_mm, h_mm, image: bytes}] — x/y là góc TRÊN-TRÁI
    của khung ảnh tính từ góc trên-trái trang (đúng hệ toạ độ của trình duyệt);
    PDF đếm từ góc dưới-trái nên phải lật trục y ở đây.
    """
    import io

    if not placements:
        return pdf_bytes
    pdfium = _pdfium()
    try:
        from PIL import Image
    except ImportError as e:
        raise PdfConvertError("Chưa cài thư viện Pillow — chạy: pip install -r requirements.txt") from e

    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        n = len(doc)
        # Giữ nguyên MỘT đối tượng trang cho mỗi số trang: doc[i] nạp lại trang mới
        # mỗi lần gọi, gen_content() trên đối tượng khác sẽ không thấy ảnh vừa chèn
        # → PDF lưu ra trông y như chưa ký, không báo lỗi gì.
        pages: dict = {}
        for pl in placements:
            pno = max(0, min(int(pl.get("page") or 0), n - 1))
            page = pages.setdefault(pno, doc[pno])
            _, h_pt = page.get_size()
            img = Image.open(io.BytesIO(pl["image"]))
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            obj = pdfium.PdfImage.new(doc)
            obj.set_bitmap(pdfium.PdfBitmap.from_pil(img))
            w_pt = float(pl["w_mm"]) * PT_PER_MM
            hh_pt = float(pl["h_mm"]) * PT_PER_MM
            x_pt = float(pl["x_mm"]) * PT_PER_MM
            y_pt = h_pt - (float(pl["y_mm"]) + float(pl["h_mm"])) * PT_PER_MM
            obj.set_matrix(pdfium.PdfMatrix().scale(w_pt, hh_pt).translate(x_pt, y_pt))
            page.insert_obj(obj)
        for page in pages.values():
            page.gen_content()
        out = io.BytesIO()
        doc.save(out)
        return out.getvalue()
    finally:
        doc.close()


def png_size(image: bytes) -> Tuple[int, int]:
    """(rộng, cao) tính bằng pixel — để giữ đúng tỉ lệ khung chữ ký."""
    import io

    try:
        from PIL import Image
    except ImportError:
        return (0, 0)
    try:
        with Image.open(io.BytesIO(image)) as im:
            return im.size
    except Exception as e:                          # noqa: BLE001 — ảnh hỏng thì dùng tỉ lệ mặc định
        logger.warning("leave_pdf: không đọc được kích thước ảnh chữ ký: %s", e)
        return (0, 0)
