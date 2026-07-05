# -*- coding: utf-8 -*-
"""
parsers.py
----------
Đọc dữ liệu từ 4 loại file nguồn (tất cả đều có đuôi .xls nhưng KHÔNG phải
file Excel nhị phân thật, mà là 2 dạng khác nhau):

1. File xuất từ SAA (Alliance Message Management) - cho cả điện đến & điện đi
   -> Thực chất là XML định dạng "SpreadsheetML" (Excel 2003 XML).

2. File xuất từ màn hình quản lý điện đến / điện đi
   -> Thực chất là 1 bảng HTML (<table>...</table>).

Mỗi hàm parse_* trả về một pandas.DataFrame:
   - Giữ NGUYÊN toàn bộ các cột gốc (để còn xuất lại nguyên trạng khi cần
     xem "chi tiết lệch").
   - Thêm các cột chuẩn hoá dùng để đối chiếu, bắt đầu bằng dấu gạch dưới:
       _key       : chuỗi dùng để so khớp giữa 2 hệ thống
       _msg_type  : loại điện đã chuẩn hoá (để gộp nhóm thống kê)
       _time      : datetime dùng để lọc theo khoảng thời gian
       _source    : tên nguồn dữ liệu (SAA_DEN, QL_DEN, QL_DI, SAA_DI)
       _direction : "DEN" hoặc "DI"
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from bs4 import BeautifulSoup

SS_NS = "urn:schemas-microsoft-com:office:spreadsheet"
NS = {"ss": SS_NS}


# --------------------------------------------------------------------------
# Phát hiện loại file
# --------------------------------------------------------------------------
class UnknownFileFormat(Exception):
    pass


def _looks_like_real_excel(path: str) -> bool:
    """True neu file la Excel nhi phan THAT (.xlsx dang zip/OOXML, hoac .xls
    dang OLE compound cu) - khac voi cac file .xls "gia" (thuc chat la
    XML/HTML) ma he thong SAA / man hinh quan ly xuat ra."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except Exception:
        return False
    return head.startswith(b"PK\x03\x04") or head.startswith(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1")


def _read_generic_excel_table(path: str) -> pd.DataFrame:
    """Doc 1 file Excel NHI PHAN THAT (vi du nguoi dung mo file .xls "gia"
    trong Excel roi Save As lai thanh .xlsx thuc su) - lay sheet dau tien,
    dong 1 la header, tra ve tat ca la string giong cac ham doc khac."""
    df = pd.read_excel(path, sheet_name=0, header=0)
    df = df.fillna("")
    df = df.astype(str)
    df.columns = [str(c).strip() for c in df.columns]
    # Bo cac dong hoan toan trong (openpyxl doi khi tra ve dong rong o cuoi)
    if len(df):
        df = df[~(df == "").all(axis=1)].reset_index(drop=True)
    return df


def _ensure_cols(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df


def sniff_file_kind(path: str) -> str:
    """Trả về 'saa_xml', 'ql_html', 'real_excel' hoặc 'unknown' dựa vào nội
    dung đầu file.

    File trong hệ thống thực tế có đuôi .xls nhưng không phải binary Excel,
    nên không thể dựa vào đuôi file mà phải đọc vài nghìn ký tự đầu để suy
    luận. Rieng 'real_excel' la truong hop nguoi dung tu Save As lai thanh
    file Excel nhi phan THAT (.xlsx/.xls) - nhan dien qua magic bytes dau
    file, khong phai qua noi dung text."""
    if _looks_like_real_excel(path):
        return "real_excel"
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(4000)
    except Exception:
        return "unknown"

    head_low = head.lower()
    if "urn:schemas-microsoft-com:office:spreadsheet" in head_low or (
        head_low.lstrip().startswith("<?xml") and "<workbook" in head_low
    ):
        return "saa_xml"
    if "<table" in head_low:
        return "ql_html"
    return "unknown"


# --------------------------------------------------------------------------
# Helper chung
# --------------------------------------------------------------------------
def _clean_str(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _last_chars(v, n: int) -> str:
    s = _clean_str(v)
    return s[-n:] if s else ""


def _parse_dt(s: str, fmt_list) -> Optional[datetime]:
    s = _clean_str(s)
    if not s:
        return None
    for fmt in fmt_list:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # Cố thử bỏ phần milliseconds / timezone dạng "+0700" nếu có
    m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", s)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    m = re.match(r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})", s)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y/%m/%d %H:%M:%S")
        except ValueError:
            pass
    return None


def normalize_msg_type(identifier: str) -> str:
    """Chuẩn hoá loại điện để 2 bên SAA / Quản lý so sánh được với nhau.

    - Bên SAA dùng "Identifier" dạng 'fin.950', 'fin.999', 'pacs.008.001.08',
      'camt.053.001.08' ...
    - Bên Quản lý dùng "Msg Type" dạng '950', '999', 'pacs.008.001.08' ...

    => Nếu Identifier có tiền tố 'fin.' thì bỏ tiền tố để ra đúng dạng số
       loại điện MT truyền thống (950, 999, ...). Các loại MX (pacs.*, camt.*,
       apc.*) giữ nguyên vì 2 bên đã đồng nhất."""
    s = _clean_str(identifier)
    if not s:
        return ""
    if s.lower().startswith("fin."):
        return s[4:]
    return s


# --------------------------------------------------------------------------
# Đọc file SAA (SpreadsheetML XML) - dùng chung cho điện đến & điện đi
# --------------------------------------------------------------------------
def _read_saa_rows(path: str):
    """Đọc toàn bộ Row/Cell của sheet 'Report' trong file SAA, trả về:
    header (dict tên cột -> index cột) và list các dict {index: value}
    cho từng dòng dữ liệu thật (đã loại bỏ phần Report Header / Report
    Footer / dòng trống)."""
    tree = ET.parse(path)
    root = tree.getroot()
    ws = root.find("ss:Worksheet", NS)
    if ws is None:
        raise UnknownFileFormat(f"Không tìm thấy Worksheet trong file: {path}")
    table = ws.find("ss:Table", NS)
    if table is None:
        raise UnknownFileFormat(f"Không tìm thấy Table trong file: {path}")

    all_rows = []
    for row_el in table.findall("ss:Row", NS):
        row = {}
        next_index = 1
        for cell_el in row_el.findall("ss:Cell", NS):
            idx_attr = cell_el.attrib.get(f"{{{SS_NS}}}Index")
            idx = int(idx_attr) if idx_attr else next_index
            data_el = cell_el.find("ss:Data", NS)
            value = data_el.text if data_el is not None else ""
            row[idx] = value if value is not None else ""
            merge = cell_el.attrib.get(f"{{{SS_NS}}}MergeAcross")
            span = int(merge) + 1 if merge else 1
            next_index = idx + span
        all_rows.append(row)

    # Tìm dòng header thật (chứa "Correspondent" ở cột 1)
    header_idx = None
    for i, row in enumerate(all_rows):
        if _clean_str(row.get(1)) == "Correspondent":
            header_idx = i
            break
    if header_idx is None:
        raise UnknownFileFormat(
            f"Không tìm thấy dòng tiêu đề 'Correspondent' trong file SAA: {path}"
        )

    header_row = all_rows[header_idx]
    col_names = {idx: _clean_str(val) for idx, val in header_row.items() if _clean_str(val)}

    data_rows = []
    for row in all_rows[header_idx + 1:]:
        first_cell = _clean_str(row.get(1))
        if first_cell in ("Report Footer", "End of report", "Number of Entities:"):
            break
        # Bỏ dòng hoàn toàn trống
        if not any(_clean_str(v) for v in row.values()):
            continue
        data_rows.append(row)

    return col_names, data_rows


def _saa_rows_to_df(col_names: dict, data_rows: list) -> pd.DataFrame:
    records = []
    for row in data_rows:
        rec = {}
        for idx, name in col_names.items():
            rec[name] = _clean_str(row.get(idx, ""))
        records.append(rec)
    df = pd.DataFrame.from_records(records)
    # Đảm bảo các cột mong đợi luôn tồn tại dù file có thiếu cột nào đó
    for must in ["Correspondent", "Identifier", "Reference", "MUR",
                 "I/O", "Reception Info", "Mesg Creation"]:
        if must not in df.columns:
            df[must] = ""
    return df


SAA_DT_FORMATS = ["%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"]


def parse_saa_den(path: str) -> pd.DataFrame:
    """Parse file SAA của ĐIỆN ĐẾN (cột khoá: Reception Info, lấy 6 ký tự
    cuối; lọc I/O = 'O' = Output = điện hệ thống nhận về)."""
    if _looks_like_real_excel(path):
        df = _read_generic_excel_table(path)
    else:
        col_names, data_rows = _read_saa_rows(path)
        df = _saa_rows_to_df(col_names, data_rows)
    df = _ensure_cols(df, ["Correspondent", "Identifier", "Reference", "MUR",
                            "I/O", "Reception Info", "Mesg Creation"])

    # Lọc an toàn: chỉ giữ các dòng I/O = O (điện đến) nếu cột tồn tại có dữ liệu
    if "I/O" in df.columns and df["I/O"].astype(str).str.strip().isin(["I", "O"]).any():
        df = df[df["I/O"].astype(str).str.strip().str.upper() != "I"].copy()

    df["_key"] = df["Reception Info"].apply(lambda v: _last_chars(v, 6))
    df["_msg_type"] = df["Identifier"].apply(normalize_msg_type)
    df["_time"] = df["Mesg Creation"].apply(lambda v: _parse_dt(v, SAA_DT_FORMATS))
    df["_source"] = "SAA_DEN"
    df["_direction"] = "DEN"
    # Bỏ các dòng không có khoá (không phải bản ghi điện thật, ví dụ dòng tiêu đề lặp)
    df = df[df["_key"] != ""].reset_index(drop=True)
    return df


def parse_saa_di(path: str) -> pd.DataFrame:
    """Parse file SAA của ĐIỆN ĐI (cột khoá: 16 ký tự cuối của MUR; lọc
    I/O = 'I' = Input = điện gửi đi)."""
    if _looks_like_real_excel(path):
        df = _read_generic_excel_table(path)
    else:
        col_names, data_rows = _read_saa_rows(path)
        df = _saa_rows_to_df(col_names, data_rows)
    df = _ensure_cols(df, ["Correspondent", "Identifier", "Reference", "MUR",
                            "I/O", "Reception Info", "Mesg Creation"])

    if "I/O" in df.columns and df["I/O"].astype(str).str.strip().isin(["I", "O"]).any():
        df = df[df["I/O"].astype(str).str.strip().str.upper() != "O"].copy()

    df["_key"] = df["MUR"].apply(lambda v: _last_chars(v, 16))
    df["_msg_type"] = df["Identifier"].apply(normalize_msg_type)
    df["_time"] = df["Mesg Creation"].apply(lambda v: _parse_dt(v, SAA_DT_FORMATS))
    df["_source"] = "SAA_DI"
    df["_direction"] = "DI"
    df = df[df["_key"] != ""].reset_index(drop=True)
    return df


# --------------------------------------------------------------------------
# Đọc file Quản lý điện (HTML table) - QL điện đến & QL điện đi
# --------------------------------------------------------------------------
def _table_from_html(content: str) -> Optional[pd.DataFrame]:
    """Tim <table> dau tien trong 1 doan HTML va tra ve DataFrame, hoac None
    neu khong tim thay <table> / khong tim thay dong tieu de (KHONG raise,
    de ham goi ben ngoai con thu cach khac truoc khi bao loi)."""
    soup = BeautifulSoup(content, "html.parser")
    table = soup.find("table")
    if table is None:
        return None

    header_tr = table.find("tr")
    if header_tr is None:
        return None
    headers = [th.get_text(strip=True) for th in header_tr.find_all(["th", "td"])]

    # tfoot (dòng Total:.../ACK:.../NAK:...) phải loại trừ, không phải dữ liệu
    tfoot = table.find("tfoot")
    footer_trs = set()
    if tfoot is not None:
        footer_trs = {id(tr) for tr in tfoot.find_all("tr")}

    rows = []
    for tr in table.find_all("tr"):
        if id(tr) in footer_trs:
            continue
        if tr is header_tr:
            continue
        if tr.find("th") is not None:
            continue
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not cells:
            continue
        # Dòng tổng kết kiểu "Total:516" lọt ra ngoài tfoot (phòng hờ) -> loại bỏ
        if cells[0].lower().startswith("total"):
            continue
        rows.append(cells)

    n = len(headers)
    fixed_rows = []
    for r in rows:
        if len(r) < n:
            r = r + [""] * (n - len(r))
        elif len(r) > n:
            r = r[:n]
        fixed_rows.append(r)

    return pd.DataFrame(fixed_rows, columns=headers)


def _read_ql_table(path: str) -> pd.DataFrame:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    df = _table_from_html(content)
    if df is not None:
        return df

    # Fallback: file nay la kieu export "Web Page, Complete" cua Excel/IE -
    # ban than file chi la 1 "khung" (frameset) dan link toi 1 file .htm KHAC
    # moi chua bang du lieu thuc su, thuong nam trong 1 thu muc con ten
    # "<ten file>_files" duoc tao TU DONG canh file goc khi xuat ra kieu nay.
    # Neu thu muc con do co san CANH file dang doc (path), tu dong doc theo.
    import os
    from urllib.parse import unquote

    soup = BeautifulSoup(content, "html.parser")
    base_dir = os.path.dirname(os.path.abspath(path))
    candidate_hrefs = []
    for tag_name, attr in [("frame", "src"), ("iframe", "src"), ("link", "href")]:
        for tag in soup.find_all(tag_name):
            href = tag.get(attr)
            if href:
                candidate_hrefs.append(href)
    for m in re.finditer(r'HRef="([^"]+)"', content):
        candidate_hrefs.append(m.group(1))

    tried_paths = []
    for href in candidate_hrefs:
        candidate_path = os.path.normpath(os.path.join(base_dir, unquote(href)))
        if candidate_path in tried_paths:
            continue
        tried_paths.append(candidate_path)
        if os.path.isfile(candidate_path):
            try:
                with open(candidate_path, "r", encoding="utf-8", errors="ignore") as f:
                    sub_df = _table_from_html(f.read())
            except Exception:
                continue
            if sub_df is not None and len(sub_df) > 0:
                return sub_df

    raise UnknownFileFormat(
        f"Không tìm thấy <table> trong file: {path}\n"
        "File này có dạng 'Web Page, Complete' (chỉ là khung dẫn tới 1 file .htm khác "
        "chứa dữ liệu thật, thường nằm trong 1 thư mục con '<tên file>_files' đi kèm "
        "cạnh file .xls khi xuất ra) - thư mục con đó không có sẵn cạnh file đang đọc.\n"
        "Cách xử lý: nén (zip) CẢ file .xls này VÀ thư mục '..._files' đi kèm cạnh nó lại, "
        "rồi tải file .zip đó lên."
    )


QL_DT_FORMATS = ["%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"]


def _parse_ql_dt(s: str):
    s = _clean_str(s)
    if not s or s.lower() == "null":
        return None
    # Bỏ phần offset dạng +0700 ở cuối nếu strptime không xử lý được %z đúng ý
    s2 = re.sub(r"([+-]\d{4})$", "", s).strip()
    return _parse_dt(s2, ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"])


def parse_ql_den(path: str) -> pd.DataFrame:
    """Parse file màn hình quản lý ĐIỆN ĐẾN (cột khoá: SaSeq, lấy 6 ký tự cuối)."""
    if _looks_like_real_excel(path):
        df = _read_generic_excel_table(path)
    else:
        df = _read_ql_table(path)
    df = _ensure_cols(df, ["Msg Key", "Msg Type", "Brcd", "SaSeq", "Create Date"])

    df["_key"] = df["SaSeq"].apply(lambda v: _last_chars(v, 6))
    df["_msg_type"] = df["Msg Type"].apply(_clean_str)
    df["_time"] = df["Create Date"].apply(_parse_ql_dt)
    df["_source"] = "QL_DEN"
    df["_direction"] = "DEN"
    df = df[df["_key"] != ""].reset_index(drop=True)
    return df


def parse_ql_di(path: str) -> pd.DataFrame:
    """Parse file màn hình quản lý ĐIỆN ĐI (cột khoá: Brcd(4) + Msg Key(12))."""
    if _looks_like_real_excel(path):
        df = _read_generic_excel_table(path)
    else:
        df = _read_ql_table(path)
    df = _ensure_cols(df, ["Msg Key", "Msg Type", "Brcd", "Create Date"])

    def make_key(row):
        brcd = _clean_str(row["Brcd"])[:4].zfill(4) if _clean_str(row["Brcd"]) else ""
        msgkey = _last_chars(row["Msg Key"], 12)
        if not brcd or not msgkey:
            return ""
        return brcd + msgkey

    df["_key"] = df.apply(make_key, axis=1)
    df["_msg_type"] = df["Msg Type"].apply(_clean_str)
    df["_time"] = df["Create Date"].apply(_parse_ql_dt)
    df["_source"] = "QL_DI"
    df["_direction"] = "DI"
    df = df[df["_key"] != ""].reset_index(drop=True)
    return df


# --------------------------------------------------------------------------
# Hàm tiện ích cấp cao: tự nhận diện + parse đúng hàm theo (loại nguồn, chiều)
# --------------------------------------------------------------------------
def load_file(path: str, source: str) -> pd.DataFrame:
    """source thuộc {'SAA_DEN', 'QL_DEN', 'QL_DI', 'SAA_DI'}"""
    kind = sniff_file_kind(path)
    # 'real_excel' = nguoi dung da tu Save As lai thanh file Excel nhi phan
    # THAT (khong con la XML/HTML gia dang .xls nua) - hop le cho ca 2 phia,
    # vi luc nay chi con phu thuoc dung cot du lieu, khong phu thuoc dinh
    # dang xuat file nua.
    if kind == "real_excel":
        pass
    elif source in ("SAA_DEN", "SAA_DI") and kind != "saa_xml":
        raise UnknownFileFormat(
            f"File '{Path(path).name}' không đúng định dạng xuất từ SAA "
            f"(không phải SpreadsheetML XML)."
        )
    elif source in ("QL_DEN", "QL_DI") and kind != "ql_html":
        raise UnknownFileFormat(
            f"File '{Path(path).name}' không đúng định dạng xuất từ màn hình "
            f"quản lý điện (không phải bảng HTML)."
        )

    if source == "SAA_DEN":
        return parse_saa_den(path)
    if source == "SAA_DI":
        return parse_saa_di(path)
    if source == "QL_DEN":
        return parse_ql_den(path)
    if source == "QL_DI":
        return parse_ql_di(path)
    raise ValueError(f"source không hợp lệ: {source}")
