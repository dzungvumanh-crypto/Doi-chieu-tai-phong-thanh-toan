"""Service chấm TK 459901-1000-000000000 — 3 nhóm (Cân ITT / Điện KO offline / GD khác).

Anh em của `cham459901_service` (TK 459901-1000-000007709, 7 nhóm): dùng lại cách đọc
file GL02 (zip/Excel), cách ghi Excel và khuôn tiến độ + tiến trình con của module đó.
Chỉ khác ba thứ: bộ lọc CUSTOMER, bộ phân loại (3 nhóm thay vì 7), và file phụ trợ duy
nhất là file tồn tháng trước (không có HUB đi/đến).

Hai module KHÔNG chung dữ liệu: thư mục tạm, bảng tiến độ, cửa `phien_doi_chieu` và mã
quyền đều riêng. Đừng gộp — hai mã CUSTOMER là hai sổ khác nhau.
"""

import logging
import re
import shutil
import threading
import time
import unicodedata
import uuid
import zipfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import numpy as np
import pandas as pd

from backend.core.config import BASE_DIR
from backend.core.don_dep import moc_don_gan_nhat
from backend.core.tien_trinh_doi_chieu import chay_tach, trong_tien_trinh_con
# Chỉ IMPORT từ module 459901 cũ (đọc GL02, helper ghi XML) — không sửa file đó.
from backend.services.cham459901_service import (
    COL_WIDTHS, DUOI_EXCEL, DUOI_HOP_LE, OUTPUT_COLS, InputError, _Cancelled, _COL_LETTERS,
    _doc_tep, _MAX_DATA_ROWS, _NUM_COLS, _ROW_CHUNK, _styles_xml, _ten_sheet, _xe,
)

# ─── Config ───────────────────────────────────────────────────────────────────
TEMP_DIR        = BASE_DIR / "data" / "temp_cham459901_000000000"
FILTER_LOCAC    = "459901"
FILTER_CUSTOMER = "1000-000000000"
FILTER_CCY      = "VND"

# Chuỗi nhận diện dòng Điện KO offline, nằm trong cột REMARK
CHUOI_KO = "Remitting Amount:VND"

TEN_TK = "459901-1000-000000000"
# ─────────────────────────────────────────────────────────────────────────────

# Cột dữ liệu vào (không có GHI_CHU — cột đó do chương trình sinh ra)
_COT_DU_LIEU = [c for c in OUTPUT_COLS if c != 'GHI_CHU']
_COT_LOC     = ('LOCAC', 'CUSTOMER', 'CCY')
# Chỉ strip các cột dùng để ghép khoá — không strip cả 17 cột
_COT_STRIP   = ('TRTP', 'REFERENCE', 'TRBRCD', 'DYTRSEQ', 'REMARK')

GHI_CHU_KO_THIEU_CHUOI = (
    f"Không có '{CHUOI_KO}' — chỉ khớp theo số tiền (Tổng Nợ = Tổng Có), cần soát lại"
)
GHI_CHU_NGHI_KO = "Nghi ngờ Điện KO offline — chưa khớp đủ cặp, cần chấm tay"

# Cột nhận diện một dòng bút toán — hai dòng trùng HẾT các cột này là cùng một bút toán bị đưa vào hai lần.
# Không tính CRTDTM (file tồn không có) và REMARK (có thể khác khoảng trắng).
_COT_KHOA_TRUNG = [
    'TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'REFERENCE', 'DRAMOUNT', 'CRAMOUNT',
]
# Excel chỉ chứa 1.048.576 dòng/sheet. Bản GL02 được mở bằng Excel rồi lưu lại mà dài sát trần này thì gần như
# chắc chắn đã bị cắt đuôi — dòng mất không để lại dấu vết. Đặt ngưỡng thấp hơn trần một chút vì có thể còn dòng tiêu đề.
_TRAN_DONG_EXCEL = 1_048_000

log = logging.getLogger(__name__)


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


# Một lượt bị bỏ dở quá lâu coi như đã chết, không được khoá chết tính năng —
# cùng mốc với `cham459901_service._TTL_DANG_CHAY`.
_TTL_DANG_CHAY = 4 * 3600


def luot_dang_chay() -> dict | None:
    """Lượt Chấm 459901-1000-000000000 đang chiếm máy chủ, None nếu rảnh."""
    now = time.time()
    # list(...) chụp nhanh — request khác có thể gọi init_progress() cùng lúc
    for token, p in list(_progress.items()):
        if p.get("done"):
            continue
        if now - p.get("_ts", 0) > _TTL_DANG_CHAY:
            continue
        return {
            "job_id":    token,
            "status":    "running",
            "tuoi_giay": max(0, int(now - p.get("_ts", now))),
        }
    return None


def tao_thu_muc_upload(task_token: str) -> Path:
    """Thư mục nhận file tải lên của một lượt: `<TEMP_DIR>/upload_<token>/`.

    Nằm cùng chỗ với thư mục kết quả nên `_cleanup_old_results()` trông coi luôn.
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
    """Xóa thư mục kết quả trên server. `result_token` phải đã qua `safe_filename()` ở API."""
    out_dir = TEMP_DIR / result_token
    if not out_dir.exists():
        return False
    shutil.rmtree(out_dir, ignore_errors=True)
    return True


def _bo_dau(s: str) -> str:
    s = unicodedata.normalize('NFD', s.lower().replace('đ', 'd'))
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')


def la_tep_khoa_office(filename: str) -> bool:
    """File khoá tạm `~$<tên>.xlsx` Office sinh ra khi đang mở file (165 byte, không phải Excel).

    Nằm cạnh file thật trong thư mục nên kéo-thả cả thư mục là mang theo. Không loại thì
    hoặc làm hỏng cả lượt ("không đọc được như file Excel"), hoặc — với `~$459_TON.xlsx` —
    bị nhận nhầm là file tồn và đè mất file tồn thật (file tồn tới sau thắng)."""
    return filename.startswith('~$')


def classify_upload_filename(filename: str) -> str | None:
    """Nhận diện file PHỤ TRỢ duy nhất theo tên: 'ton' (tồn tháng trước) hoặc None.

    Tên tồn có dạng `459_TON...` hoặc `459-mã 0...` (bỏ dấu, gạch dưới/gạch ngang/khoảng
    trắng đều được). File GL02 chính KHÔNG qua hàm này — tên gì cũng được, nhận theo đuôi
    (`DUOI_HOP_LE`) ở tầng gọi, và nhiều file được GỘP lại.
    """
    if la_tep_khoa_office(filename):
        return None
    name = _bo_dau(filename)
    if not name.endswith(DUOI_EXCEL):
        return None
    # `ton` phải là MỘT TỪ: bỏ dấu rồi "tổng"→"tong", "Boston", "Anton" đều chứa chuỗi "ton" — khớp trơn thì
    # file GL02 tên "…Tổng hợp…" bị nhận nhầm là file tồn và đè mất file tồn thật (module cũ không dính vì không bỏ dấu)
    if '459' in name and (re.search(r'(?<![a-z])ton(?![a-z])', name)
                          or re.search(r'(?<![a-z])ma[\s_\-]*0(?!\d)', name)):
        return 'ton'
    return None


def _set_prog(task_token: str | None, pct: int, msg: str) -> None:
    if task_token and task_token in _progress:
        p = _progress[task_token]
        if p["cancel_event"].is_set():
            raise _Cancelled()
        p["pct"] = pct
        p["msg"] = msg
        # Trong tiến trình con: `_progress` là bản sao, phải gửi tiến độ về backend
        gui_ve = p.get("_gui_ve")
        if gui_ve:
            gui_ve(pct, msg)


# ─── Public API ───────────────────────────────────────────────────────────────

def run_process(
    tep: list[tuple[str, Path]],
    task_token: str,
    ton: tuple[str, Path] | None = None,
) -> None:
    """Chạy process_files ở tiến trình riêng (`chay_tach`); cập nhật progress và bắt lỗi.

    Kết quả cuối ghi vào `_progress` Ở ĐÂY: `process_files` trong con chỉ ghi được vào bản sao."""
    p = _progress.get(task_token, {})

    def _cap_nhat(pct: int, msg: str) -> None:
        p["pct"], p["msg"] = pct, msg

    try:
        result = chay_tach(
            _xu_ly_tach, ten=f"Chấm {TEN_TK}",
            tep=tep, task_token=task_token, ton=ton,
            cancel_event=p.get("cancel_event"), callbacks={"tien_do_callback": _cap_nhat},
        )
        if result is None:   # bị buộc dừng sau lệnh Dừng (HAN_DUNG_GIAY)
            raise _Cancelled()
        if task_token in _progress:
            _progress[task_token].update({"pct": 100, "msg": "Hoàn thành!", "done": True, "result": result})
    except _Cancelled:
        if task_token in _progress:
            _progress[task_token].update({
                "done": True, "cancelled": True, "msg": "Đã dừng theo yêu cầu.",
            })
    except InputError as e:
        # File sai — không phải lỗi hệ thống, người dùng tự sửa được.
        log.warning("cham459901_000000000 file không hợp lệ [%s]: %s", task_token, e)
        if task_token in _progress:
            _progress[task_token].update({"done": True, "error": str(e), "msg": str(e)})
    except Exception as e:
        log.error("cham459901_000000000 process_files lỗi [%s]: %s", task_token, e, exc_info=True)
        if task_token in _progress:
            _progress[task_token].update({
                "done": True, "error": str(e),
                "msg": "Lỗi xử lý — xem log server",
            })


def _xu_ly_tach(
    tep, task_token, ton, log_callback, cancel_event, tien_do_callback,
) -> dict:
    """Điểm vào của `chay_tach` — cùng khuôn `cham459901_service._xu_ly_tach`.

    Chỉ dựng mục `_progress` cục bộ khi ĐANG Ở TRONG CON: chạy trong luồng
    (DOI_CHIEU_TIEN_TRINH=0) thì mục thật đã có, dựng thêm là để lại mục "ma"."""
    if trong_tien_trinh_con():
        _progress[task_token] = {
            "pct": 0, "msg": "", "done": False, "error": None, "cancelled": False,
            "result": None, "cancel_event": cancel_event, "_ts": time.time(),
            "_gui_ve": tien_do_callback,
        }
    return process_files(tep, task_token, ton)


def process_files(
    tep: list[tuple[str, Path]],
    task_token: str | None = None,
    ton: tuple[str, Path] | None = None,
) -> dict:
    """Nhiều file GL02 ZIP/Excel [(tên hiển thị, đường dẫn)] (+ tùy chọn 1 file tồn tháng
    trước) → lọc TK → phân loại 3 nhóm → lưu 3 xlsx → trả metadata.

    Thiếu file tồn → chạy như thường, chỉ không ghép dữ liệu tháng trước.
    """
    if not tep:
        raise InputError("Chưa chọn file nào.")

    _cleanup_old_results()
    t0 = time.time()

    _set_prog(task_token, 5, "Đang đọc dữ liệu...")
    df, filtered_rows, canh_bao = _doc_va_loc(tep, task_token, 5, 25)
    total_before = len(df) + filtered_rows
    so_dong_gl02 = len(df)

    ton_rows_added = 0
    if ton is not None:
        _set_prog(task_token, 26, "Đang đọc file tồn tháng trước...")
        df_ton, _, cb_ton = _doc_va_loc([ton], task_token, 26, 28)
        canh_bao += cb_ton
        ton_rows_added = len(df_ton)
        # Dòng tồn đứng trước: cùng REFERENCE với dòng tháng này thì vẫn cân được
        df = pd.concat([df_ton, df], ignore_index=True)

    if df.empty:
        raise InputError(
            f"Không có dòng nào của TK {TEN_TK} (LOCAC={FILTER_LOCAC}, CUSTOMER="
            f"{FILTER_CUSTOMER}, CCY={FILTER_CCY}) trong các file đã tải lên — "
            "kiểm tra lại file GL02 có đúng kỳ và đúng tài khoản không."
        )

    # ── Các dấu hiệu dữ liệu vào có vấn đề mà KHÔNG làm pipeline lỗi — nói ra thay vì im lặng ──
    if so_dong_gl02 == 0:
        canh_bao.append(
            f"Các file GL02 không có dòng nào của TK {TEN_TK} — kết quả chỉ gồm {ton_rows_added:,} dòng "
            "tồn. Kiểm tra lại file GL02 có đúng kỳ và đúng tài khoản không."
        )
    so_trung = int(df.duplicated(subset=_COT_KHOA_TRUNG).sum())
    if so_trung:
        # KHÔNG tự xoá: hai bút toán giống hệt nhau có thể là thật. Nhưng nếu là một file bị chọn hai lần
        # (tên khác nhau) hay file tồn trùng GL02 thì mọi dòng nhân đôi mà vẫn cân — không lỗi nào báo.
        canh_bao.append(
            f"Có {so_trung:,} dòng trùng hoàn toàn (cùng ngày, JOURSEQ, DYTRSEQ, REFERENCE, số tiền) — có thể "
            "một file bị chọn hai lần hoặc file tồn trùng với file GL02. Các dòng này VẪN được tính; nếu số "
            "dòng tăng gấp đôi bất thường thì kiểm tra lại các file đã chọn."
        )

    df_can_itt, df_ko, df_khac = _phan_loai(df, task_token)

    result_token = str(uuid.uuid4())
    out_dir = TEMP_DIR / result_token
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        _set_prog(task_token, 85, f"Xuất Excel — GD cân ITT ({len(df_can_itt):,} dòng)...")
        _ghi_excel(df_can_itt, out_dir / "can_itt.xlsx", "GD cân ITT",     "27AE60")

        _set_prog(task_token, 90, f"Xuất Excel — Điện KO offline ({len(df_ko):,} dòng)...")
        _ghi_excel(df_ko,      out_dir / "ko.xlsx",      "Điện KO offline", "16A085")

        _set_prog(task_token, 95, f"Xuất Excel — GD khác ({len(df_khac):,} dòng)...")
        _ghi_excel(df_khac,    out_dir / "khac.xlsx",    "GD khác",         "E67E22")

        # Checkpoint cuối — bấm Dừng đúng lúc ghi file cuối vẫn phải phát hiện được
        _set_prog(task_token, 99, "Đang hoàn tất...")
    except _Cancelled:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise

    result = {
        "token":               result_token,
        "can_itt_rows":        len(df_can_itt),
        "ko_rows":             len(df_ko),
        "khac_rows":           len(df_khac),
        # dòng KO chỉ khớp theo số tiền, không có chuỗi Remitting Amount — UI nhắc soát lại
        "ko_thieu_chuoi_rows": int((df_ko['GHI_CHU'] == GHI_CHU_KO_THIEU_CHUOI).sum()),
        # dòng GD khác có chuỗi Remitting Amount nhưng chưa khớp đủ cặp
        "khac_nghi_ko_rows":   int((df_khac['GHI_CHU'] == GHI_CHU_NGHI_KO).sum()),
        # total_before chốt TRƯỚC khi ghép df_ton — không cộng thêm thì bảng kết quả
        # báo thiếu đúng bằng số dòng tồn, trong khi 3 nhóm đã tính cả chúng
        "total_rows":          total_before + ton_rows_added,
        "filtered_rows":       filtered_rows,
        "n_files":             len(tep),
        "ton_rows_added":      ton_rows_added,
        # Phân biệt "không chọn file tồn" với "có chọn nhưng không có dòng nào của TK này" —
        # thiếu tồn thì dòng đối ứng của giao dịch tồn rơi về GD khác, màn hình phải nói rõ
        "ton_provided":        ton is not None,
        # Cảnh báo dữ liệu vào (Excel bị cắt, trùng dòng, GL02 không có dòng nào của TK…) — UI hiện từng dòng
        "canh_bao":            canh_bao,
        "elapsed_s":           round(time.time() - t0, 1),
        "process_date":        datetime.now().strftime("%Y%m%d"),
    }

    if task_token and task_token in _progress:
        _progress[task_token].update({
            "pct": 100, "msg": "Hoàn thành!",
            "done": True, "result": result,
        })

    return result


# ─── Internal — đọc + lọc ─────────────────────────────────────────────────────

def _loc_tai_khoan(d: pd.DataFrame) -> pd.DataFrame:
    """Giữ đúng các dòng của TK 459901-1000-000000000 (LOCAC + CUSTOMER + CCY)."""
    khop = pd.Series(True, index=d.index)
    for col, gia_tri in zip(_COT_LOC, (FILTER_LOCAC, FILTER_CUSTOMER, FILTER_CCY)):
        khop &= d[col].astype(str).str.strip() == gia_tri
    return d[khop].copy()


_KHONG = Decimal(0)


def _sang_decimal(chu: str, gia_tri_float: float) -> Decimal:
    """Ô tiền → Decimal CHÍNH XÁC, dựng từ chuỗi gốc chứ không đi qua float.

    Chỉ gọi cho ô đã qua kiểm `to_numeric`; nếu `Decimal` vẫn không nhận dạng chuỗi (hiếm: kiểu viết mà pandas
    chịu còn `Decimal` thì không) thì lấy `repr` của float — vẫn không bao giờ là `round()`."""
    try:
        return Decimal(chu)
    except InvalidOperation:
        return Decimal(repr(float(gia_tri_float)))


def _chuan_hoa(d: pd.DataFrame, nhan: str = "File") -> pd.DataFrame:
    """Đưa bảng đã lọc về đúng bộ cột dữ liệu: cột thiếu (vd CRTDTM của file tồn) → rỗng.

    Cột tiền: ô TRỐNG là 0 (bình thường); ô có chữ mà không phải số thì BÁO LỖI, cả hai cột một lần.
    Trước đây `errors='coerce'` + `fillna(0)` đổi thẳng `"1,000"` thành 0: cặp Nợ/Có bằng nhau không còn
    cân, rơi hết xuống GD khác mà không ai biết vì sao. Không tự đoán dấu phẩy/chấm — "1.234" có thể là
    một nghìn hai trăm ba mươi tư hoặc 1,234 — đoán sai là đổi số tiền.

    Mỗi cột tiền có HAI dạng: `DRAMOUNT`/`CRAMOUNT` (float, chỉ để ghi Excel) và `_DR_DEC`/`_CR_DEC`
    (Decimal chính xác, dùng cho MỌI phép so sánh/cộng số tiền — checklist mục E: không `round()`/`==` trên float)."""
    d = d.reindex(columns=_COT_DU_LIEU)
    for col in _COT_DU_LIEU:
        if col not in ('DRAMOUNT', 'CRAMOUNT'):
            d[col] = d[col].fillna('').astype(str)

    so: dict[str, pd.Series] = {}
    dec: dict[str, pd.Series] = {}
    loi_cot: list[str] = []
    mo_ho_cot: list[str] = []
    for col in ('DRAMOUNT', 'CRAMOUNT'):
        s = d[col]
        v = pd.to_numeric(s, errors='coerce')
        chu = s.astype(str).str.strip()
        trong = (chu == '') | chu.str.lower().isin(['nan', 'none'])
        # NaN (không đọc được) và ±inf đều là lỗi, trừ ô trống hẳn
        loi = ~np.isfinite(v) & ~trong
        if loi.any():
            loi_cot.append(
                f"cột {col}: {int(loi.sum()):,} dòng (ví dụ REFERENCE "
                f"'{d.loc[loi, 'REFERENCE'].iloc[0]}' có '{chu[loi].iloc[0]}')"
            )
        # "1.000" / "180.000" (đúng 3 chữ số sau dấu chấm): cách viết Việt Nam của "một nghìn" / "một trăm tám
        # mươi nghìn", nhưng máy đọc thành 1 / 180 — sai gấp 1000 lần mà không báo (checklist mục E). VND không có
        # phần lẻ 3 chữ số nên coi là mơ hồ và chặn, thay vì đoán.
        mo_ho = chu.str.fullmatch(r'-?\d{1,3}\.\d{3}') & ~trong
        if mo_ho.any():
            mo_ho_cot.append(
                f"cột {col}: {int(mo_ho.sum()):,} dòng (ví dụ REFERENCE "
                f"'{d.loc[mo_ho, 'REFERENCE'].iloc[0]}' có '{chu[mo_ho].iloc[0]}')"
            )
        so[col] = v.fillna(0.0).astype(float)
        dec[col] = pd.Series(
            [_KHONG if t else _sang_decimal(c, f) for c, t, f in zip(chu, trong, so[col])],
            index=d.index, dtype=object,
        )
    if loi_cot:
        raise InputError(
            f"{nhan} có ô tiền không phải số — {'; '.join(loi_cot)}. Đổi các ô đó về dạng số (bỏ dấu "
            "phân cách hàng nghìn) rồi chạy lại — chương trình không tự đoán để khỏi làm sai số tiền."
        )
    if mo_ho_cot:
        raise InputError(
            f"{nhan} có ô tiền dạng 'x.yyy' mơ hồ — {'; '.join(mo_ho_cot)}. '1.000' có thể là một nghìn "
            "(cách viết Việt Nam) hoặc 1,000 — chương trình không tự đoán vì sai là lệch gấp 1000 lần. "
            "Đổi các ô đó về số thường (vd 1000) rồi chạy lại."
        )
    d['DRAMOUNT'], d['CRAMOUNT'] = so['DRAMOUNT'], so['CRAMOUNT']
    d['_DR_DEC'], d['_CR_DEC'] = dec['DRAMOUNT'], dec['CRAMOUNT']

    for col in _COT_STRIP:
        d[col] = d[col].str.strip()
    return d


def _doc_va_loc(
    tep: list[tuple[str, Path]],
    task_token: str | None,
    pct_dau: int,
    pct_cuoi: int,
) -> tuple[pd.DataFrame, int, list[str]]:
    """Đọc các file (ZIP/Excel), LỌC TỪNG BẢNG ngay khi đọc rồi mới gộp.

    Lọc trước khi gộp (khác module 000007709 lọc sau khi gộp): file GL02 cả tháng có vài
    triệu dòng mà TK này chỉ có vài nghìn — gộp hết rồi mới lọc là ôm cả triệu dòng vô ích.
    Trả (bảng đã lọc, số dòng bị loại, các cảnh báo cần hiện cho người dùng)."""
    khung: list[pd.DataFrame] = []
    canh_bao: list[str] = []
    loai = 0
    n = len(tep)
    for i, (ten, duong_dan) in enumerate(tep, 1):
        _set_prog(task_token, pct_dau + ((pct_cuoi - pct_dau) * (i - 1)) // n,
                  f"Đang đọc dữ liệu ({i}/{n}): {ten}...")
        nhan = f"File '{ten}'"
        la_excel = Path(ten).suffix.lower() in DUOI_EXCEL
        for d in _doc_tep(ten, duong_dan):
            # REFERENCE không nằm trong cột bắt buộc của bộ đọc chung, mà thiếu nó thì KHÔNG cặp nào cân ITT được
            # — điền rỗng cả cột là mọi dòng rơi xuống KO/GD khác mà không có lỗi nào.
            if 'REFERENCE' not in d.columns:
                raise InputError(
                    f"{nhan} thiếu cột REFERENCE — không ghép được GD cân ITT (cột đang có: "
                    f"{', '.join(map(str, d.columns[:8]))}…). Kiểm tra lại file có đúng là bản xuất GL02 không."
                )
            if la_excel and len(d) >= _TRAN_DONG_EXCEL:
                canh_bao.append(
                    f"{nhan} có {len(d):,} dòng — sát trần 1.048.576 dòng/sheet của Excel, nhiều khả năng "
                    "Excel đã cắt bớt các dòng cuối (mất dòng mà không báo). Xuất lại GL02 chia thành nhiều "
                    "file hoặc dùng bản .zip gốc rồi chạy lại."
                )
            d_loc = _loc_tai_khoan(d)
            loai += len(d) - len(d_loc)
            khung.append(_chuan_hoa(d_loc, nhan))

    df = pd.concat(khung, ignore_index=True) if khung else _chuan_hoa(pd.DataFrame())
    return df, loai, canh_bao


# ─── Internal — phân loại ─────────────────────────────────────────────────────

def _tong_theo_khoa(khoa: pd.Series, gia_tri: pd.Series) -> pd.Series:
    """Tổng `Decimal` CHÍNH XÁC theo từng khoá, trải lại theo từng dòng (như `groupby().transform('sum')`).

    Tự cộng bằng vòng lặp thay vì `groupby.sum()`: cột kiểu object chứa Decimal không nằm trong đường được
    pandas bảo đảm, còn ở đây phải chắc chắn từng phép cộng là Decimal — không im lặng rơi về float."""
    tong: dict = {}
    for k, v in zip(khoa, gia_tri):
        tong[k] = tong.get(k, _KHONG) + v
    return khoa.map(tong)


def _mark_can_itt(df: pd.DataFrame) -> pd.Series:
    """Cân ITT: các dòng CÙNG REFERENCE mà Tổng DRAMOUNT = Tổng CRAMOUNT.

    Cần ≥ 2 dòng và có ít nhất một dòng khác 0 — một dòng lẻ, hoặc nhóm toàn dòng 0, không phải "một
    cặp giao dịch". KHÔNG đòi đủ cả hai phía Nợ/Có: yêu cầu chỉ nói "cùng REFERENCE, Tổng DRAMOUNT = Tổng
    CRAMOUNT", nên cặp Cancel/Normal cùng REFERENCE (kể cả cùng một phía, dấu ngược nhau, tổng triệt tiêu) cũng
    rơi vào đây, không xét TRTP. REFERENCE rỗng không được gom chung thành một nhóm.
    """
    ref = df['REFERENCE'].str.strip()
    sum_dr = _tong_theo_khoa(ref, df['_DR_DEC'])
    sum_cr = _tong_theo_khoa(ref, df['_CR_DEC'])
    n      = ref.groupby(ref).transform('size')
    co_tien = ((df['_DR_DEC'] != _KHONG) | (df['_CR_DEC'] != _KHONG)).groupby(ref).transform('any')
    # `==` chính xác trên Decimal: không dung sai, không làm tròn (10,0004 KHÔNG cân với 10,0000)
    return (ref != '') & (n >= 2) & co_tien & (sum_dr == sum_cr)


def _mark_ko(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Điện KO offline — trả (ko, ko_thieu_chuoi).

    Gom các dòng CÒN LẠI (sau Cân ITT) theo số tiền tuyệt đối. Nhóm nào có ≥ 2 dòng và
    Tổng DRAMOUNT = Tổng CRAMOUNT thì cả nhóm là Điện KO offline (một điện KO ghi Có vào
    TK này bằng REMARK 'Remitting Amount:VND<số tiền>', vế Nợ đối ứng là dòng khác REFERENCE
    cùng số tiền — nên khoá ghép là SỐ TIỀN, không phải REFERENCE).

    Nhóm cân nhưng KHÔNG dòng nào chứa chuỗi vẫn vào KO (bản chấm tay tháng 7/2026 xếp cặp
    NAPAS 7.465.869.595.881 và bút toán điều chỉnh −7.465.869.595.881 vào đây) — nhưng đánh
    dấu `ko_thieu_chuoi` để ghi GHI_CHU cho người chấm soát lại.
    """
    # Khoá nhóm = số tiền tuyệt đối CHÍNH XÁC (Decimal, không làm tròn): hai số khác nhau dù chỉ 0,001 là hai nhóm
    amt = pd.Series(
        [max(abs(dr), abs(cr)) for dr, cr in zip(df['_DR_DEC'], df['_CR_DEC'])],
        index=df.index, dtype=object,
    )
    co_chuoi = df['REMARK'].str.contains(CHUOI_KO, case=False, regex=False, na=False)
    sum_dr = _tong_theo_khoa(amt, df['_DR_DEC'])
    sum_cr = _tong_theo_khoa(amt, df['_CR_DEC'])
    n      = amt.groupby(amt).transform('size')
    nhom_co_chuoi = co_chuoi.groupby(amt).transform('any')

    ko = (amt > _KHONG) & (n >= 2) & (sum_dr == sum_cr)
    return ko, ko & ~nhom_co_chuoi


def _phan_loai(
    df: pd.DataFrame, task_token: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Cascade: Cân ITT → Điện KO offline (trên phần còn lại) → GD khác (phần dư)."""
    _set_prog(task_token, 30, "Bước 1 — Xác định GD cân ITT...")
    df = df.reset_index(drop=True)
    df['GHI_CHU'] = ''
    can_itt = _mark_can_itt(df)
    df_can_itt = df[can_itt]

    _set_prog(task_token, 50, "Bước 2 — Xác định Điện KO offline...")
    con_lai = df[~can_itt].reset_index(drop=True)
    ko, ko_thieu_chuoi = _mark_ko(con_lai)
    con_lai.loc[ko_thieu_chuoi, 'GHI_CHU'] = GHI_CHU_KO_THIEU_CHUOI
    df_ko = con_lai[ko]

    _set_prog(task_token, 70, "Bước 3 — GD khác (còn lại, chấm thủ công)...")
    df_khac = con_lai[~ko].copy()
    nghi = df_khac['REMARK'].str.contains(CHUOI_KO, case=False, regex=False, na=False)
    df_khac.loc[nghi, 'GHI_CHU'] = GHI_CHU_NGHI_KO

    # Ba nhóm phải cộng đúng bằng tổng — sót/dư một dòng là lỗi thuật toán, không được im lặng
    assert len(df_can_itt) + len(df_ko) + len(df_khac) == len(df), (
        f"Phân loại lệch: {len(df_can_itt)}+{len(df_ko)}+{len(df_khac)} != {len(df)}"
    )
    return df_can_itt.reset_index(drop=True), df_ko.reset_index(drop=True), df_khac.reset_index(drop=True)


# ─── Internal — ghi Excel (có cột STT) ────────────────────────────────────────

# Cột STT (số thứ tự) làm cột A, đứng trước các cột GL02. Hàm ghi của module 459901 cũ KHÔNG có cột này và
# không được sửa (thuộc phần của người khác), nên module này có hàm riêng — dựa trên cùng khuôn XML/style.
_COT_XUAT = ['STT'] + OUTPUT_COLS
_DO_RONG = {'STT': 7, **COL_WIDTHS}


def _ghi_excel(df: pd.DataFrame, path: Path, sheet_name: str, hex_color: str) -> None:
    """Ghi XLSX bằng direct XML (stream theo lô, như `cham459901_service._write_excel`) kèm cột STT.

    STT là SỐ (sắp xếp/lọc được), đánh liên tục xuyên các sheet khi nhóm bị tách quá trần dòng của Excel.
    Nhãn TỔNG CỘNG nằm ở cột B (cột A là STT, hẹp không đủ chỗ). Chỉ ghi float ra Excel — các cột Decimal
    phụ (`_DR_DEC`/`_CR_DEC`) không nằm trong `OUTPUT_COLS` nên không lọt ra file."""
    df_out   = df[OUTPUT_COLS].reset_index(drop=True)
    n_data   = len(df_out)
    dr_total = float(df_out['DRAMOUNT'].sum())
    cr_total = float(df_out['CRAMOUNT'].sum())
    last_col = _COL_LETTERS[len(_COT_XUAT) - 1]

    styles  = _styles_xml(f'FF{hex_color.upper()}')
    num_idx = frozenset(i for i, c in enumerate(_COT_XUAT) if c in _NUM_COLS)

    cols_xml = '<cols>' + ''.join(
        f'<col min="{i+1}" max="{i+1}" width="{_DO_RONG.get(col, 12)}" customWidth="1"/>'
        for i, col in enumerate(_COT_XUAT)
    ) + '</cols>'
    hdr = ''.join(
        f'<c r="{_COL_LETTERS[i]}2" t="inlineStr" s="2"><is><t>{col}</t></is></c>'
        for i, col in enumerate(_COT_XUAT)
    )

    # Quá _MAX_DATA_ROWS dòng thì cắt sang sheet mới trong cùng file; bucket rỗng vẫn có đúng 1 sheet.
    tong_phan = max(1, -(-n_data // _MAX_DATA_ROWS))
    if tong_phan > 1:
        log.warning(
            "cham459901_000000000: '%s' có %s dòng, vượt giới hạn %s của một sheet Excel "
            "→ tách thành %d sheet trong cùng file %s",
            sheet_name, f"{n_data:,}", f"{_MAX_DATA_ROWS:,}", tong_phan, path.name,
        )
    lat_cat = [(k * _MAX_DATA_ROWS, min((k + 1) * _MAX_DATA_ROWS, n_data)) for k in range(tong_phan)]

    sheets_xml = ''.join(
        f'<sheet name="{_xe(_ten_sheet(sheet_name, k + 1, tong_phan))}" sheetId="{k + 1}" r:id="rId{k + 1}"/>'
        for k in range(tong_phan)
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{sheets_xml}</sheets></workbook>'
    )
    rel_sheets = ''.join(
        f'<Relationship Id="rId{k + 1}"'
        ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"'
        f' Target="worksheets/sheet{k + 1}.xml"/>'
        for k in range(tong_phan)
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{rel_sheets}'
        f'<Relationship Id="rId{tong_phan + 1}"'
        ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"'
        ' Target="styles.xml"/></Relationships>'
    )
    pkg_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    override_sheets = ''.join(
        f'<Override PartName="/xl/worksheets/sheet{k + 1}.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for k in range(tong_phan)
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        f'{override_sheets}'
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

        for k, (dau, cuoi) in enumerate(lat_cat):
            phan_df = df_out.iloc[dau:cuoi]
            n_part  = len(phan_df)
            dr_part = float(phan_df['DRAMOUNT'].sum())
            cr_part = float(phan_df['CRAMOUNT'].sum())

            # Một phần thì giữ câu chữ gọn; nhiều phần thì nói rõ phần nào, tổng cuối sheet là tổng CỦA PHẦN ĐÓ.
            if tong_phan == 1:
                summary   = (f"{sheet_name}: {n_data:,} dòng  |  "
                             f"Tổng Nợ: {dr_total:,.0f}  |  Tổng Có: {cr_total:,.0f}")
                nhan_tong = "TỔNG CỘNG"
            else:
                summary   = (f"{sheet_name} — phần {k + 1}/{tong_phan}: dòng "
                             f"{dau + 1:,}–{cuoi:,} trong tổng {n_data:,} dòng  |  "
                             f"Tổng Nợ cả nhóm: {dr_total:,.0f}  |  Tổng Có cả nhóm: {cr_total:,.0f}")
                nhan_tong = f"TỔNG CỘNG PHẦN {k + 1}/{tong_phan}"

            sum_row = n_part + 3
            total: list[str] = [
                f'<c r="A{sum_row}" t="inlineStr" s="4"><is><t></t></is></c>',                        # cột STT
                f'<c r="B{sum_row}" t="inlineStr" s="4"><is><t>{_xe(nhan_tong)}</t></is></c>',        # nhãn ở cột B
            ]
            for c_idx, col in enumerate(OUTPUT_COLS[1:], start=2):
                cl = _COL_LETTERS[c_idx]
                if col == 'DRAMOUNT':
                    total.append(f'<c r="{cl}{sum_row}" s="5"><v>{dr_part:.2f}</v></c>')
                elif col == 'CRAMOUNT':
                    total.append(f'<c r="{cl}{sum_row}" s="5"><v>{cr_part:.2f}</v></c>')
                else:
                    total.append(f'<c r="{cl}{sum_row}" t="inlineStr" s="4"><is><t></t></is></c>')

            with zf.open(f'xl/worksheets/sheet{k + 1}.xml', 'w') as fh:
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
                for row_0, row in enumerate(phan_df.itertuples(index=False)):
                    r_num = row_0 + 3
                    # STT: `dau` = số dòng đã ghi ở các phần trước → liên tục xuyên sheet
                    cells: list[str] = [f'<c r="A{r_num}"><v>{dau + row_0 + 1}</v></c>']
                    for c_idx, val in enumerate(row, start=1):
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
                # OOXML CT_Worksheet: autoFilter PHẢI đứng TRƯỚC mergeCells, sai thứ tự Excel gỡ bỏ sheet
                w(f'<autoFilter ref="A2:{last_col}{n_part + 2}"/>')
                w(f'<mergeCells count="1"><mergeCell ref="A1:{last_col}1"/></mergeCells>')
                w('</worksheet>')


def _cleanup_old_results(cutoff: float | None = None) -> None:
    """Xóa thư mục kết quả và progress entry cũ hơn `cutoff` (mặc định: mốc 23h gần nhất)."""
    cutoff = moc_don_gan_nhat() if cutoff is None else cutoff

    if TEMP_DIR.exists():
        for sub in TEMP_DIR.iterdir():
            # stat() nằm TRONG try: hai lượt dọn chạy sát nhau có kẽ hở giữa is_dir()
            # và stat() để lượt kia xoá xong thư mục — xem cham459901_service._cleanup_old_results
            try:
                if sub.is_dir() and sub.stat().st_mtime < cutoff:
                    shutil.rmtree(sub)
            except OSError as e:
                log.warning("Không xóa được %s: %s", sub, e)

    stale = [k for k, v in list(_progress.items()) if v.get("_ts", 0) < cutoff]
    for k in stale:
        _progress.pop(k, None)


# Khai với chốt chặn dùng chung — xem backend/core/phien_doi_chieu.py.
# Đặt CUỐI file: `luot_dang_chay` phải tồn tại trước khi đem đi khai.
from backend.core.phien_doi_chieu import dang_ky_nguon  # noqa: E402

dang_ky_nguon("cham459901_000000000", f"Chấm TK {TEN_TK}", luot_dang_chay)
