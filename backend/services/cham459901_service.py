"""Service phân loại bút toán tài khoản 459901 — 7 nhóm (Hủy/Đi/1000 Hoàn trả/
Chuyển chi nhánh/Điện KO offline/Cân CN/GD khác).

I/O làm việc với ĐƯỜNG DẪN file đã nằm trên máy chủ (`backend/api/cham459901.py`
ghi thẳng từng khối xuống `data/temp_cham459901/upload_<token>/`, hoặc — với
`process_folder` — dùng thẳng đường dẫn có sẵn trên server), không nhận bytes:
một lượt có thể là nhiều ZIP vài trăm MB, ôm hết vào RAM rồi mới đọc là trả giá
gấp đôi bộ nhớ cho cùng một kết quả. Chỉ file con BÊN TRONG ZIP mới đi qua bytes,
và cũng chỉ khi buộc phải thế (xem `_doc_zip`).
"""

import io
import logging
import shutil
import threading
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from backend.core.config import BASE_DIR, zip_password   # mật khẩu ZIP đọc từ .env
from backend.core.don_dep import moc_don_gan_nhat

try:
    import pyzipper
    _ZipFile = pyzipper.AESZipFile
    # pyzipper đóng gói bản zipfile riêng: pyzipper.BadZipFile KHÔNG phải lớp con
    # của zipfile.BadZipFile. Bắt thiếu lớp này thì zip hỏng lọt thành lỗi 500.
    _BAD_ZIP = (pyzipper.BadZipFile, zipfile.BadZipFile)
except ImportError:
    _ZipFile = zipfile.ZipFile      # fallback nếu pyzipper chưa cài
    _BAD_ZIP = (zipfile.BadZipFile,)

# ─── Config ───────────────────────────────────────────────────────────────────
TEMP_DIR        = BASE_DIR / "data" / "temp_cham459901"
FILTER_LOCAC    = "459901"
FILTER_CUSTOMER = "1000-000007709"
FILTER_CCY      = "VND"
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_COLS = [
    'TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'LOCAC', 'CCY',
    'BUSCD', 'UNIT', 'TRCD', 'CUSTOMER', 'TRTP', 'REFERENCE', 'REMARK',
    'DRAMOUNT', 'CRAMOUNT', 'CRTDTM', 'GHI_CHU',
]

COL_WIDTHS = {
    'TRDATE': 12, 'TRBRCD': 8, 'USERID': 13, 'JOURSEQ': 10, 'DYTRSEQ': 9,
    'LOCAC': 8, 'CCY': 5, 'BUSCD': 7, 'UNIT': 6, 'TRCD': 6, 'CUSTOMER': 18,
    'TRTP': 8, 'REFERENCE': 22, 'REMARK': 52, 'DRAMOUNT': 18, 'CRAMOUNT': 18,
    'CRTDTM': 20, 'GHI_CHU': 38,
}

# Định dạng nhận được. ZIP là bản xuất gốc từ GL02 (bên trong là .csv, đôi khi là
# Excel); Excel rời dành cho người đã mở ZIP ra, cắt bớt rồi lưu lại.
DUOI_ZIP    = '.zip'
DUOI_EXCEL  = ('.xlsx', '.xlsm', '.xlsb', '.xls')
DUOI_HOP_LE = (DUOI_ZIP,) + DUOI_EXCEL

# Cột chung giữa dữ liệu GL02 gốc và file "tồn" tháng trước (459_TON_Tx.xlsx) — dùng khi
# ghép nối tiếp file tồn vào dữ liệu tháng mới để phân loại lại (xem _read_ton_file).
# Thiếu CRTDTM (không có trong file tồn); các cột str được ép kiểu để khớp dtype=str của
# _load_data (đọc CSV dtype=str).
_TON_COLS = [
    'TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'LOCAC', 'CCY',
    'BUSCD', 'UNIT', 'TRCD', 'CUSTOMER', 'TRTP', 'REFERENCE', 'REMARK',
    'DRAMOUNT', 'CRAMOUNT',
]
_TON_STR_COLS = [c for c in _TON_COLS if c not in ('DRAMOUNT', 'CRAMOUNT')]

# Số dòng đầu mỗi sheet dùng để dò hàng tiêu đề (xem _dat_tieu_de). Bản người
# dùng tự lưu lại có thể có khối tiêu đề báo cáo (tên báo cáo, chi nhánh, kỳ,
# điều kiện lọc…) dài hơn 10 dòng — dò trượt là báo "không phải dữ liệu GL02"
# dù dữ liệu bên dưới vẫn đủ.
_MAX_DONG_DO_TIEU_DE = 25

# Cột ngày: Excel trả về kiểu ngày-giờ, cần cắt đuôi giờ 0 cho giống bản CSV
_COT_NGAY = ('TRDATE', 'CRTDTM')

# Chỉ strip các cột dùng trong filter và xây key — không strip tất cả string cols
_STRIP_COLS = {'LOCAC', 'CUSTOMER', 'CCY', 'TRTP', 'REFERENCE', 'TRBRCD', 'DYTRSEQ', 'REMARK'}

_NUM_COLS = frozenset({'DRAMOUNT', 'CRAMOUNT'})

# Không có đủ các cột này thì không lọc/phân loại được — kiểm từng file một
_COT_BAT_BUOC = frozenset({'LOCAC', 'CUSTOMER', 'CCY', 'REMARK', 'DRAMOUNT', 'CRAMOUNT'})

# A–Z rồi AA, AB, … (đủ cho 30 cột)
_COL_LETTERS = [
    (chr(65 + i) if i < 26 else chr(64 + i // 26) + chr(65 + i % 26))
    for i in range(30)
]

log = logging.getLogger(__name__)


class _Cancelled(Exception):
    """Sentinel nội bộ — báo hiệu người dùng đã bấm Dừng, thoát sớm khỏi xử lý."""


class InputError(ValueError):
    """Lỗi do chính file người dùng tải lên — thông báo hiển thị thẳng cho họ."""


# ─── In-memory progress store ─────────────────────────────────────────────────
# key = task_token; value = {pct, msg, done, error, cancelled, result, cancel_event, _ts}
_progress: dict[str, dict] = {}


def init_progress() -> str:
    """Khởi tạo entry theo dõi tiến độ, trả về task_token."""
    task_token = str(uuid.uuid4())
    _progress[task_token] = {
        "pct": 0, "msg": "Đang khởi tạo...",
        "done": False, "error": None, "cancelled": False, "result": None,
        "cancel_event": threading.Event(),
        "_ts": time.time(),
    }
    return task_token


def tao_thu_muc_upload(task_token: str) -> Path:
    """Thư mục nhận file tải lên của một lượt: `data/temp_cham459901/upload_<token>/`.

    Nằm cùng chỗ với thư mục kết quả nên `_cleanup_old_results()` trông coi luôn,
    không phải thêm đường dọn thứ hai. Tiền tố `upload_` để người vận hành mở ra
    là phân biệt được đâu là file người dùng gửi lên, đâu là 7 file Excel sinh ra.
    """
    d = TEMP_DIR / f"upload_{task_token}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bo_luot(task_token: str) -> None:
    """Huỷ một lượt chưa chạy (upload lỗi/đứt): xoá thư mục và entry tiến độ."""
    shutil.rmtree(TEMP_DIR / f"upload_{task_token}", ignore_errors=True)
    _progress.pop(task_token, None)


def get_progress(task_token: str) -> dict | None:
    p = _progress.get(task_token)
    if p is None:
        return None
    return {k: v for k, v in p.items() if not k.startswith("_") and k != "cancel_event"}


def cancel_progress(task_token: str) -> bool:
    """Đánh dấu yêu cầu dừng — pipeline sẽ tự thoát ở checkpoint gần nhất."""
    p = _progress.get(task_token)
    if p is None or p["done"]:
        return False
    p["cancel_event"].set()
    return True


def delete_result(result_token: str) -> bool:
    """Xóa thư mục kết quả trên server (khi người dùng phát hiện sai sót, muốn làm lại).

    `result_token` phải đã qua `safe_filename()` ở tầng gọi (API) trước khi tới đây —
    hàm này chỉ ghép thẳng vào TEMP_DIR, không tự làm sạch.
    """
    out_dir = TEMP_DIR / result_token
    if not out_dir.exists():
        return False
    shutil.rmtree(out_dir, ignore_errors=True)
    return True


def classify_upload_filename(filename: str) -> str | None:
    """Tự nhận diện 3 loại file PHỤ TRỢ theo tên khi upload nhiều file cùng lúc
    (kéo-thả kiểu ACH): HUB đi / HUB đến / tồn tháng trước. Trả về
    'hub_di' | 'hub_den' | 'ton' | None.

    File GL02 chính (zip hoặc Excel) KHÔNG qua hàm này — tên gì cũng được, nhận
    diện bằng đuôi file (`DUOI_HOP_LE`) ở tầng gọi, và nhiều file được GỘP lại
    trước khi phân loại (xem `process_files`), không phải chọn 1 file như 3 loại
    phụ trợ dưới đây.
    """
    name = filename.lower()
    if not name.endswith('.xlsx'):
        return None
    if '459' in name and 'ton' in name:
        return 'ton'
    if 'quay' in name or 'chuyen tien di' in name or 'chuyen_tien_di' in name:
        return 'hub_di'
    if ('giao dich den' in name or 'giao_dich_den' in name
            or ('danh_sach' in name and 'den' in name)
            or ('danh sach' in name and 'den' in name)):
        return 'hub_den'
    return None


def _set_prog(task_token: str | None, pct: int, msg: str) -> None:
    if task_token and task_token in _progress:
        p = _progress[task_token]
        if p["cancel_event"].is_set():
            raise _Cancelled()
        p["pct"] = pct
        p["msg"] = msg


# ─── Public API ───────────────────────────────────────────────────────────────

def run_process(
    tep: list[tuple[str, Path]],
    task_token: str,
    hub_di: tuple[str, Path] | None = None,
    hub_den: tuple[str, Path] | None = None,
    ton: tuple[str, Path] | None = None,
) -> None:
    """Chạy process_files trong luồng riêng; cập nhật progress và bắt lỗi."""
    try:
        process_files(tep, task_token, hub_di, hub_den, ton)
    except _Cancelled:
        if task_token in _progress:
            _progress[task_token].update({
                "done": True, "cancelled": True, "msg": "Đã dừng theo yêu cầu.",
            })
    except InputError as e:
        # File sai — không phải lỗi hệ thống, người dùng tự sửa được.
        log.warning("cham459901 file không hợp lệ [%s]: %s", task_token, e)
        if task_token in _progress:
            _progress[task_token].update({"done": True, "error": str(e), "msg": str(e)})
    except Exception as e:
        log.error("process_files lỗi [%s]: %s", task_token, e, exc_info=True)
        if task_token in _progress:
            _progress[task_token].update({
                "done": True, "error": str(e),
                "msg": "Lỗi xử lý — xem log server",
            })


def process_files(
    tep: list[tuple[str, Path]],
    task_token: str | None = None,
    hub_di: tuple[str, Path] | None = None,
    hub_den: tuple[str, Path] | None = None,
    ton: tuple[str, Path] | None = None,
) -> dict:
    """Nhận nhiều file GL02 ZIP/Excel [(tên hiển thị, đường dẫn)] (+ tùy chọn 1 file
    HUB đi, 1 file HUB đến, 1 file tồn tháng trước) → gộp → phân loại 7 nhóm → lưu
    7 xlsx → trả metadata.

    `tên hiển thị` là tên gốc người dùng chọn, chỉ dùng để viết thông báo lỗi;
    `đường dẫn` là file đã nằm trên máy chủ (ghi từ upload, hoặc đã có sẵn khi
    chạy từ thư mục server). Hai thứ tách nhau vì tên trên đĩa đã qua
    `safe_filename()` nên có thể khác tên người dùng nhìn thấy — báo lỗi bằng
    tên đã bị cắt là bắt họ đi tìm một file không tồn tại.

    Gộp TRƯỚC rồi mới phân loại các file GL02 chính, không chạy riêng từng file:
    cặp Cancel/Normal của một lệnh hủy có thể nằm ở hai file khác nhau (xuất theo
    ngày/theo chi nhánh). Chạy tách ra thì cả hai vế đều rơi vào "GD khác". Trộn
    ZIP với Excel trong cùng một lượt cũng vậy — nguồn nào không quan trọng, sau
    khi đọc lên đều là cùng một bảng.

    Thiếu file HUB (thiếu 1 trong 2, hoặc cả 2) → bỏ qua bước 1000 Hoàn trả, các
    dòng đó rơi về GD khác chấm thủ công. Thiếu file tồn → chạy như cũ, không
    ghép thêm dữ liệu tháng trước.
    """
    if not tep:
        raise InputError("Chưa chọn file nào.")

    _cleanup_old_results()
    t0 = time.time()

    _set_prog(task_token, 5, "Đang đọc dữ liệu...")
    df, filtered_rows = _load_data(tep, task_token)
    total_before = len(df) + filtered_rows

    ton_rows_added = 0
    if ton is not None:
        _set_prog(task_token, 26, "Đang đọc file tồn tháng trước...")
        df_ton = _read_ton_file(ton[1])
        ton_rows_added = len(df_ton)
        df = pd.concat([df_ton, df], ignore_index=True)

    hub_di_df = hub_den_df = None
    if hub_di is not None and hub_den is not None:
        _set_prog(task_token, 28, "Đang đọc file HUB đi/đến...")
        hub_di_df  = _read_hub_di(hub_di[1])
        hub_den_df = _read_hub_den(hub_den[1])

    _set_prog(task_token, 30, "Bước 1 — Xác định lệnh hủy...")
    df_huy, df_di, df_1000ht, df_ccn, df_ko, df_can_cn, df_khac = _classify(
        df, task_token, hub_di_df, hub_den_df,
    )

    result_token = str(uuid.uuid4())
    out_dir = TEMP_DIR / result_token
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        _set_prog(task_token, 85, f"Xuất Excel — Lệnh Hủy ({len(df_huy):,} dòng)...")
        _write_excel(df_huy,    out_dir / "huy.xlsx",    "Lệnh Hủy",         "C0392B")

        _set_prog(task_token, 87, f"Xuất Excel — Lệnh Đi ({len(df_di):,} dòng)...")
        _write_excel(df_di,     out_dir / "di.xlsx",     "Lệnh Đi",          "27AE60")

        _set_prog(task_token, 89, f"Xuất Excel — 1000 Hoàn trả ({len(df_1000ht):,} dòng)...")
        _write_excel(df_1000ht, out_dir / "ht1000.xlsx", "1000 Hoàn trả",    "2980B9")

        _set_prog(task_token, 91, f"Xuất Excel — Chuyển chi nhánh ({len(df_ccn):,} dòng)...")
        _write_excel(df_ccn,    out_dir / "ccn.xlsx",    "Chuyển chi nhánh", "8E44AD")

        _set_prog(task_token, 93, f"Xuất Excel — Điện KO offline ({len(df_ko):,} dòng)...")
        _write_excel(df_ko,     out_dir / "ko.xlsx",     "Điện KO offline",  "16A085")

        _set_prog(task_token, 95, f"Xuất Excel — Cân CN ({len(df_can_cn):,} dòng)...")
        _write_excel(df_can_cn, out_dir / "can_cn.xlsx", "Cân CN",           "F1C40F")

        _set_prog(task_token, 98, f"Xuất Excel — GD khác ({len(df_khac):,} dòng)...")
        _write_excel(df_khac,   out_dir / "khac.xlsx",   "GD khác",          "E67E22")

        # Checkpoint cuối — nếu người dùng bấm Dừng đúng lúc đang ghi file cuối, vẫn
        # phải phát hiện trước khi báo "Hoàn thành!" thay vì hoàn tất bất chấp yêu cầu dừng.
        _set_prog(task_token, 99, "Đang hoàn tất...")
    except _Cancelled:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise

    result = {
        "token":          result_token,
        "huy_rows":       len(df_huy),
        "di_rows":        len(df_di),
        "ht1000_rows":    len(df_1000ht),
        "ccn_rows":       len(df_ccn),
        "ko_rows":        len(df_ko),
        "can_cn_rows":    len(df_can_cn),
        "khac_rows":      len(df_khac),
        "total_rows":     total_before,
        "filtered_rows":  filtered_rows,
        "n_files":        len(tep),
        "ton_rows_added": ton_rows_added,
        "hub_provided":   hub_di_df is not None,
        "elapsed_s":      round(time.time() - t0, 1),
        "process_date":   datetime.now().strftime("%Y%m%d"),
    }

    if task_token and task_token in _progress:
        _progress[task_token].update({
            "pct": 100, "msg": "Hoàn thành!",
            "done": True, "result": result,
        })

    return result


# ─── Internal — đọc file GL02 chính (ZIP/Excel, gộp nhiều file) ───────────────

def _liet_ke_cot(d: pd.DataFrame, gioi_han: int = 8) -> str:
    """Tên các cột bảng đang có, cắt bớt cho vừa một dòng thông báo."""
    cot = [str(c) for c in d.columns]
    if not cot:
        return "(không có cột nào)"
    if len(cot) <= gioi_han:
        return ", ".join(cot)
    return ", ".join(cot[:gioi_han]) + f", … ({len(cot)} cột)"


def _kiem_cot(d: pd.DataFrame, nhan: str) -> None:
    """Kiểm cột NGAY TỪNG BẢNG, không đợi gộp xong.

    `pd.concat` lấy hợp các cột: bảng thiếu cột chỉ thành ô rỗng. Gộp rồi mới
    kiểm thì một file sai định dạng lọt qua và làm lệch kết quả phân loại.
    """
    missing = sorted(_COT_BAT_BUOC - set(d.columns))
    if not missing:
        return

    # Thiếu SẠCH cả 6 cột nghĩa là cầm nhầm loại file (hoặc dò trượt dòng tiêu
    # đề) — không phải bản GL02 bị cắt bớt cột. Câu "thiếu cột bắt buộc" ở đây
    # bắt người dùng đi tìm cột trong một file vốn không bao giờ có. Kèm luôn
    # tên cột đang có để họ tự nhận ra mình chọn nhầm bảng nào.
    if len(missing) == len(_COT_BAT_BUOC):
        raise InputError(
            f"{nhan} không phải dữ liệu GL02 — không có cột nào trong số "
            f"{', '.join(sorted(_COT_BAT_BUOC))}. Cột đang có: {_liet_ke_cot(d)}."
        )

    raise InputError(f"{nhan} thiếu cột bắt buộc: {', '.join(missing)}.")


def _doc_csv(nguon) -> pd.DataFrame:
    """`nguon`: đường dẫn file, hoặc luồng đọc của một file con trong ZIP."""
    d = pd.read_csv(nguon, encoding='utf-8-sig', dtype=str, keep_default_na=False)
    d.columns = d.columns.str.strip()
    return d


def _dat_tieu_de(raw: pd.DataFrame) -> pd.DataFrame | None:
    """Dò hàng tiêu đề trong vài dòng đầu sheet → bảng đã đặt tên cột (None nếu trống).

    Đọc `header=None` rồi tự dò, không đọc thẳng `header=0`: bản Excel người
    dùng tự lưu lại thường có thêm dòng tiêu đề báo cáo / ngày xuất ở trên
    cùng. Đọc cứng dòng đầu thì những file đó báo "thiếu cột bắt buộc" dù dữ
    liệu bên dưới vẫn đủ.
    """
    raw = raw.dropna(how='all')
    if raw.empty:
        return None

    dong = 0
    for i in range(min(_MAX_DONG_DO_TIEU_DE, len(raw))):
        ten_cot = {str(v).strip() for v in raw.iloc[i]}
        # 3 cột bắt buộc trên cùng một dòng là đủ chắc đây là hàng tiêu đề,
        # không phải một dòng dữ liệu tình cờ có chữ giống tên cột.
        if len(_COT_BAT_BUOC & ten_cot) >= 3:
            dong = i
            break
    # Dò không ra thì vẫn lấy dòng đầu làm tiêu đề: _kiem_cot() ngay sau đó nói
    # rõ thiếu những cột nào — sát vấn đề hơn câu "không tìm thấy dòng tiêu đề".

    d = raw.iloc[dong + 1:].copy()
    d.columns = [str(v).strip() for v in raw.iloc[dong]]
    d = d.dropna(how='all')
    if d.empty:
        return None

    # Bỏ cột không có tên (ô tiêu đề trống → pandas trả 'nan'); giữ theo vị trí
    # để không vấp khi workbook có hai cột trùng tên.
    giu = [i for i, c in enumerate(d.columns) if c and c.lower() != 'nan']
    d = d.iloc[:, giu]

    # Ô trống trong Excel là NaN. Để nguyên thì `.str.strip()` và phép ghép khoá
    # phân loại đều cho NaN, mà NaN != NaN → dòng đó lặng lẽ rơi vào "GD khác".
    d = d.fillna('')

    # Excel lưu ngày ở kiểu ngày-giờ, pandas đổi ra "2026-08-01 00:00:00"; bản
    # CSV gốc không có đuôi giờ đó — cắt đi để hai nguồn ra cùng một dạng.
    for col in _COT_NGAY:
        if col in d.columns:
            d[col] = d[col].astype(str).str.replace(r' 00:00:00$', '', regex=True)

    return d.reset_index(drop=True)


def _doc_excel(nguon, nhan: str) -> list[pd.DataFrame]:
    """Đọc 1 workbook Excel → mỗi sheet có dữ liệu là một DataFrame.

    `nguon` là đường dẫn file trên đĩa (đường thường), hoặc bytes khi workbook
    nằm bên trong ZIP — calamine cần đọc nhảy vị trí nên không nhận luồng giải
    nén tuần tự, đó là chỗ duy nhất còn phải qua RAM.

    Đọc TẤT CẢ sheet chứ không chỉ sheet đầu, và bắt sheet nào cũng phải đủ cột.
    Bỏ qua sheet thiếu cột là im lặng đánh rơi dữ liệu — người dùng không có
    cách nào biết một phần bút toán đã không được tính.
    """
    try:
        sheets = pd.read_excel(io.BytesIO(nguon) if isinstance(nguon, bytes) else nguon,
                               sheet_name=None, header=None,
                               dtype=str, engine='calamine')
    except Exception as e:
        log.warning("%s: không đọc được Excel: %s", nhan, e, exc_info=True)
        raise InputError(
            f"{nhan} không đọc được như file Excel — có thể file hỏng, bị cắt dở, "
            "hoặc chỉ được đổi đuôi tên thành .xlsx."
        ) from e

    dfs = []
    for ten_sheet, raw in sheets.items():
        d = _dat_tieu_de(raw)
        if d is None:
            continue                      # sheet trống — bỏ qua, không phải lỗi
        _kiem_cot(d, f"{nhan} → sheet '{ten_sheet}'")
        dfs.append(d)

    if not dfs:
        raise InputError(f"{nhan} không có sheet nào chứa dữ liệu.")
    return dfs


def _doc_tep(ten: str, duong_dan: Path) -> list[pd.DataFrame]:
    """Đọc 1 file GL02 → danh sách DataFrame, theo đuôi tên file.

    Đuôi lấy từ TÊN NGƯỜI DÙNG CHỌN, không từ tên trên đĩa: hai cái có thể khác
    nhau sau `safe_filename()`, và đây là thứ quyết định file được đọc kiểu gì.
    """
    duoi = Path(ten).suffix.lower()
    if duoi == DUOI_ZIP:
        return _doc_zip(ten, duong_dan)
    if duoi in DUOI_EXCEL:
        return _doc_excel(duong_dan, f"File '{ten}'")
    raise InputError(
        f"File '{ten}' không thuộc định dạng nhận được — chỉ nhận "
        f"{', '.join(DUOI_HOP_LE)}."
    )


def _doc_zip(ten: str, duong_dan: Path) -> list[pd.DataFrame]:
    """Giải nén 1 file ZIP trên đĩa → danh sách DataFrame (mỗi .csv/Excel bên trong một cái).

    CSV bên trong được đọc qua `zf.open()` — pandas kéo dữ liệu giải nén theo
    luồng, không có lúc nào cả file CSV nằm nguyên trong RAM. Workbook Excel thì
    vẫn phải `zf.read()` vì calamine đọc nhảy vị trí (xem `_doc_excel`).

    Mọi thông báo lỗi đều kèm TÊN FILE: người dùng chọn cả chục file một lượt,
    câu "file .zip không hợp lệ" trơ trọi thì không biết phải bỏ file nào ra.
    """
    dfs = []
    try:
        with _ZipFile(str(duong_dan)) as zf:
            ten_con = [n for n in zf.namelist()
                       if n.lower().endswith(('.csv',) + DUOI_EXCEL)]
            for ten_trong in ten_con:
                nhan = f"File '{ten}' → '{ten_trong}'"
                if ten_trong.lower().endswith('.csv'):
                    with zf.open(ten_trong, pwd=zip_password()) as luong:
                        d = _doc_csv(luong)
                    _kiem_cot(d, nhan)
                    dfs.append(d)
                else:
                    dfs.extend(_doc_excel(zf.read(ten_trong, pwd=zip_password()), nhan))
    except _BAD_ZIP as e:
        raise InputError(
            f"File '{ten}' không phải file .zip hợp lệ — có thể tải bị lỗi, "
            "bị cắt dở, hoặc chỉ được đổi đuôi tên thành .zip."
        ) from e
    except RuntimeError as e:
        raise InputError(
            f"Không giải nén được file '{ten}' — sai mật khẩu hoặc file dùng kiểu "
            "mã hoá khác với file xuất từ IPCAS."
        ) from e

    # Trước đây dfs rỗng → dfs[0] ném IndexError('list index out of range'),
    # người dùng chỉ thấy đúng câu đó, không biết phải sửa gì.
    if not dfs:
        raise InputError(
            f"File '{ten}' không chứa file .csv hay Excel nào — cần file dữ liệu "
            "xuất từ IPCAS."
        )
    return dfs


def _load_data(
    tep: list[tuple[str, Path]],
    task_token: str | None = None,
) -> tuple[pd.DataFrame, int]:
    """Đọc tất cả file GL02, gộp thành một DataFrame, lọc theo TK 459901."""
    dfs: list[pd.DataFrame] = []
    n = len(tep)
    for i, (ten, duong_dan) in enumerate(tep, 1):
        # 5% → 25%: phần đọc file chiếm khoảng đó trong thanh tiến độ chung
        _set_prog(task_token, 5 + (20 * (i - 1)) // n,
                  f"Đang đọc dữ liệu ({i}/{n}): {ten}...")
        dfs.extend(_doc_tep(ten, duong_dan))

    _set_prog(task_token, 25, f"Đang gộp dữ liệu {n} file...")
    df = pd.concat(dfs, ignore_index=True) if len(dfs) > 1 else dfs[0]

    # Chỉ strip các cột cần thiết — tránh strip 17 cột × 645k dòng
    for col in _STRIP_COLS:
        if col in df.columns:
            df[col] = df[col].str.strip()

    df['REMARK'] = df['REMARK'].fillna('')
    df['DRAMOUNT'] = pd.to_numeric(df['DRAMOUNT'], errors='coerce').fillna(0.0)
    df['CRAMOUNT'] = pd.to_numeric(df['CRAMOUNT'], errors='coerce').fillna(0.0)

    before = len(df)
    df = df[
        (df['LOCAC']    == FILTER_LOCAC) &
        (df['CUSTOMER'] == FILTER_CUSTOMER) &
        (df['CCY']      == FILTER_CCY)
    ].copy()
    return df, before - len(df)


# ─── Internal — file phụ trợ (tồn tháng trước / HUB đi / HUB đến) ─────────────

def _read_ton_file(duong_dan: Path) -> pd.DataFrame:
    """Đọc file 'tồn' tháng trước (459_TON_Tx.xlsx, header ngay dòng 1) — chỉ lấy 16 cột
    chung với dữ liệu GL02 gốc (_TON_COLS), bỏ các cột ghi chú thủ công của người chấm
    ('chấm', 'Phong ban', 'refhub') — dùng để ghép nối tiếp vào dữ liệu tháng mới rồi
    phân loại lại từ đầu, không giữ trạng thái/ghi chú cũ."""
    raw = pd.read_excel(duong_dan, engine='calamine')
    raw.columns = raw.columns.astype(str).str.strip()
    df = raw[_TON_COLS].copy()

    for col in _TON_STR_COLS:
        s = df[col]
        if pd.api.types.is_numeric_dtype(s):
            # Cột số nguyên (TRDATE, TRBRCD, JOURSEQ, DYTRSEQ, LOCAC) đọc từ Excel có thể
            # ra dtype float64 nếu có NaN xen kẽ — ép qua int() thủ công để tránh hậu tố
            # ".0" (dùng .map thay vì .astype(str) để không dính quirk hiển thị NA của
            # dtype "string" mới trong pandas gần đây, khiến NaN bị in ngược thành float).
            df[col] = s.map(lambda v: '' if pd.isna(v) else str(int(v)))
        else:
            df[col] = s.map(lambda v: '' if pd.isna(v) else str(v).strip())

    df['DRAMOUNT'] = pd.to_numeric(df['DRAMOUNT'], errors='coerce').fillna(0.0).astype(float)
    df['CRAMOUNT'] = pd.to_numeric(df['CRAMOUNT'], errors='coerce').fillna(0.0).astype(float)

    df = df[
        (df['LOCAC']    == FILTER_LOCAC) &
        (df['CUSTOMER'] == FILTER_CUSTOMER) &
        (df['CCY']      == FILTER_CCY)
    ].reset_index(drop=True)
    return df


def _read_hub_di(duong_dan: Path) -> pd.DataFrame:
    """Đọc file 'Quay_danh sach giao dich chuyen tien di' — tiêu đề ở dòng Excel thứ 2."""
    raw = pd.read_excel(duong_dan, header=None, engine='calamine')
    df = raw.iloc[2:].copy()
    df.columns = raw.iloc[1].tolist()
    df = df.dropna(subset=['Số Trace 1']).reset_index(drop=True)

    amt   = pd.to_numeric(df['Số tiền thực chuyển'], errors='coerce').fillna(0.0).round(0)
    trace = pd.to_numeric(df['Số Trace 1'], errors='coerce')
    is_napas = df['Hệ thống thanh toán'].astype(str).str.strip() == 'ACH-NAPAS'
    # ACH-NAPAS: lấy ký tự thứ 47-52 (1-based) của "Nội dung chuyển tiền"
    override = df['Nội dung chuyển tiền'].astype(str).str.slice(46, 52).str.strip()
    link = df['Số tham chiếu lệnh gốc'].astype(str).str.strip()
    link = link.where(~is_napas, override)

    return pd.DataFrame({'AMOUNT': amt, 'TRACE': trace, 'LINK': link})


def _trace_candidates(raw: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Chuẩn hoá cột 'Số trace' của hub_đến — trả về CẢ HAI ứng viên trace khi có 2 dãy số
    cách nhau bởi ';' (gặp ở giao dịch kênh ACH-NAPAS). KHÔNG thể chỉ tin dãy đầu: verify dữ
    liệu thật Tháng 5 cho thấy 49/97 dòng ACH-NAPAS khớp REFERENCE của TK459 với dãy ĐẦU,
    46/97 dòng chỉ khớp với dãy THỨ HAI — bỏ sót dãy 2 khiến ~47% giao dịch 1000 Hoàn trả kênh
    ACH biến mất vào GD khác (xem Implementation-notes.html). Mỗi dãy lấy 9 ký tự cuối (phòng
    trace dài hơn 9 số — phần thừa phía trước không phải trace thật). seg2 là NaN nếu không
    có ';'."""
    parts = raw.astype(str).str.split(';')
    # .astype(str) trước khi cắt 9 ký tự cuối — parts.str[1] toàn NaN (không dòng nào có ';')
    # trả về dtype float64, .str[...] trên float64 ném AttributeError; ép về chuỗi ('nan' cho
    # dòng thiếu) rồi mới cắt để đồng nhất dtype trước khi to_numeric coerce về NaN.
    seg1 = pd.to_numeric(parts.str[0].astype(str).str[-9:], errors='coerce')
    seg2 = pd.to_numeric(parts.str[1].astype(str).str[-9:], errors='coerce')
    return seg1, seg2


def _trace_last9(raw: pd.Series) -> pd.Series:
    """Dãy trace ĐẦU TIÊN (xem _trace_candidates) — giữ cho nơi chỉ cần 1 giá trị/không cần
    xét dãy thứ hai."""
    return _trace_candidates(raw)[0]


def _read_hub_den(duong_dan: Path) -> pd.DataFrame:
    """Đọc file 'Danh sach giao dich den' — tiêu đề ở dòng Excel thứ 3."""
    raw = pd.read_excel(duong_dan, header=None, engine='calamine')
    df = raw.iloc[3:].copy()
    df.columns = raw.iloc[2].tolist()
    df = df.dropna(subset=['Số trace']).reset_index(drop=True)

    amt = pd.to_numeric(df['Số tiền lệnh gốc'], errors='coerce').fillna(0.0).round(0)
    trace, trace2 = _trace_candidates(df['Số trace'])
    is_napas = df['Hệ thống thanh toán'].astype(str).str.strip() == 'ACH-NAPAS'
    # ACH-NAPAS: lấy 6 số cuối của "Số thành công/MSGID"
    override = df['Số thành công/MSGID'].astype(str).str.strip().str[-6:]
    link = df['Số REF HUB'].astype(str).str.strip()
    link = link.where(~is_napas, override)

    return pd.DataFrame({'AMOUNT': amt, 'TRACE': trace, 'TRACE2': trace2, 'LINK': link})


_BLANK_LINK = frozenset({'', 'nan', 'none', 'nat'})


def _match_hub_1000ht(hub_di: pd.DataFrame, hub_den: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """DK1: khớp hub đi ↔ hub đến theo LINK (Số tham chiếu lệnh gốc = Số REF HUB),
    xác nhận bằng tổng tiền theo nhóm bằng nhau (đối chiếu N:N).
    LINK rỗng/nan bị loại trước khi khớp — nhiều dòng thiếu "Số tham chiếu lệnh gốc"/
    "Số REF HUB" (VD bút toán điều chỉnh thủ công) đều mang cùng giá trị rỗng, ghép nhóm
    với nhau sẽ tạo trùng khớp giả (tổng tiền trùng ngẫu nhiên) không phải cùng 1 giao dịch."""
    ok_di  = ~hub_di['LINK'].str.lower().isin(_BLANK_LINK)
    ok_den = ~hub_den['LINK'].str.lower().isin(_BLANK_LINK)

    sum_di  = hub_di[ok_di].groupby('LINK', sort=False)['AMOUNT'].sum()
    sum_den = hub_den[ok_den].groupby('LINK', sort=False)['AMOUNT'].sum()
    common  = sum_di.index.intersection(sum_den.index)
    matched = common[(sum_di.loc[common] - sum_den.loc[common]).abs() < 1]

    mask_di  = ok_di  & hub_di['LINK'].isin(matched)
    mask_den = ok_den & hub_den['LINK'].isin(matched)
    return mask_di, mask_den


def _mark_1000ht(df: pd.DataFrame, hub_di: pd.DataFrame, hub_den: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """1000 Hoàn trả (DK2): cột REFERENCE của TK459 (phần số từ ký tự thứ 8) CHÍNH LÀ
    số Trace của hub — Trace 1 (hub đi) cho chân Nợ, Trace đầu tiên (hub đến) cho chân Có.
    Đây là khóa định danh gần như tuyệt đối (đã verify 20/20 mẫu khớp chính xác), không phải
    khớp mờ theo số tiền — nên ghép Cột A (REFERENCE_số + DRAMOUNT) = Cột C (Trace1 + Số tiền)
    và Cột B (REFERENCE_số + CRAMOUNT) = Cột D (Trace đến + Số tiền lệnh gốc).

    Mỗi cặp hub đã xác nhận DK1 chỉ được đánh dấu 1000HT trong TK459 khi tìm được ĐỦ CẢ 2
    CHÂN (Nợ khớp cột C, Có khớp cột D của CÙNG 1 cặp hub) — đúng yêu cầu bắt buộc Nợ=Có theo
    từng cặp giao dịch. Nếu TK459 chỉ chấm 1 phần kỳ trong khi HUB trải dài hơn, chân còn lại
    có thể rơi ngoài kỳ dữ liệu — cặp đó không được xác nhận, dòng tìm thấy 1 chân sẽ được
    đánh dấu "nghi ngờ" (mask_candidate) để chấm tay thay vì đoán.

    Trả về (mask_confirmed, mask_candidate)."""
    mask_di_1000ht, mask_den_1000ht = _match_hub_1000ht(hub_di, hub_den)
    di_ok  = hub_di.loc[mask_di_1000ht,  ['LINK', 'TRACE', 'AMOUNT']]
    den_ok = hub_den.loc[mask_den_1000ht, ['LINK', 'TRACE', 'TRACE2', 'AMOUNT']]

    ref_suffix = pd.to_numeric(df['REFERENCE'].str.slice(7), errors='coerce')
    dr = df['DRAMOUNT'].round(0)
    cr = df['CRAMOUNT'].round(0)
    tk = pd.DataFrame({'REF_SUFFIX': ref_suffix, 'DR': dr, 'CR': cr}, index=df.index).reset_index()

    dr_match = tk.merge(di_ok,  left_on=['REF_SUFFIX', 'DR'], right_on=['TRACE', 'AMOUNT'], how='inner')
    # Hub đến ACH-NAPAS có thể có 2 dãy trace (xem _trace_candidates) — REFERENCE của TK459
    # có thể khớp dãy 1 HOẶC dãy 2, không đoán trước dãy nào đúng nên thử cả hai rồi gộp.
    cr_match_seg1 = tk.merge(den_ok, left_on=['REF_SUFFIX', 'CR'], right_on=['TRACE', 'AMOUNT'], how='inner')
    cr_match_seg2 = tk.merge(
        den_ok[den_ok['TRACE2'].notna()],
        left_on=['REF_SUFFIX', 'CR'], right_on=['TRACE2', 'AMOUNT'], how='inner',
    )
    cr_match = pd.concat([cr_match_seg1, cr_match_seg2], ignore_index=True) \
                 .drop_duplicates(subset=['index', 'LINK'])

    links_confirmed = set(dr_match['LINK']) & set(cr_match['LINK'])

    idx_confirmed = (
        set(dr_match.loc[dr_match['LINK'].isin(links_confirmed), 'index'])
        | set(cr_match.loc[cr_match['LINK'].isin(links_confirmed), 'index'])
    )
    idx_candidate = (
        set(dr_match.loc[~dr_match['LINK'].isin(links_confirmed), 'index'])
        | set(cr_match.loc[~cr_match['LINK'].isin(links_confirmed), 'index'])
    ) - idx_confirmed

    mask_confirmed = pd.Series(df.index.isin(idx_confirmed), index=df.index)
    mask_candidate = pd.Series(df.index.isin(idx_candidate), index=df.index)
    return mask_confirmed, mask_candidate


def _mark_ccn(df: pd.DataFrame) -> pd.Series:
    """Chuyển chi nhánh: ghép (số tiền + REMARK), khớp khi Tổng Nợ = Tổng Có của CẢ NHÓM.
    REMARK so khớp KHÔNG phân biệt hoa/thường và bỏ khoảng trắng thừa — 2 chân cùng 1 giao dịch
    do 2 chi nhánh khác nhau gõ tay REMARK khác case (VD 'chuyen tien' / 'CHUYEN TIEN') vẫn phải
    được nhận diện cùng 1 nhóm (xem Implementation-notes.html) — nếu không, chân lẻ rơi xuống
    bước Cân CN phía sau và có thể bị ghép nhầm với giao dịch không liên quan trùng số tiền tròn.
    Nhóm không cân bằng tuyệt đối (VD REMARK trùng lặp giữa nhiều giao dịch khác nhau)
    bị loại bỏ hoàn toàn — không tách một phần — để rơi về GD khác chấm thủ công."""
    if len(df) == 0:
        return pd.Series(dtype=bool)
    amt = df[['DRAMOUNT', 'CRAMOUNT']].abs().max(axis=1).round(0)
    key = amt.astype('Int64').astype(str) + '|' + df['REMARK'].str.strip().str.lower()

    sum_dr  = df['DRAMOUNT'].groupby(key).transform('sum')
    sum_cr  = df['CRAMOUNT'].groupby(key).transform('sum')
    dr_any  = (df['DRAMOUNT'] != 0).groupby(key).transform('any')
    cr_any  = (df['CRAMOUNT'] != 0).groupby(key).transform('any')

    return (sum_cr - sum_dr).abs().lt(1) & dr_any & cr_any


def _mark_can_cn(df: pd.DataFrame) -> pd.Series:
    """Cân CN (Cân chi nhánh): ghép (TRBRCD + số tiền), khớp khi Tổng Nợ = Tổng Có của nhóm.
    Riêng TRBRCD=1000: chỉ chấp nhận nếu tổng tiền nhóm >5 tỷ — nhóm nhỏ ở nhánh 1000 do
    người dùng xử lý thủ công, để nguyên trong GD khác cho chấm tay."""
    if len(df) == 0:
        return pd.Series(dtype=bool)
    amt = df[['DRAMOUNT', 'CRAMOUNT']].abs().max(axis=1).round(0)
    key = df['TRBRCD'] + '|' + amt.astype('Int64').astype(str)

    sum_dr  = df['DRAMOUNT'].groupby(key).transform('sum')
    sum_cr  = df['CRAMOUNT'].groupby(key).transform('sum')
    dr_any  = (df['DRAMOUNT'] != 0).groupby(key).transform('any')
    cr_any  = (df['CRAMOUNT'] != 0).groupby(key).transform('any')
    balanced = (sum_cr - sum_dr).abs().lt(1) & dr_any & cr_any

    is_1000 = df['TRBRCD'] == '1000'
    threshold_ok = sum_dr.gt(5_000_000_000) & sum_cr.gt(5_000_000_000)
    return balanced & (~is_1000 | threshold_ok)


def _mark_ko(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Điện KO offline (DK1-DK3): DK1 — tập ứng viên Có = USERID đúng mẫu "<mã chi nhánh 4
    số>KO" (VD '1000KO', '3511KO' — verify 58/58 USERID KO offline thật đều khớp mẫu này).
    KHÔNG dùng contains('KO') đơn thuần — bắt nhầm USERID tên đăng nhập giao dịch viên tình cờ
    có hậu tố "KO" (VD 'DTRLTKO') gây xếp nhầm Điện KO offline (xem Implementation-notes.html).
    DK2 — tập ứng viên Nợ = DRAMOUNT của các dòng có REMARK chứa marker 'Remitting Amount:VND'.
    DK3 — ghép cặp N:N theo SỐ TIỀN bằng nhau giữa 1 dòng Nợ (DK2) và 1 dòng Có (DK1), bắt buộc
    Nợ=Có từng cặp; dòng không tìm được đối tác cùng số tiền thì KHÔNG đánh dấu, rơi về GD khác
    (đánh dấu nghi ngờ) thay vì đoán.

    Trả về (mask_confirmed, mask_candidate)."""
    if len(df) == 0:
        return pd.Series(dtype=bool), pd.Series(dtype=bool)

    is_ko_user = df['USERID'].str.match(r'^\d{4}KO$', na=False)
    is_remit   = df['REMARK'].str.contains('Remitting Amount:VND', na=False)

    dr = df['DRAMOUNT'].round(0)
    cr = df['CRAMOUNT'].round(0)
    dr_amt = dr.where(is_remit & (dr != 0))
    cr_amt = cr.where(is_ko_user & (cr != 0))

    cnt_dr = dr_amt.dropna().value_counts()
    cnt_cr = cr_amt.dropna().value_counts()
    common = cnt_dr.index.intersection(cnt_cr.index)
    n_match = {amt: min(cnt_dr[amt], cnt_cr[amt]) for amt in common}

    cc_dr   = dr_amt.groupby(dr_amt).cumcount()
    cc_cr   = cr_amt.groupby(cr_amt).cumcount()
    limit_dr = dr_amt.map(n_match).fillna(0)
    limit_cr = cr_amt.map(n_match).fillna(0)

    mask_confirmed = (dr_amt.notna() & (cc_dr < limit_dr)) | (cr_amt.notna() & (cc_cr < limit_cr))
    mask_candidate = (is_ko_user | is_remit) & ~mask_confirmed
    return mask_confirmed, mask_candidate


def _classify(
    df: pd.DataFrame,
    task_token: str | None = None,
    hub_di: pd.DataFrame | None = None,
    hub_den: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, ...]:
    """Phân loại thác nước: Hủy → Đi → 1000 Hoàn trả → Chuyển chi nhánh → Điện KO offline
    → Cân CN → GD khác."""
    # ── Bước 1: Lệnh Hủy ──────────────────────────────────────────────────────
    df['abs_amt']  = (df['DRAMOUNT'] + df['CRAMOUNT']).abs()
    df['_huy_key'] = (df['REFERENCE'] + '|' + df['TRBRCD'] + '|'
                      + df['DYTRSEQ'] + '|' + df['abs_amt'].astype(str))

    cancel_keys = set(df.loc[df['TRTP'] == 'Cancel', '_huy_key'])
    normal_keys = set(df.loc[df['TRTP'] == 'Normal', '_huy_key'])
    huy_keys    = cancel_keys & normal_keys

    df_huy       = df[df['_huy_key'].isin(huy_keys)].copy()
    df_remaining = df[~df['_huy_key'].isin(huy_keys)].copy()

    # ── Bước 2: Lệnh Đi ───────────────────────────────────────────────────────
    _set_prog(task_token, 50, "Bước 2 — Phân loại lệnh đi...")
    df_remaining['_amt']    = df_remaining[['DRAMOUNT', 'CRAMOUNT']].abs().max(axis=1)
    df_remaining['_di_key'] = (df_remaining['TRBRCD'] + '|'
                               + df_remaining['_amt'].astype(str) + '|'
                               + df_remaining['REMARK'])

    # Vectorized — nhanh hơn groupby().apply(lambda) ~10-20x
    grp = df_remaining.groupby('_di_key')[['CRAMOUNT', 'DRAMOUNT']].sum()
    grp['balance'] = (grp['CRAMOUNT'] - grp['DRAMOUNT']).round(2)
    zero_keys = set(grp.index[grp['balance'] == 0])

    df_di   = df_remaining[df_remaining['_di_key'].isin(zero_keys)].copy()
    df_khac = df_remaining[~df_remaining['_di_key'].isin(zero_keys)].copy()

    # Xóa cột tạm
    temp_cols = ['abs_amt', '_huy_key', '_amt', '_di_key']
    for tmp_df in (df_huy, df_di, df_khac):
        tmp_df.drop(columns=[c for c in temp_cols if c in tmp_df.columns], inplace=True)

    # ── Bước 3: 1000 Hoàn trả (cần đủ 2 file HUB đi/đến) ──────────────────────
    # Ghép theo khóa TRACE (REFERENCE = số Trace của hub) — gần như không có rủi ro
    # cướp nhầm (đã verify precision >99,9%) nên chạy TRƯỚC CCN/KO. Chạy sau khi 1000HT
    # đã dùng khóa mờ theo số tiền từng khiến CCN/KO bị cướp; nay đã đảo lại vì khóa
    # TRACE chính xác hơn nhiều so với khóa amt+REMARK (CCN) hay amt-pairing (KO) —
    # để 1000HT chạy sau sẽ khiến CCN cướp mất 1 chân trước khi 1000HT kịp nhận diện
    # (xem Implementation-notes.html, case REFERENCE=1000API845335).
    _set_prog(task_token, 60, "Bước 3 — Đối chiếu 1000 Hoàn trả...")
    if hub_di is not None and hub_den is not None and len(df_khac) > 0:
        mask_ht, mask_ht_candidate = _mark_1000ht(df_khac, hub_di, hub_den)
    else:
        mask_ht = pd.Series(False, index=df_khac.index)
        mask_ht_candidate = pd.Series(False, index=df_khac.index)
    df_1000ht = df_khac[mask_ht].copy()
    df_rem2   = df_khac[~mask_ht].copy()

    # ── Bước 4: Chuyển chi nhánh ──────────────────────────────────────────────
    _set_prog(task_token, 70, "Bước 4 — Phân loại chuyển chi nhánh...")
    mask_ccn = _mark_ccn(df_rem2)
    df_ccn  = df_rem2[mask_ccn].copy()
    df_rem3 = df_rem2[~mask_ccn].copy()

    # ── Bước 5: Điện KO offline ───────────────────────────────────────────────
    _set_prog(task_token, 80, "Bước 5 — Phân loại điện KO offline...")
    mask_ko, mask_ko_candidate = _mark_ko(df_rem3)
    df_ko   = df_rem3[mask_ko].copy()
    df_rem4 = df_rem3[~mask_ko].copy()

    # ── Bước 6: Cân CN ────────────────────────────────────────────────────────
    _set_prog(task_token, 85, "Bước 6 — Phân loại Cân CN...")
    mask_can_cn   = _mark_can_cn(df_rem4)
    df_can_cn     = df_rem4[mask_can_cn].copy()
    df_khac_final = df_rem4[~mask_can_cn].copy()

    # Đánh dấu các dòng "nghi ngờ nhưng chưa đủ điều kiện" (1000HT hoặc KO) để chấm tay dễ hơn
    ghi_chu = pd.Series('', index=df_khac_final.index)
    ghi_chu[mask_ht_candidate.reindex(df_khac_final.index, fill_value=False)] = \
        'Nghi ngờ 1000HT — chưa khớp đủ cặp, cần chấm tay'
    ghi_chu[mask_ko_candidate.reindex(df_khac_final.index, fill_value=False)] = \
        'Nghi ngờ Điện KO offline — chưa khớp đủ cặp, cần chấm tay'
    df_khac_final['GHI_CHU'] = ghi_chu
    for tmp_df in (df_huy, df_di, df_1000ht, df_ccn, df_ko, df_can_cn):
        tmp_df['GHI_CHU'] = ''

    assert (len(df_huy) + len(df_di) + len(df_ccn) + len(df_ko) + len(df_can_cn)
            + len(df_1000ht) + len(df_khac_final)) == len(df), "Lỗi logic phân loại!"

    return df_huy, df_di, df_1000ht, df_ccn, df_ko, df_can_cn, df_khac_final


def _xe(s: str) -> str:
    """XML-escape cho nội dung text (không phải attribute)."""
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _styles_xml(header_argb: str) -> str:
    """Tạo styles.xml với 3 fonts, 4 fills, 2 borders, 6 cell styles.

    Styles:
      0 – default          1 – summary (bold white on header, no border)
      2 – col header       3 – number data (#,##0)
      4 – total text       5 – total number (#,##0 bold light-blue)
    """
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0"/></numFmts>'
        '<fonts count="3">'
          '<font><sz val="11"/><name val="Calibri"/></font>'
          f'<font><b/><sz val="11"/><name val="Calibri"/><color rgb="FFFFFFFF"/></font>'
          '<font><b/><sz val="11"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="4">'
          '<fill><patternFill patternType="none"/></fill>'
          '<fill><patternFill patternType="gray125"/></fill>'
          f'<fill><patternFill patternType="solid"><fgColor rgb="{header_argb}"/></patternFill></fill>'
          '<fill><patternFill patternType="solid"><fgColor rgb="FFD6EAF8"/></patternFill></fill>'
        '</fills>'
        '<borders count="2">'
          '<border><left/><right/><top/><bottom/><diagonal/></border>'
          '<border>'
            '<left style="thin"><color rgb="FF000000"/></left>'
            '<right style="thin"><color rgb="FF000000"/></right>'
            '<top style="thin"><color rgb="FF000000"/></top>'
            '<bottom style="thin"><color rgb="FF000000"/></bottom>'
            '<diagonal/>'
          '</border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="6">'
          '<xf numFmtId="0"   fontId="0" fillId="0" borderId="0" xfId="0"/>'
          '<xf numFmtId="0"   fontId="1" fillId="2" borderId="0" xfId="0"'
          ' applyFont="1" applyFill="1" applyAlignment="1">'
          '<alignment horizontal="left" vertical="center"/></xf>'
          '<xf numFmtId="0"   fontId="1" fillId="2" borderId="1" xfId="0"'
          ' applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
          '<alignment horizontal="center" vertical="center"/></xf>'
          '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
          '<xf numFmtId="0"   fontId="2" fillId="3" borderId="1" xfId="0"'
          ' applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
          '<alignment horizontal="left" vertical="center"/></xf>'
          '<xf numFmtId="164" fontId="2" fillId="3" borderId="1" xfId="0"'
          ' applyFont="1" applyFill="1" applyBorder="1" applyNumberFormat="1" applyAlignment="1">'
          '<alignment horizontal="right" vertical="center"/></xf>'
        '</cellXfs>'
        '</styleSheet>'
    )


_ROW_CHUNK = 5000  # dòng gộp mỗi lần ghi xuống stream — giới hạn đỉnh RAM ở mức 1 chunk


def _write_excel(df: pd.DataFrame, path: Path, sheet_name: str, hex_color: str) -> None:
    """Ghi XLSX bằng direct XML — 8x nhanh hơn xlsxwriter, giữ đủ formatting.

    sheet1.xml được STREAM trực tiếp vào ZIP theo từng lô _ROW_CHUNK dòng thay vì
    dựng toàn bộ chuỗi XML trong RAM rồi mới ghi — bucket "Lệnh Đi" cả triệu dòng từng
    gây MemoryError khi RAM máy trống thấp (xem Implementation-notes.html card 21) vì
    cách cũ giữ đồng thời list các chuỗi row + chuỗi nối + bản encode UTF-8 trong bộ nhớ.
    """
    df_out   = df[OUTPUT_COLS].reset_index(drop=True)
    n_data   = len(df_out)
    dr_total = float(df_out['DRAMOUNT'].sum())
    cr_total = float(df_out['CRAMOUNT'].sum())
    ncols    = len(OUTPUT_COLS)
    last_col = _COL_LETTERS[ncols - 1]

    summary = (f"{sheet_name}: {n_data:,} dòng  |  "
               f"Tổng Nợ: {dr_total:,.0f}  |  Tổng Có: {cr_total:,.0f}")

    styles   = _styles_xml(f'FF{hex_color.upper()}')
    num_idx  = frozenset(i for i, c in enumerate(OUTPUT_COLS) if c in _NUM_COLS)

    cols_xml = '<cols>' + ''.join(
        f'<col min="{i+1}" max="{i+1}" width="{COL_WIDTHS.get(col, 12)}" customWidth="1"/>'
        for i, col in enumerate(OUTPUT_COLS)
    ) + '</cols>'

    hdr = ''.join(
        f'<c r="{_COL_LETTERS[i]}2" t="inlineStr" s="2"><is><t>{col}</t></is></c>'
        for i, col in enumerate(OUTPUT_COLS)
    )

    sum_row = n_data + 3
    total: list[str] = [
        f'<c r="A{sum_row}" t="inlineStr" s="4"><is><t>TỔNG CỘNG</t></is></c>'
    ]
    for c_idx, col in enumerate(OUTPUT_COLS[1:], start=1):
        cl = _COL_LETTERS[c_idx]
        if col == 'DRAMOUNT':
            total.append(f'<c r="{cl}{sum_row}" s="5"><v>{dr_total:.2f}</v></c>')
        elif col == 'CRAMOUNT':
            total.append(f'<c r="{cl}{sum_row}" s="5"><v>{cr_total:.2f}</v></c>')
        else:
            total.append(f'<c r="{cl}{sum_row}" t="inlineStr" s="4"><is><t></t></is></c>')

    # ── Bundle thành XLSX (ZIP) ───────────────────────────────────────────────
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{_xe(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>'
    )
    pkg_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )

    with zipfile.ZipFile(str(path), 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml',         content_types)
        zf.writestr('_rels/.rels',                  pkg_rels)
        zf.writestr('xl/workbook.xml',              workbook_xml)
        zf.writestr('xl/_rels/workbook.xml.rels',   wb_rels)
        zf.writestr('xl/styles.xml',                styles)

        with zf.open('xl/worksheets/sheet1.xml', 'w') as fh:
            w = lambda s: fh.write(s.encode('utf-8'))
            w('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
            w('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
              ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">')
            w('<sheetViews><sheetView workbookViewId="0">'
              '<pane ySplit="2" topLeftCell="A3" activePane="bottomLeft" state="frozen"/>'
              '</sheetView></sheetViews>')
            w(cols_xml)
            w('<sheetData>')
            w(f'<row r="1"><c r="A1" t="inlineStr" s="1"><is><t>{_xe(summary)}</t></is></c></row>')
            w(f'<row r="2">{hdr}</row>')

            chunk: list[str] = []
            for row_0, row in enumerate(df_out.itertuples(index=False)):
                r_num = row_0 + 3
                cells: list[str] = []
                for c_idx, val in enumerate(row):
                    cl = _COL_LETTERS[c_idx]
                    if c_idx in num_idx:
                        cells.append(f'<c r="{cl}{r_num}" s="3"><v>{val:.2f}</v></c>')
                    else:
                        v = str(val).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        cells.append(f'<c r="{cl}{r_num}" t="inlineStr"><is><t>{v}</t></is></c>')
                chunk.append(f'<row r="{r_num}">{"".join(cells)}</row>')
                if len(chunk) >= _ROW_CHUNK:
                    w(''.join(chunk))
                    chunk = []
            if chunk:
                w(''.join(chunk))

            w(f'<row r="{sum_row}">{"".join(total)}</row>')
            w('</sheetData>')
            # OOXML CT_Worksheet yêu cầu thứ tự cố định: autoFilter PHẢI đứng TRƯỚC mergeCells.
            # Ghi sai thứ tự khiến Excel coi sheet1.xml là "unreadable content" và gỡ bỏ sheet.
            w(f'<autoFilter ref="A2:{last_col}{n_data + 2}"/>')
            w(f'<mergeCells count="1"><mergeCell ref="A1:{last_col}1"/></mergeCells>')
            w('</worksheet>')


def _cleanup_old_results(cutoff: float | None = None) -> None:
    """Xóa thư mục kết quả và progress entry cũ hơn `cutoff`.

    Mặc định là mốc 23h gần nhất đã trôi qua (backend/core/don_dep.py) — kết quả
    sống hết ngày làm việc thay vì tự bốc hơi sau 2 giờ như trước. Vì mốc đó
    không bao giờ rơi vào trong ngày đang chạy, hàm này vẫn gọi được ngay đầu
    một lượt xử lý mới mà không xoá mất kết quả người khác vừa chạy sáng nay.
    """
    cutoff = moc_don_gan_nhat() if cutoff is None else cutoff

    if TEMP_DIR.exists():
        for sub in TEMP_DIR.iterdir():
            # stat() nằm TRONG try, dù `is_dir()` đã chặn phần lớn: hai lượt dọn
            # chạy sát nhau (mỗi lượt xử lý mới đều gọi hàm này) vẫn có kẽ hở
            # giữa is_dir() và stat() để lượt kia xoá xong thư mục. Rơi vào kẽ
            # đó thì OSError ném thẳng ra giữa `process_files()` và người dùng
            # nhận lỗi 500 chẳng liên quan gì tới file họ vừa tải lên. Phòng xa,
            # chưa gặp thật — cùng cách `ach_service._cleanup_old_jobs()` làm.
            try:
                if sub.is_dir() and sub.stat().st_mtime < cutoff:
                    shutil.rmtree(sub)
            except OSError as e:
                log.warning("Không xóa được %s: %s", sub, e)

    # list(...) chụp nhanh trước khi duyệt — tránh RuntimeError nếu 1 request khác
    # gọi init_progress() làm thay đổi kích thước _progress cùng lúc (nhiều thread nền).
    stale = [k for k, v in list(_progress.items()) if v.get("_ts", 0) < cutoff]
    for k in stale:
        _progress.pop(k, None)
