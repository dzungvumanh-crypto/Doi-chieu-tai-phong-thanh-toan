"""Service phân loại bút toán tài khoản 459901.

Logic phân loại (3 phase) port nguyên từ phan_loai_459901.py — KHÔNG THAY ĐỔI.
I/O làm việc với ĐƯỜNG DẪN file đã nằm trên máy chủ (`backend/api/cham459901.py`
ghi thẳng từng khối xuống `data/temp_cham459901/upload_<token>/`), không nhận bytes:
một lượt có thể là nhiều ZIP vài trăm MB, ôm hết vào RAM rồi mới đọc là trả giá
gấp đôi bộ nhớ cho cùng một kết quả. Chỉ file con BÊN TRONG ZIP mới đi qua bytes,
và cũng chỉ khi buộc phải thế (xem `_doc_zip`).
"""

import io
import logging
import shutil
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
    'DRAMOUNT', 'CRAMOUNT', 'CRTDTM',
]

COL_WIDTHS = {
    'TRDATE': 12, 'TRBRCD': 8, 'USERID': 13, 'JOURSEQ': 10, 'DYTRSEQ': 9,
    'LOCAC': 8, 'CCY': 5, 'BUSCD': 7, 'UNIT': 6, 'TRCD': 6, 'CUSTOMER': 18,
    'TRTP': 8, 'REFERENCE': 22, 'REMARK': 52, 'DRAMOUNT': 18, 'CRAMOUNT': 18,
    'CRTDTM': 20,
}

# Định dạng nhận được. ZIP là bản xuất gốc từ GL02 (bên trong là .csv, đôi khi là
# Excel); Excel rời dành cho người đã mở ZIP ra, cắt bớt rồi lưu lại.
DUOI_ZIP    = '.zip'
DUOI_EXCEL  = ('.xlsx', '.xlsm', '.xlsb', '.xls')
DUOI_HOP_LE = (DUOI_ZIP,) + DUOI_EXCEL

# Số dòng đầu mỗi sheet dùng để dò hàng tiêu đề (xem _dat_tieu_de)
_MAX_DONG_DO_TIEU_DE = 10

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

# ─── In-memory progress store ─────────────────────────────────────────────────
# key = task_token; value = {pct, msg, done, error, result, _ts}
_progress: dict[str, dict] = {}


def init_progress() -> str:
    """Khởi tạo entry theo dõi tiến độ, trả về task_token."""
    task_token = str(uuid.uuid4())
    _progress[task_token] = {
        "pct": 0, "msg": "Đang khởi tạo...",
        "done": False, "error": None, "result": None,
        "_ts": time.time(),
    }
    return task_token


def tao_thu_muc_upload(task_token: str) -> Path:
    """Thư mục nhận file tải lên của một lượt: `data/temp_cham459901/upload_<token>/`.

    Nằm cùng chỗ với thư mục kết quả nên `_cleanup_old_results()` trông coi luôn,
    không phải thêm đường dọn thứ hai. Tiền tố `upload_` để người vận hành mở ra
    là phân biệt được đâu là file người dùng gửi lên, đâu là 3 file Excel sinh ra.
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
    return {k: v for k, v in p.items() if not k.startswith("_")}


def _set_prog(task_token: str | None, pct: int, msg: str) -> None:
    if task_token and task_token in _progress:
        _progress[task_token]["pct"] = pct
        _progress[task_token]["msg"] = msg


# ─── Public API ───────────────────────────────────────────────────────────────

class InputError(ValueError):
    """Lỗi do chính file người dùng tải lên — thông báo hiển thị thẳng cho họ."""


def run_process(tep: list[tuple[str, Path]], task_token: str) -> None:
    """Chạy process_files trong background thread; cập nhật progress và bắt lỗi."""
    try:
        process_files(tep, task_token)
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


def process_files(tep: list[tuple[str, Path]], task_token: str | None = None) -> dict:
    """Nhận nhiều file ZIP/Excel [(tên hiển thị, đường dẫn)] → gộp → phân loại → lưu 3 xlsx.

    `tên hiển thị` là tên gốc người dùng chọn, chỉ dùng để viết thông báo lỗi;
    `đường dẫn` là file đã được ghi xuống máy chủ. Hai thứ tách nhau vì tên trên
    đĩa đã qua `safe_filename()` nên có thể khác tên người dùng nhìn thấy — báo
    lỗi bằng tên đã bị cắt là bắt họ đi tìm một file không tồn tại.

    Gộp TRƯỚC rồi mới phân loại, không chạy riêng từng file: cặp Cancel/Normal
    của một lệnh hủy có thể nằm ở hai file khác nhau (xuất theo ngày/theo chi
    nhánh). Chạy tách ra thì cả hai vế đều rơi vào "Lệnh Khác". Trộn ZIP với
    Excel trong cùng một lượt cũng vậy — nguồn nào không quan trọng, sau khi
    đọc lên đều là cùng một bảng.
    """
    if not tep:
        raise InputError("Chưa chọn file nào.")

    _cleanup_old_results()
    t0 = time.time()

    df, filtered_rows = _load_data(tep, task_token)
    total_before = len(df) + filtered_rows

    _set_prog(task_token, 30, "Bước 1 — Xác định lệnh hủy...")
    df_huy, df_di, df_khac = _classify(df, task_token)

    result_token = str(uuid.uuid4())
    out_dir = TEMP_DIR / result_token
    out_dir.mkdir(parents=True, exist_ok=True)

    _set_prog(task_token, 70, f"Xuất Excel — Lệnh Hủy ({len(df_huy):,} dòng)...")
    _write_excel(df_huy,  out_dir / "huy.xlsx",  "Lệnh Hủy",  "C0392B")

    _set_prog(task_token, 80, f"Xuất Excel — Lệnh Đi ({len(df_di):,} dòng)...")
    _write_excel(df_di,   out_dir / "di.xlsx",   "Lệnh Đi",   "27AE60")

    _set_prog(task_token, 92, f"Xuất Excel — Lệnh Khác ({len(df_khac):,} dòng)...")
    _write_excel(df_khac, out_dir / "khac.xlsx", "Lệnh Khác", "E67E22")

    result = {
        "token":         result_token,
        "huy_rows":      len(df_huy),
        "di_rows":       len(df_di),
        "khac_rows":     len(df_khac),
        "total_rows":    total_before,
        "filtered_rows": filtered_rows,
        "n_files":       len(tep),
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

def _kiem_cot(d: pd.DataFrame, nhan: str) -> None:
    """Kiểm cột NGAY TỪNG BẢNG, không đợi gộp xong.

    `pd.concat` lấy hợp các cột: bảng thiếu cột chỉ thành ô rỗng. Gộp rồi mới
    kiểm thì một file sai định dạng lọt qua và làm lệch kết quả phân loại.
    """
    missing = sorted(_COT_BAT_BUOC - set(d.columns))
    if missing:
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
    # phân loại đều cho NaN, mà NaN != NaN → dòng đó lặng lẽ rơi vào "Lệnh Khác".
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
    """Đọc 1 file người dùng tải lên → danh sách DataFrame, theo đuôi tên file.

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
    """Đọc tất cả file, gộp thành một DataFrame, lọc theo TK 459901."""
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


def _classify(
    df: pd.DataFrame,
    task_token: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Phân loại: Hủy (set giao) → Đi (groupby balance=0) → Khác (còn lại)."""
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

    assert len(df_huy) + len(df_di) + len(df_khac) == len(df), "Lỗi logic phân loại!"

    return df_huy, df_di, df_khac


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

    stale = [k for k, v in _progress.items() if v.get("_ts", 0) < cutoff]
    for k in stale:
        _progress.pop(k, None)
