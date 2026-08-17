"""Đơn nghỉ phép bản PDF — Word chuyển .docx → .pdf, pypdfium2 dán chữ ký + dựng ảnh xem trước.

Chia việc: Word chỉ chạy MỘT lần cho mỗi nội dung đơn (5–7 giây, có cache trong RAM);
chữ ký dán thẳng lên trang PDF (~0,02 giây) nên mỗi lần ký lại không phải gọi Word nữa.
"""
import hashlib
import logging
import os
import subprocess
import tempfile
import threading
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
_word_lock = threading.Lock()


def _kill_pids(pid_file: str) -> None:
    """Diệt WINWORD do lần chuyển đổi này sinh ra — chỉ dùng khi quá hạn."""
    try:
        with open(pid_file, encoding="ascii") as f:
            pids = [p.strip() for p in f.read().split(",") if p.strip()]
    except OSError:
        return
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=15)
            logger.warning("leave_pdf: đã diệt WINWORD treo (pid=%s)", pid)
        except Exception as e:                      # noqa: BLE001 — dọn rác, lỗi không chặn luồng
            logger.warning("leave_pdf: không diệt được pid=%s: %s", pid, e)


def docx_to_pdf(docx_bytes: bytes) -> bytes:
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


def page_png(pdf_bytes: bytes, page_no: int = 0, dpi: int = 110) -> Tuple[bytes, float, float, int]:
    """Trang PDF → (PNG bytes, rộng mm, cao mm, tổng số trang)."""
    import io

    pdfium = _pdfium()
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        n = len(doc)
        page = doc[max(0, min(page_no, n - 1))]
        w_pt, h_pt = page.get_size()
        pil = page.render(scale=dpi / 72).to_pil()
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
