"""Service phân loại bút toán tài khoản 459901.

Logic phân loại (3 phase) port nguyên từ phan_loai_459901.py — KHÔNG THAY ĐỔI.
I/O được điều chỉnh để hoạt động với bytes (từ HTTP upload) thay vì file path.
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
TEMP_DIR        = Path("data/temp_cham459901")
ZIP_PASSWORD    = b"DACwLdHi"
FILTER_LOCAC    = "459901"
FILTER_CUSTOMER = "1000-000007709"
FILTER_CCY      = "VND"
CLEANUP_HOURS   = 2
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

# Chỉ strip các cột dùng trong filter và xây key — không strip tất cả string cols
_STRIP_COLS = {'LOCAC', 'CUSTOMER', 'CCY', 'TRTP', 'REFERENCE', 'TRBRCD', 'DYTRSEQ', 'REMARK'}

_NUM_COLS = frozenset({'DRAMOUNT', 'CRAMOUNT'})

# A–Z rồi AA, AB, … (đủ cho 30 cột)
_COL_LETTERS = [
    (chr(65 + i) if i < 26 else chr(64 + i // 26) + chr(65 + i % 26))
    for i in range(30)
]

log = logging.getLogger(__name__)


class _Cancelled(Exception):
    """Sentinel nội bộ — báo hiệu người dùng đã bấm Dừng, thoát sớm khỏi xử lý."""


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
    """Xóa thư mục kết quả trên server (khi người dùng phát hiện sai sót, muốn làm lại)."""
    out_dir = TEMP_DIR / result_token
    if not out_dir.exists():
        return False
    shutil.rmtree(out_dir, ignore_errors=True)
    return True


def classify_upload_filename(filename: str) -> str | None:
    """Tự nhận diện loại file theo tên khi upload nhiều file cùng lúc (kéo-thả kiểu ACH).
    Trả về 'zip' | 'hub_di' | 'hub_den' | None (không nhận diện được)."""
    name = filename.lower()
    if name.endswith('.zip') and 'gl02' in name:
        return 'zip'
    if name.endswith('.xlsx'):
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

class InputError(ValueError):
    """Lỗi do chính file người dùng tải lên — thông báo hiển thị thẳng cho họ."""


def run_process(
    zip_bytes: bytes,
    task_token: str,
    hub_di_bytes: bytes | None = None,
    hub_den_bytes: bytes | None = None,
) -> None:
    """Chạy process_zip trong background thread; cập nhật progress và bắt lỗi."""
    try:
        process_zip(zip_bytes, hub_di_bytes, hub_den_bytes, task_token)
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
        log.error("process_zip lỗi [%s]: %s", task_token, e, exc_info=True)
        if task_token in _progress:
            _progress[task_token].update({
                "done": True, "error": str(e),
                "msg": "Lỗi xử lý — xem log server",
            })


def process_zip(
    zip_bytes: bytes,
    hub_di_bytes: bytes | None = None,
    hub_den_bytes: bytes | None = None,
    task_token: str | None = None,
) -> dict:
    """Nhận bytes ZIP (+ 2 file HUB đi/đến tùy chọn) → phân loại 7 nhóm → lưu 7 xlsx → trả metadata.

    Thiếu file HUB → bỏ qua bước 1000 Hoàn trả (các dòng đó rơi về GD khác chấm thủ công).
    """
    _cleanup_old_results()
    t0 = time.time()

    _set_prog(task_token, 5, "Đang giải mã và đọc dữ liệu...")
    df, filtered_rows = _load_data(zip_bytes)
    total_before = len(df) + filtered_rows

    hub_di = hub_den = None
    if hub_di_bytes is not None and hub_den_bytes is not None:
        _set_prog(task_token, 15, "Đang đọc file HUB đi/đến...")
        hub_di  = _read_hub_di(hub_di_bytes)
        hub_den = _read_hub_den(hub_den_bytes)

    _set_prog(task_token, 30, "Bước 1 — Xác định lệnh hủy...")
    df_huy, df_di, df_1000ht, df_ccn, df_ko, df_can_cn, df_khac = _classify(
        df, task_token, hub_di, hub_den,
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
        "token":         result_token,
        "huy_rows":      len(df_huy),
        "di_rows":       len(df_di),
        "ht1000_rows":   len(df_1000ht),
        "ccn_rows":      len(df_ccn),
        "ko_rows":       len(df_ko),
        "can_cn_rows":   len(df_can_cn),
        "khac_rows":     len(df_khac),
        "total_rows":    total_before,
        "filtered_rows": filtered_rows,
        "hub_provided":  hub_di is not None,
        "elapsed_s":     round(time.time() - t0, 1),
        "process_date":  datetime.now().strftime("%Y%m%d"),
    }

    if task_token and task_token in _progress:
        _progress[task_token].update({
            "pct": 100, "msg": "Hoàn thành!",
            "done": True, "result": result,
        })

    return result


# ─── Internal ─────────────────────────────────────────────────────────────────

def _load_data(zip_bytes: bytes) -> tuple[pd.DataFrame, int]:
    buf = io.BytesIO(zip_bytes)
    dfs = []
    try:
        with _ZipFile(buf) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith('.csv')]
            for csv_name in csv_names:
                raw = zf.read(csv_name, pwd=ZIP_PASSWORD)
                dfs.append(pd.read_csv(
                    io.BytesIO(raw),
                    encoding='utf-8-sig',
                    dtype=str,
                    keep_default_na=False,
                ))
    except _BAD_ZIP as e:
        raise InputError(
            "File tải lên không phải file .zip hợp lệ — có thể tải bị lỗi, "
            "bị cắt dở, hoặc chỉ được đổi đuôi tên thành .zip."
        ) from e
    except RuntimeError as e:
        raise InputError(
            "Không giải nén được file .zip — sai mật khẩu hoặc file dùng kiểu "
            "mã hoá khác với file xuất từ IPCAS."
        ) from e

    # Trước đây dfs rỗng → dfs[0] ném IndexError('list index out of range'),
    # người dùng chỉ thấy đúng câu đó, không biết phải sửa gì.
    if not dfs:
        raise InputError("File .zip không chứa file .csv nào — cần file dữ liệu xuất từ IPCAS.")

    df = pd.concat(dfs, ignore_index=True) if len(dfs) > 1 else dfs[0]

    df.columns = df.columns.str.strip()

    missing = sorted({'LOCAC', 'CUSTOMER', 'CCY', 'REMARK', 'DRAMOUNT', 'CRAMOUNT'} - set(df.columns))
    if missing:
        raise InputError(f"File .csv thiếu cột bắt buộc: {', '.join(missing)}.")

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


def _classify(
    df: pd.DataFrame,
    task_token: str | None = None,
    hub_di: pd.DataFrame | None = None,
    hub_den: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, ...]:
    """Phân loại thác nước: Hủy → Đi → 1000 Hoàn trả → Chuyển chi nhánh → Điện KO offline
    → Cân CN → Khác."""
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


def _read_hub_di(raw_bytes: bytes) -> pd.DataFrame:
    """Đọc file 'Quay_danh sach giao dich chuyen tien di' — tiêu đề ở dòng Excel thứ 2."""
    raw = pd.read_excel(io.BytesIO(raw_bytes), header=None, engine='calamine')
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


def _read_hub_den(raw_bytes: bytes) -> pd.DataFrame:
    """Đọc file 'Danh sach giao dich den' — tiêu đề ở dòng Excel thứ 3."""
    raw = pd.read_excel(io.BytesIO(raw_bytes), header=None, engine='calamine')
    df = raw.iloc[3:].copy()
    df.columns = raw.iloc[2].tolist()
    df = df.dropna(subset=['Số trace']).reset_index(drop=True)

    amt   = pd.to_numeric(df['Số tiền lệnh gốc'], errors='coerce').fillna(0.0).round(0)
    # Số trace: nếu có 2 dãy số (phân cách bởi ';') thì chỉ lấy dãy đầu tiên
    trace = pd.to_numeric(df['Số trace'].astype(str).str.split(';').str[0], errors='coerce')
    is_napas = df['Hệ thống thanh toán'].astype(str).str.strip() == 'ACH-NAPAS'
    # ACH-NAPAS: lấy 6 số cuối của "Số thành công/MSGID"
    override = df['Số thành công/MSGID'].astype(str).str.strip().str[-6:]
    link = df['Số REF HUB'].astype(str).str.strip()
    link = link.where(~is_napas, override)

    return pd.DataFrame({'AMOUNT': amt, 'TRACE': trace, 'LINK': link})


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
    den_ok = hub_den.loc[mask_den_1000ht, ['LINK', 'TRACE', 'AMOUNT']]

    ref_suffix = pd.to_numeric(df['REFERENCE'].str.slice(7), errors='coerce')
    dr = df['DRAMOUNT'].round(0)
    cr = df['CRAMOUNT'].round(0)
    tk = pd.DataFrame({'REF_SUFFIX': ref_suffix, 'DR': dr, 'CR': cr}, index=df.index).reset_index()

    dr_match = tk.merge(di_ok,  left_on=['REF_SUFFIX', 'DR'], right_on=['TRACE', 'AMOUNT'], how='inner')
    cr_match = tk.merge(den_ok, left_on=['REF_SUFFIX', 'CR'], right_on=['TRACE', 'AMOUNT'], how='inner')

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
    Nhóm không cân bằng tuyệt đối (VD REMARK trùng lặp giữa nhiều giao dịch khác nhau)
    bị loại bỏ hoàn toàn — không tách một phần — để rơi về GD khác chấm thủ công."""
    if len(df) == 0:
        return pd.Series(dtype=bool)
    amt = df[['DRAMOUNT', 'CRAMOUNT']].abs().max(axis=1).round(0)
    key = amt.astype('Int64').astype(str) + '|' + df['REMARK']

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
    """Điện KO offline (DK1-DK3): DK1 — tập ứng viên Có = USERID chứa 'KO'. DK2 — tập ứng
    viên Nợ = DRAMOUNT của các dòng có REMARK chứa marker 'Remitting Amount:VND'. DK3 — ghép
    cặp N:N theo SỐ TIỀN bằng nhau giữa 1 dòng Nợ (DK2) và 1 dòng Có (DK1), bắt buộc Nợ=Có
    từng cặp; dòng không tìm được đối tác cùng số tiền thì KHÔNG đánh dấu, rơi về GD khác
    (đánh dấu nghi ngờ) thay vì đoán.

    Trả về (mask_confirmed, mask_candidate)."""
    if len(df) == 0:
        return pd.Series(dtype=bool), pd.Series(dtype=bool)

    is_ko_user = df['USERID'].str.contains('KO', na=False)
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


def _write_excel(df: pd.DataFrame, path: Path, sheet_name: str, hex_color: str) -> None:
    """Ghi XLSX bằng direct XML — 8x nhanh hơn xlsxwriter, giữ đủ formatting."""
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

    # ── Rows XML ──────────────────────────────────────────────────────────────
    rows: list[str] = []

    # Dòng 1: summary (merge toàn bộ, style 1)
    rows.append(
        f'<row r="1">'
        f'<c r="A1" t="inlineStr" s="1"><is><t>{_xe(summary)}</t></is></c>'
        f'</row>'
    )

    # Dòng 2: tên cột (style 2)
    hdr = ''.join(
        f'<c r="{_COL_LETTERS[i]}2" t="inlineStr" s="2"><is><t>{col}</t></is></c>'
        for i, col in enumerate(OUTPUT_COLS)
    )
    rows.append(f'<row r="2">{hdr}</row>')

    # Dòng 3..N+2: data
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
        rows.append(f'<row r="{r_num}">{"".join(cells)}</row>')

    # Dòng N+3: tổng cộng
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
    rows.append(f'<row r="{sum_row}">{"".join(total)}</row>')

    # ── Sheet XML ─────────────────────────────────────────────────────────────
    cols_xml = '<cols>' + ''.join(
        f'<col min="{i+1}" max="{i+1}" width="{COL_WIDTHS.get(col, 12)}" customWidth="1"/>'
        for i, col in enumerate(OUTPUT_COLS)
    ) + '</cols>'

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="2" topLeftCell="A3" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        + cols_xml
        + '<sheetData>' + ''.join(rows) + '</sheetData>'
        # OOXML CT_Worksheet yêu cầu thứ tự cố định: autoFilter PHẢI đứng TRƯỚC mergeCells.
        # Ghi sai thứ tự khiến Excel coi sheet1.xml là "unreadable content" và gỡ bỏ sheet.
        + f'<autoFilter ref="A2:{last_col}{n_data + 2}"/>'
        + f'<mergeCells count="1"><mergeCell ref="A1:{last_col}1"/></mergeCells>'
        + '</worksheet>'
    )

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
        zf.writestr('xl/worksheets/sheet1.xml',     sheet_xml)


def _cleanup_old_results() -> None:
    """Xóa thư mục kết quả và progress entry cũ hơn CLEANUP_HOURS giờ."""
    cutoff = time.time() - CLEANUP_HOURS * 3600

    if TEMP_DIR.exists():
        for sub in TEMP_DIR.iterdir():
            if sub.is_dir() and sub.stat().st_mtime < cutoff:
                try:
                    shutil.rmtree(sub)
                except Exception as e:
                    log.warning("Không xóa được %s: %s", sub, e)

    # list(...) chụp nhanh trước khi duyệt — tránh RuntimeError nếu 1 request khác
    # gọi init_progress() làm thay đổi kích thước _progress cùng lúc (nhiều thread nền).
    stale = [k for k, v in list(_progress.items()) if v.get("_ts", 0) < cutoff]
    for k in stale:
        _progress.pop(k, None)
