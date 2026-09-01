"""Đọc file .XLS (BIFF cũ) cho module DTBB — dùng xlrd trực tiếp, tự chứa.

Không tái dùng backend/services/doi_soat_citad/parsers.py: các hàm/class ở đó
(`parse_citad_xls`, `_XlrdWs`, `_OpenpyxlWs`) gắn chặt logic nghiệp vụ CITAD
(tên private, thuộc module khác phụ trách), không phải bộ đọc XLS tổng quát.
"""
from __future__ import annotations

import re

import xlrd

_DATE_SUFFIX_RE = re.compile(r"(\d{8})\.XLS$", re.IGNORECASE)

# Chi nhánh mặc định khi tên file không mang mã chi nhánh ở đầu (vd "USD20260731.XLS")
# — quy ước nội bộ: "9999" = toàn hệ thống / Trụ sở chính.
DEFAULT_BRANCH_CODE = "9999"

# Tiêu đề chuẩn của file cân đối — đã verify khớp đúng cả 18 file thật (mọi loại
# tiền). File nào lệch tiêu đề (thiếu/thừa/đổi thứ tự cột) bị chặn ngay, không cố
# đọc liều — tránh tính sai âm thầm nếu gặp file xuất từ hệ thống/định dạng khác.
BALANCE_HEADER = ['ccy', 'Acctcd', 'acbldrcr', 'Acctnm', 'beforebal_dr', 'beforebal_cr',
                   'drcnt', 'dramt', 'crcnt', 'cramt', 'afterbal_dr', 'afterbal_cr', 'subunit']


class DtbbFileError(Exception):
    """Lỗi định dạng/nội dung file do người dùng upload — hiển thị thẳng cho FE.

    filenames: tên (các) file cụ thể gây lỗi, khi xác định được — FE dùng để tô đỏ
    đúng ô file trong danh sách đã chọn, không phải đoán mò/regex lại chuỗi message."""

    def __init__(self, message: str, filenames: list[str] | None = None):
        super().__init__(message)
        self.filenames = filenames or []


def extract_report_date_and_branch(filename: str, ccy: str) -> tuple[str, str]:
    """Trích (report_date, branch_code) từ tên file cân đối.

    Quy ước: <mã_chi_nhánh?><mã_tiền><YYYYMMDD>.XLS — mã tiền lấy từ NỘI DUNG file
    (cột `ccy`, đã đọc trước ở read_balance_file()), không đoán từ tên. Ví dụ
    '1200USD20260720.XLS' với ccy='USD' → bỏ '20260720.XLS', bỏ tiếp 'USD' ở cuối
    phần còn lại ('1200USD') → mã chi nhánh '1200'. Không còn dư ký tự nào (vd
    'USD20260731.XLS') → chi nhánh mặc định DEFAULT_BRANCH_CODE ('9999').

    Phần đứng trước mã tiền không khớp (hiếm — sai quy ước đặt tên) → báo lỗi rõ
    ràng thay vì đoán liều, tránh gán nhầm dữ liệu cho sai chi nhánh.
    """
    m = _DATE_SUFFIX_RE.search(filename or "")
    if not m:
        raise DtbbFileError(
            f"Không đọc được ngày từ tên file '{filename}' (cần dạng ...YYYYMMDD.XLS)",
            filenames=[filename],
        )
    d = m.group(1)
    report_date = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"

    prefix = filename[: m.start()]  # phần trước 8 số ngày, chưa gồm ".XLS"
    if not prefix.upper().endswith(ccy.upper()):
        raise DtbbFileError(
            f"Tên file '{filename}' không đúng quy ước <mã chi nhánh?><mã tiền><YYYYMMDD>.XLS "
            f"— phần trước ngày ('{prefix}') không kết thúc bằng mã tiền đọc được từ nội dung "
            f"file ('{ccy}').",
            filenames=[filename],
        )
    branch_code = prefix[: len(prefix) - len(ccy)].strip()
    return report_date, (branch_code or DEFAULT_BRANCH_CODE)


def _read_header(sh) -> list[str]:
    return [str(sh.cell_value(0, c)).strip() for c in range(sh.ncols)]


def _cell_to_code(v) -> str:
    """Chuẩn hoá ô mã tài khoản (Acctcd) về chuỗi. Nếu Excel lưu ô dạng số nguyên
    (xlrd trả về float, vd 401.0), str() trần sẽ ra '401.0' — không khớp danh mục
    tài khoản hardcode dạng chuỗi ('401') trong calculator.py, khiến dòng đó bị bỏ
    sót âm thầm khỏi mọi nhóm tính DTBB. Ép về '401' khi là số nguyên."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _cell_to_float(sh, row: int, col: int, *, filename: str, field: str) -> float:
    """Đọc 1 ô số, báo lỗi rõ ràng (file/dòng/cột) thay vì để ValueError lọt thành
    lỗi 500 thô khi ô chứa dữ liệu không parse được thành số (vd lỗi công thức Excel
    '#N/A', số dạng text lẫn dấu phân cách hàng nghìn)."""
    raw = sh.cell_value(row, col)
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        raise DtbbFileError(
            f"File '{filename}' có ô dữ liệu không phải số ở dòng {row + 1}, cột "
            f"'{field}': giá trị '{raw}'",
            filenames=[filename],
        )


def sniff_file_type(content: bytes, filename: str) -> str:
    """Nhận diện 'balance' (file cân đối) hay 'tygia' (file tỷ giá) theo cột đầu —
    không dựa vào tên file, để không bắt người dùng phải tự phân loại khi upload.
    Chỉ là bước định tuyến (kiểm tra lỏng); tiêu đề đầy đủ được validate nghiêm
    ngặt trong read_balance_file()/read_tygia_file() ngay sau đó."""
    try:
        wb = xlrd.open_workbook(file_contents=content)
        header = _read_header(wb.sheet_by_index(0))
    except Exception as e:
        raise DtbbFileError(
            f"File '{filename}' không đọc được (không phải .XLS hợp lệ): {e}", filenames=[filename]
        )
    if "ccyseq" in header:
        return "tygia"
    if "ccy" in header and "Acctcd" in header:
        return "balance"
    raise DtbbFileError(
        f"File '{filename}' không đúng định dạng file cân đối hay file tỷ giá DTBB",
        filenames=[filename],
    )


def read_balance_file(content: bytes, filename: str) -> tuple[str, dict[str, float]]:
    """Đọc 1 file cân đối tài khoản.

    Trả về (ccy, {Acctcd_đã_strip: afterbal_cr}) — bỏ dòng 'Tổng cộng' cuối (Acctcd rỗng).
    Báo lỗi ngay nếu tiêu đề cột không khớp CHÍNH XÁC chuẩn BALANCE_HEADER (đủ, đúng
    tên, đúng thứ tự) — không cố đọc liều khi tiêu đề không đồng nhất.
    """
    wb = xlrd.open_workbook(file_contents=content)
    sh = wb.sheet_by_index(0)
    header = _read_header(sh)
    if header != BALANCE_HEADER:
        raise DtbbFileError(
            f"File '{filename}' có tiêu đề cột không đúng chuẩn file cân đối DTBB.\n"
            f"Cần đúng: {', '.join(BALANCE_HEADER)}\n"
            f"Thực tế:  {', '.join(header)}",
            filenames=[filename],
        )
    col_ccy = BALANCE_HEADER.index("ccy")
    col_code = BALANCE_HEADER.index("Acctcd")
    col_cr = BALANCE_HEADER.index("afterbal_cr")

    rows: dict[str, float] = {}
    ccy = None
    for r in range(1, sh.nrows):
        code = _cell_to_code(sh.cell_value(r, col_code))
        if not code:
            continue
        c = sh.cell_value(r, col_ccy)
        if c:
            # .upper() — phòng file nguồn ghi mã tiền thường ('vnd'/'usd'), tránh so
            # sánh case-sensitive ở calculator.py (if ccy == 'VND') bỏ sót âm thầm.
            c_val = str(c).strip().upper()
            if ccy is not None and c_val != ccy:
                # File GLCB41/CĐ1000 chuẩn chỉ chứa 1 mã tiền — trộn 2 mã tiền trong
                # cùng 1 file là dấu hiệu file sai/ghép nhầm, không cố gộp chung.
                raise DtbbFileError(
                    f"File '{filename}' có nhiều mã tiền khác nhau trong cùng 1 file "
                    f"('{ccy}' và '{c_val}') — mỗi file chỉ được chứa đúng 1 mã tiền",
                    filenames=[filename],
                )
            ccy = c_val
        # Cộng dồn (không ghi đè) — export "Sub Branch, Including 1056" có thể tách
        # 1 tài khoản thành nhiều dòng theo subunit; số dư thật là tổng các dòng đó.
        rows[code] = rows.get(code, 0.0) + _cell_to_float(
            sh, r, col_cr, filename=filename, field="afterbal_cr"
        )
    if not ccy:
        raise DtbbFileError(
            f"File '{filename}' không xác định được mã tiền (cột ccy trống)", filenames=[filename]
        )
    return ccy, rows


# Tên cột tỷ giá đọc từ file: mua chuyển khoản, bình quân mua-bán, hạch toán/tính
# thuế (fallback khi 2 cột kia = 0 — xem calculator.py::calculate()).
RateInfo = dict  # {"ttbuyrt": float, "bsrt": float, "taxrt": float}


def read_tygia_file(content: bytes, filename: str) -> tuple[dict[str, "RateInfo"], str]:
    """Đọc file tỷ giá.

    Trả về ({ccycd: {"ttbuyrt", "bsrt", "taxrt"}}, report_date dạng 'YYYY-MM-DD' lấy
    từ cột rgstdt). Đọc cả 3 cột tỷ giá — công thức quy đổi chọn cột nào là việc của
    calculator.py, reader.py chỉ đọc dữ liệu thô.
    """
    wb = xlrd.open_workbook(file_contents=content)
    sh = wb.sheet_by_index(0)
    header = _read_header(sh)
    try:
        col_ccy = header.index("ccycd")
        col_buy = header.index("ttbuyrt")
        col_bsrt = header.index("bsrt")
        col_tax = header.index("taxrt")
        col_rgstdt = header.index("rgstdt")
    except ValueError as e:
        raise DtbbFileError(f"File tỷ giá '{filename}' thiếu cột bắt buộc: {e}", filenames=[filename])

    rates: dict[str, RateInfo] = {}
    rgstdt_serial = None
    for r in range(1, sh.nrows):
        ccy = str(sh.cell_value(r, col_ccy)).strip().upper()
        if not ccy:
            continue
        rates[ccy] = {
            "ttbuyrt": _cell_to_float(sh, r, col_buy, filename=filename, field="ttbuyrt"),
            "bsrt": _cell_to_float(sh, r, col_bsrt, filename=filename, field="bsrt"),
            "taxrt": _cell_to_float(sh, r, col_tax, filename=filename, field="taxrt"),
        }
        if rgstdt_serial is None:
            v = sh.cell_value(r, col_rgstdt)
            if v:
                rgstdt_serial = v
    if rgstdt_serial is None:
        raise DtbbFileError(
            f"File tỷ giá '{filename}' không có ngày đăng ký (cột rgstdt)", filenames=[filename]
        )
    try:
        y, mo, d, *_ = xlrd.xldate_as_tuple(rgstdt_serial, wb.datemode)
    except (TypeError, ValueError, xlrd.XLDateError):
        raise DtbbFileError(
            f"File tỷ giá '{filename}' có cột rgstdt không phải ngày Excel hợp lệ: "
            f"'{rgstdt_serial}'",
            filenames=[filename],
        )
    return rates, f"{y:04d}-{mo:02d}-{d:02d}"
