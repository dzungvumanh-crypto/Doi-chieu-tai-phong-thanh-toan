"""Chốt chặn số lượt đối chiếu nặng chạy cùng lúc — dùng chung cho MỌI cửa nặng.

Hiện có 7: ACH, Chấm ILO1000, Chấm 459901, Đối chiếu OSB, và ba cửa Đối chiếu Song
phương (chiều ĐẾN, chiều ĐI, phân loại dữ liệu). Tất cả đều nạp trọn dữ liệu vào RAM.
Từ 18/09/2026 phần nặng chạy ở tiến trình con (`tien_trinh_doi_chieu.chay_tach`) — hết
tranh GIL nhưng KHÔNG giảm RAM: trần dưới đây vẫn cần nguyên như cũ.

THÊM MODULE MỚI thì phải gọi `dang_ky_nguon()` cho nó — quên là nó chạy ngoài
trần mà không ai biết. Đã dính hai lần, xem `tests/test_chot_phien_doi_chieu.py`. Đo được pandas giữ **5,3 lần** kích
thước file khi đọc `dtype=str` (đỉnh 5,9×), mà trần một lượt upload là 500 MB.

Tất cả khởi chạy từ `threading.Thread` tự tạo, **không** đi qua `run_heavy()` — nên
`MAX_HEAVY` trong `backend/core/concurrency.py` KHÔNG ràng buộc chúng. Trước file
này, thứ duy nhất chặn là chốt riêng của ACH; ba module kia vào thẳng, và ACH
cũng chỉ tự canh mình nên chạy ACH cùng lúc với Song phương vẫn lọt.

Đã xảy ra thật: 26/08/2026 hai pipeline pandas cùng ôm vài trăm MB làm backend
hết RAM và chết giữa lúc đang nhận file của lượt thứ hai — người dùng chỉ thấy
"[WinError 10054]".

Ba luật, cố ý khác nhau:

  1. **Cùng một module: luôn 1 lượt.** Người vận hành xác nhận cùng một menu thì
     thực tế chỉ một người chạy. Đây là luật cứng, không nới được — hai lượt cùng
     module còn tranh nhau cả thư mục tạm chứ không riêng RAM.

  2. **Toàn hệ thống: `MAX_SONG_SONG` lượt.** Khác menu thì vài người chạy song
     song là chuyện bình thường, nên KHÔNG khoá về 1. Mặc định 3: đủ cho nếp làm
     việc thật, mà vẫn chặn trường hợp cả bốn module cùng chạy (worst case
     4 × 500 MB × 5,3 ≈ 10 GB trên máy 20 GB — sát quá; bỏ hẳn trần thì 7 cửa là
     ~18,5 GB). Người dùng chốt 18/09/2026: giữ 3, đọc số "bộ nhớ cam kết đỉnh" trong
     logs/app.log vài tuần rồi mới quyết nâng hay đổi sang trần theo RAM (card 150).

  3. **RAM ước tính: tổng ≤ `NGAN_SACH_RAM_GB`** (card 156, 21/09/2026). Số lượt không
     phân biệt 3 lượt nhẹ (~4,5 GB) với 3 lượt nặng (~10 GB). Mỗi module có mức ước tính
     từ số đo máy chủ thật; module chưa có số không xét luật này. Sau lưới này còn trần
     CỨNG ở `tien_trinh_doi_chieu` (Job Object) — ước tính sai thì máy vẫn an toàn.

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


# ── Xét RAM trước khi cho chạy (card 156) ──
# Bộ nhớ cam kết đỉnh ƯỚC TÍNH mỗi lượt, GB — người dùng chốt 21/09/2026 từ số đo máy chủ
# thật. Module CHƯA có số (ILO1000, 459901, OSB) cố ý vắng mặt: không xét RAM, chỉ còn trần
# số lượt ở trên + trần cứng của tiến trình con (tien_trinh_doi_chieu, 13 GB). Có số đo thì
# khai qua `.env` (`DOI_CHIEU_RAM_UOC_TINH`), không cần sửa mã.
_RAM_UOC_TINH_MAC_DINH = {
    "ach": 4.5,                        # đo 4,19 GB (3 lượt gần trùng nhau)
    "song_phuong_kenh_core_di": 4.0,   # Song phương chiều ĐI — đo 2,50–3,87 GB, dao động theo cỡ file
    "song_phuong": 3.0,                # Song phương chiều ĐẾN — đo 1,84–2,13 GB
    "song_phuong_di": 2.0,             # Song phương PHÂN LOẠI dữ liệu (mã "_di" là tên cũ) — đo 1,55 GB
}


def _doc_gb(tho: str, ten: str) -> Optional[float]:
    try:
        gb = float(tho.strip().replace(",", "."))
    except ValueError:
        _log.warning("%s=%r không phải số — bỏ qua", ten, tho)
        return None
    if gb <= 0:
        _log.warning("%s=%r phải lớn hơn 0 — bỏ qua", ten, tho)
        return None
    return gb


def _doc_uoc_tinh() -> dict[str, float]:
    """Mặc định + ghi đè từ `DOI_CHIEU_RAM_UOC_TINH=ma=gb,ma=gb` (vd `ilo1000=3.5,cham459901=2`).
    Số thập phân dùng dấu CHẤM — dấu phẩy đã dùng để ngăn các mục. Mục sai bị bỏ qua kèm
    cảnh báo, không làm backend chết."""
    ra = dict(_RAM_UOC_TINH_MAC_DINH)
    for muc in (os.getenv("DOI_CHIEU_RAM_UOC_TINH") or "").split(","):
        if not muc.strip():
            continue
        ma, _, tho = muc.partition("=")
        gb = _doc_gb(tho, f"DOI_CHIEU_RAM_UOC_TINH[{ma.strip()}]")
        if ma.strip() and gb is not None:
            ra[ma.strip()] = gb
    return ra


RAM_UOC_TINH = _doc_uoc_tinh()
# Trạng thái vẫn CHIẾM chỗ (luật cùng module, trần số lượt) nhưng KHÔNG còn tiến trình con giữ
# RAM: ACH chờ xác nhận MIS_đi — tính 4,5 GB là chặn oan lượt khác tới 4 giờ (phản biện 21/09).
_KHONG_GIU_RAM = {"awaiting_confirmation"}

# 11,5 = ACH + Song phương ĐI + ĐẾN (4,5 + 4 + 3) — người dùng chốt 21/09/2026 để ba lượt nặng
# nhất đã đo chạy được cùng lúc (RAM thật ≈ 4,19 + 3,87 + 2,13 = 10,2 GB, dưới trần cứng 13).
# Hệ quả: với 4 module đã có số, luật này không chặn tổ hợp 3 lượt nào — nó bắt đầu có tác dụng
# khi ILO1000/459901/OSB được khai ước tính, hoặc khi nâng MAX_SONG_SONG.
NGAN_SACH_RAM_GB = _doc_gb(os.getenv("DOI_CHIEU_RAM_NGAN_SACH_GB") or "11.5",
                           "DOI_CHIEU_RAM_NGAN_SACH_GB") or 11.5


def _so_vn(x: float) -> str:
    return f"{x:g}".replace(".", ",")


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

    # Xét RAM ước tính. Chỉ cộng lượt THẬT SỰ đang giữ RAM (xem _KHONG_GIU_RAM) của module có
    # số đo. Không có gì đang dùng thì luôn cho qua — kể cả khi ước tính một mình đã vượt
    # ngân sách (đặt ngân sách thấp không được khoá chết cả module).
    uoc = RAM_UOC_TINH.get(ma_module)
    giu_ram = [j for j in dsach
               if j["module"] in RAM_UOC_TINH and j.get("status") not in _KHONG_GIU_RAM]
    if uoc is not None and giu_ram:
        dang_dung = sum(RAM_UOC_TINH[j["module"]] for j in giu_ram)
        if dang_dung + uoc > NGAN_SACH_RAM_GB:
            with _lock:
                ten_moi = _NGUON.get(ma_module, (ma_module,))[0]
            chi_tiet = ", ".join(
                f"{j['ten_module']} ~{_so_vn(RAM_UOC_TINH[j['module']])} GB" for j in giu_ram)
            return {
                "message": (
                    f"Máy chủ chưa đủ bộ nhớ cho thêm một lượt {ten_moi} "
                    f"(~{_so_vn(uoc)} GB): đang chạy {chi_tiet} — cộng lại vượt "
                    f"{_so_vn(NGAN_SACH_RAM_GB)} GB dành cho đối chiếu. Chờ một lượt xong "
                    f"rồi thử lại."
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
