"""Lớp job/progress cho Đối chiếu OSB — bọc ngoài `doi_chieu_osb.pipeline.chay_doi_chieu_osb()`
(logic đối chiếu THUẦN, không biết gì về HTTP/threading/progress).

Khuôn "job chạy nền + polling tiến độ" mirror `cham459901_service.py` — dùng chung cho MỌI module
đối chiếu trong dự án kể cả module xử lý NHANH: `phien_doi_chieu.gianh_cho()` là khoá mutex CHUNG
chặn 2 lượt chạy cùng lúc (module nào cũng cần, không phải vì lý do quy mô), và `threading.Thread`
tránh chiếm threadpool 40 token dùng chung của Starlette. Bản thân phép đối chiếu chạy ở
tiến trình riêng qua `chay_tach()` (backend/core/tien_trinh_doi_chieu.py) để không tranh GIL.

Job này đo thật chỉ vài giây (không như ACH/459901 chạy nhiều phút) — KHÔNG cần
`cancel_progress()`/checkpoint giữa chừng như cham459901, nhưng VẪN PHẢI qua
`phien_doi_chieu.gianh_cho("doi_chieu_osb")` để không chạy chồng 2 lượt (mutex chặn theo MODULE,
không phải theo thời lượng chạy)."""

import logging
import shutil
import time
import uuid
from pathlib import Path

from backend.core.config import BASE_DIR
from backend.core.don_dep import moc_don_gan_nhat
from backend.core.tien_trinh_doi_chieu import chay_tach, trong_tien_trinh_con
from backend.services.doi_chieu_osb.pipeline import chay_doi_chieu_osb

TEMP_DIR = BASE_DIR / "data" / "temp_doi_chieu_osb"

log = logging.getLogger(__name__)

# ─── In-memory progress store ─────────────────────────────────────────────────
# key = task_token; value = {pct, msg, done, error, cancelled, result, _ts}
_progress: dict[str, dict] = {}

_TTL_DANG_CHAY = 4 * 3600  # mirror cham459901_service — 1 lượt bỏ dở quá lâu coi như đã chết


def init_progress() -> str:
    """Khởi tạo entry theo dõi tiến độ, trả về task_token."""
    task_token = str(uuid.uuid4())
    _progress[task_token] = {
        "pct": 0, "msg": "Đang khởi tạo...",
        "done": False, "error": None, "cancelled": False, "result": None,
        "_ts": time.time(),
    }
    return task_token


def _thu_muc_upload(task_token: str) -> Path:
    """Đường dẫn DUY NHẤT của thư mục upload một lượt — mọi chỗ tạo/xoá đều đi qua đây."""
    return TEMP_DIR / f"upload_{task_token}"


def tao_thu_muc_upload(task_token: str) -> Path:
    """Thư mục nhận file tải lên của một lượt: `data/temp_doi_chieu_osb/upload_<token>/`."""
    d = _thu_muc_upload(task_token)
    d.mkdir(parents=True, exist_ok=True)
    return d


def bo_luot(task_token: str) -> None:
    """Huỷ một lượt chưa chạy (upload lỗi/đứt): xoá thư mục và entry tiến độ."""
    shutil.rmtree(_thu_muc_upload(task_token), ignore_errors=True)
    _progress.pop(task_token, None)


def _cleanup_old_results(cutoff: float | None = None) -> None:
    """Xóa thư mục `upload_<token>`/kết quả và progress entry cũ hơn `cutoff`.

    Mirror `cham459901_service._cleanup_old_results()` — mốc mặc định là 23h gần nhất đã trôi
    qua (`backend/core/don_dep.py`). Trước khi có hàm này, `bo_luot()` chỉ được gọi ở nhánh
    upload hỏng — một lượt chạy THÀNH CÔNG để nguyên `upload_<token>/` (file GL02 zip gốc + các
    file OSB) trên đĩa vĩnh viễn, không ai dọn (review Khánh, PR #103)."""
    cutoff = moc_don_gan_nhat() if cutoff is None else cutoff

    if TEMP_DIR.exists():
        for sub in TEMP_DIR.iterdir():
            try:
                if sub.is_dir() and sub.stat().st_mtime < cutoff:
                    shutil.rmtree(sub)
            except OSError as e:
                log.warning("Không xóa được %s: %s", sub, e)

    stale = [k for k, v in list(_progress.items()) if v.get("_ts", 0) < cutoff]
    for k in stale:
        _progress.pop(k, None)


def get_progress(task_token: str) -> dict | None:
    p = _progress.get(task_token)
    if p is None:
        return None
    return {k: v for k, v in p.items() if not k.startswith("_")}


def luot_dang_chay() -> dict | None:
    """Lượt Đối chiếu OSB đang chiếm máy chủ, None nếu rảnh — báo cáo cho `phien_doi_chieu`."""
    now = time.time()
    for token, p in list(_progress.items()):
        if p.get("done"):
            continue
        if now - p.get("_ts", 0) > _TTL_DANG_CHAY:
            continue
        return {
            "job_id": token, "status": "running",
            "tuoi_giay": max(0, int(now - p.get("_ts", now))),
        }
    return None


def _set_prog(task_token: str | None, pct: int | None = None, msg: str | None = None) -> None:
    if task_token and task_token in _progress:
        p = _progress[task_token]
        if pct is not None:
            p["pct"] = pct
        if msg is not None:
            p["msg"] = msg
        # Trong tiến trình con: `_progress` là bản sao, phải gửi tiến độ về backend
        gui_ve = p.get("_gui_ve")
        if gui_ve:
            gui_ve(pct, msg)


def run_process(
    gl02_path: Path, osb_paths: list[Path], ma_tk: str, ngay: str, task_token: str,
) -> None:
    """Chạy `process()` — cập nhật progress và bắt lỗi. Chạy trong `threading.Thread` riêng.

    `finally` xoá thư mục `upload_<token>` (file GL02 zip + OSB xlsx vừa nhận) SAU khi xử lý
    xong, kể cả nhánh THÀNH CÔNG — trước đó chỉ nhánh upload hỏng mới được `bo_luot()` dọn
    (review Khánh, PR #103). `process()` đã đọc hết dữ liệu cần vào RAM/kết quả xuất ra
    `TEMP_DIR/<result_token>/` trước khi hàm này trả về, nên xoá thư mục upload lúc này an toàn.

    Thư mục xoá dựng từ `task_token`, KHÔNG suy ra từ `gl02_path.parent`: nếu sau này có đường
    chạy thẳng từ thư mục trên máy chủ (như Chấm 459901), `parent` là thư mục dữ liệu thật và
    `rmtree` sẽ xoá sạch nó."""
    upload_dir = _thu_muc_upload(task_token)
    p = _progress.get(task_token, {})

    def _cap_nhat(pct: int | None, msg: str | None) -> None:
        if pct is not None:
            p["pct"] = pct
        if msg is not None:
            p["msg"] = msg

    try:
        # Tiến trình riêng (`chay_tach`): job chỉ vài giây nhưng suốt mấy giây đó giữ GIL.
        # Kết quả cuối ghi vào `_progress` ở dưới — `process` trong con chỉ ghi được bản sao.
        result = chay_tach(
            _xu_ly_tach, ten="Đối chiếu OSB",
            gl02_path=gl02_path, osb_paths=osb_paths, ma_tk=ma_tk, ngay=ngay,
            task_token=task_token, callbacks={"tien_do_callback": _cap_nhat},
        )
        if task_token in _progress:
            _progress[task_token].update({
                "pct": 100, "msg": "Hoàn thành!", "done": True, "result": result,
            })
    except ValueError as e:
        # Lỗi do chính file/tham số người dùng đưa vào (thiếu cột, sai TK, ...) — không phải
        # lỗi hệ thống, thông báo hiển thị thẳng cho người dùng (mirror InputError của
        # cham459901_service.py — module này chưa cần tách lớp riêng, mọi lỗi nghiệp vụ trong
        # doi_chieu_osb đều raise ValueError thẳng).
        log.warning("doi_chieu_osb: lỗi đầu vào [%s]: %s", task_token, e)
        if task_token in _progress:
            _progress[task_token].update({"done": True, "error": str(e), "msg": str(e)})
    except Exception as e:
        log.error("doi_chieu_osb: lỗi xử lý [%s]: %s", task_token, e, exc_info=True)
        if task_token in _progress:
            _progress[task_token].update({
                "done": True, "error": str(e), "msg": "Lỗi xử lý — xem log server",
            })
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)


def _xu_ly_tach(
    gl02_path: Path, osb_paths: list[Path], ma_tk: str, ngay: str, task_token: str,
    log_callback, cancel_event, tien_do_callback,
) -> dict:
    """Điểm vào của `chay_tach` — trong tiến trình con dựng mục `_progress` cục bộ để
    `_set_prog` gửi tiến độ về backend (chỉ trong con; xem `cham459901_service._xu_ly_tach`).
    Không có nút Dừng nên `cancel_event` bỏ qua."""
    if trong_tien_trinh_con():
        _progress[task_token] = {
            "pct": 0, "msg": "", "done": False, "error": None, "cancelled": False,
            "result": None, "_ts": time.time(), "_gui_ve": tien_do_callback,
        }
    return process(gl02_path, osb_paths, ma_tk, ngay, task_token)


def process(
    gl02_path: Path, osb_paths: list[Path], ma_tk: str, ngay: str,
    task_token: str | None = None,
) -> dict:
    """Chạy `chay_doi_chieu_osb()` thật, LƯU `zip_bytes` xuống đĩa trong thư mục job (không giữ
    trong RAM lâu), trả metadata gọn cho response `/progress`."""
    _cleanup_old_results()
    t0 = time.time()
    _set_prog(task_token, 10, "Đang đối chiếu GL02 <-> OSB...")

    def _log(msg: str) -> None:
        _set_prog(task_token, msg=msg)

    ket_qua = chay_doi_chieu_osb(gl02_path, osb_paths, ma_tk, ngay, log_callback=_log)

    _set_prog(task_token, 90, "Đang lưu kết quả...")
    result_token = str(uuid.uuid4())
    out_dir = TEMP_DIR / result_token
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ket_qua.zip").write_bytes(ket_qua["zip_bytes"])

    return {
        "token": result_token,
        "ma_tk": ma_tk,
        "ngay": ngay,
        "no_gl02_rows": len(ket_qua["no"]["gl02"]),
        "no_osb_rows": len(ket_qua["no"]["osb"]),
        "co_gl02_rows": len(ket_qua["co"]["gl02"]),
        "co_osb_rows": len(ket_qua["co"]["osb"]),
        "canh_bao": ket_qua["canh_bao"],
        "elapsed_s": round(time.time() - t0, 1),
    }


# Đăng ký với chốt chặn dùng chung — thiếu dòng này là job chạy ngoài trần
# DOI_CHIEU_MAX_SONG_SONG mà không ai biết (xem backend/core/phien_doi_chieu.py).
from backend.core.phien_doi_chieu import dang_ky_nguon  # noqa: E402

dang_ky_nguon("doi_chieu_osb", "Đối chiếu OSB", luot_dang_chay)
