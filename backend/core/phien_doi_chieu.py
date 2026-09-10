"""Chốt chặn số lượt đối chiếu nặng chạy cùng lúc — dùng chung cho 4 module.

Vì sao cần: ACH, Chấm ILO1000, Đối chiếu Song phương và Chấm 459901 đều nạp file
bằng pandas trong chính tiến trình backend. Đo được pandas giữ **5,3 lần** kích
thước file khi đọc `dtype=str` (đỉnh 5,9×), mà trần một lượt upload là 500 MB.

Cả bốn chạy trên `threading.Thread` tự tạo, **không** đi qua `run_heavy()` — nên
`MAX_HEAVY` trong `backend/core/concurrency.py` KHÔNG ràng buộc chúng. Trước file
này, thứ duy nhất chặn là chốt riêng của ACH; ba module kia vào thẳng, và ACH
cũng chỉ tự canh mình nên chạy ACH cùng lúc với Song phương vẫn lọt.

Đã xảy ra thật: 26/08/2026 hai pipeline pandas cùng ôm vài trăm MB làm backend
hết RAM và chết giữa lúc đang nhận file của lượt thứ hai — người dùng chỉ thấy
"[WinError 10054]".

Hai luật, cố ý khác nhau:

  1. **Cùng một module: luôn 1 lượt.** Người vận hành xác nhận cùng một menu thì
     thực tế chỉ một người chạy. Đây là luật cứng, không nới được — hai lượt cùng
     module còn tranh nhau cả thư mục tạm chứ không riêng RAM.

  2. **Toàn hệ thống: `MAX_SONG_SONG` lượt.** Khác menu thì vài người chạy song
     song là chuyện bình thường, nên KHÔNG khoá về 1. Mặc định 3: đủ cho nếp làm
     việc thật, mà vẫn chặn trường hợp cả bốn module cùng chạy (worst case
     4 × 500 MB × 5,3 ≈ 10 GB trên máy 20 GB — sát quá).

Trạng thái job vẫn nằm ở từng service, file này KHÔNG giữ bản sao: mỗi module tự
khai một hàm báo cáo "tôi đang bận với job nào". Hai nguồn sự thật về cùng một
job là kiểu lỗi tự sinh ra lệch pha, không đáng đổi lấy chút tiện.
"""
import contextlib
import logging
import os
import threading
from typing import Callable, Iterator, Optional

_log = logging.getLogger(__name__)


def _doc_so(ten_bien: str, mac_dinh: int) -> int:
    """Ô để trống trong .env (`DOI_CHIEU_MAX_SONG_SONG=`) làm `int("")` ném
    ValueError ngay lúc import — backend không lên mà lỗi không nhắc gì tới .env."""
    tho = (os.getenv(ten_bien) or "").strip()
    try:
        return max(1, int(tho)) if tho else mac_dinh
    except ValueError:
        _log.warning("%s=%r không phải số — dùng mặc định %d", ten_bien, tho, mac_dinh)
        return mac_dinh


MAX_SONG_SONG = _doc_so("DOI_CHIEU_MAX_SONG_SONG", 3)

# ma_module -> (tên hiển thị, hàm báo cáo job đang chiếm máy chủ)
_NGUON: dict[str, tuple[str, Callable[[], Optional[dict]]]] = {}
_lock = threading.Lock()


def dang_ky_nguon(ma: str, ten: str, bao_cao: Callable[[], Optional[dict]]) -> None:
    """Khai một module đối chiếu. Gọi lúc import service.

    `bao_cao()` trả dict mô tả job đang chiếm máy chủ (tối thiểu có `job_id`,
    `status`; thêm `tuoi_giay` nếu biết), hoặc None khi module đó rảnh.
    """
    with _lock:
        _NGUON[ma] = (ten, bao_cao)


def dang_chay() -> list[dict]:
    """Các lượt đang chiếm máy chủ, mọi module. Danh sách rỗng nghĩa là rảnh."""
    with _lock:
        nguon = list(_NGUON.items())
    ra = []
    for ma, (ten, bao_cao) in nguon:
        try:
            job = bao_cao()
        except Exception as exc:
            # Một module báo cáo lỗi KHÔNG được làm chết cửa kiểm tra của cả bốn.
            # Nhưng phải kêu: đếm hụt nghĩa là chốt nới ra âm thầm.
            _log.error("Module đối chiếu %r không báo cáo được trạng thái: %s", ma, exc)
            continue
        if job:
            ra.append({"module": ma, "ten_module": ten, **job})
    return ra


def kiem_tra(ma_module: str) -> Optional[dict]:
    """None nếu `ma_module` được phép chạy; dict mô tả chỗ nghẽn nếu bị chặn.

    Dict trả về luôn có `message` (câu nói thẳng cho người dùng) và `dang_chay`
    (danh sách lượt đang chiếm máy). Khi chỗ nghẽn là chính module đó, có thêm
    `job` — đúng hình dạng mà trang ACH đang đọc để hiện nút "Dừng".
    """
    dsach = dang_chay()

    cung_module = [j for j in dsach if j["module"] == ma_module]
    if cung_module:
        job = cung_module[0]
        phut = job.get("tuoi_giay", 0) // 60
        da_lau = f", đã {phut} phút" if phut else ""
        return {
            "message": (
                f"Máy chủ đang chạy dở một phiên {job['ten_module']} khác "
                f"(job {job.get('job_id')}{da_lau}). Chờ nó xong hoặc bấm "
                f"\"Dừng\" rồi chạy lại."
            ),
            "job": {k: v for k, v in job.items() if k not in ("module", "ten_module")},
            "dang_chay": dsach,
        }

    if len(dsach) >= MAX_SONG_SONG:
        ten = ", ".join(sorted({j["ten_module"] for j in dsach}))
        return {
            "message": (
                f"Máy chủ đang chạy {len(dsach)} lượt đối chiếu cùng lúc ({ten}) — "
                f"đã tới giới hạn {MAX_SONG_SONG}. Mỗi lượt có thể chiếm vài GB bộ "
                f"nhớ, chạy thêm là cả bốn cùng hỏng. Chờ một lượt xong rồi thử lại."
            ),
            "dang_chay": dsach,
        }

    return None


# Khoá kết nạp: giữ trong đúng khoảng "kiểm tra xong → job có mặt trong sổ".
# KHÔNG dùng chung với `_lock` (khoá của sổ khai nguồn) — `kiem_tra()` cần `_lock`
# nên xài chung là tự khoá chính mình.
_lock_ket_nap = threading.Lock()


@contextlib.contextmanager
def gianh_cho(ma_module: str) -> Iterator[Optional[dict]]:
    """Kiểm tra VÀ đăng ký job như một thao tác nguyên tử.

    Vì sao cần: `kiem_tra()` rồi mới `tao_job()` là hai bước rời. Hai request bắn
    cùng lúc đều qua được cửa trước khi bên nào kịp ghi job vào sổ, nên cả hai
    cùng chạy. **Đo được thật**: bắn 5 request ILO1000 đồng thời thì 2 lọt qua
    thay vì 1 (chốt vẫn chặn 3, nhưng chặn hụt).

    Không phải chuyện lý thuyết — hai người cùng bấm "Chạy" đúng lúc chính là
    kịch bản đã làm sập backend 26/08/2026.

    Dùng:
        with phien_doi_chieu.gianh_cho('ilo1000') as nghen:
            if nghen:
                raise HTTPException(409, nghen)
            job_id, input_dir = svc.tao_job()   # job vào sổ TRƯỚC khi nhả khoá

    Khoá chỉ giữ qua bước tạo job (vài mili-giây, chỉ tạo thư mục) — KHÔNG giữ
    trong lúc nhận file, nếu không một lượt upload vài trăm MB sẽ chặn cả bốn
    module suốt thời gian đó.
    """
    with _lock_ket_nap:
        yield kiem_tra(ma_module)
