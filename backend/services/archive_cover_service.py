"""
Bìa hồ sơ lưu trữ (mẫu M01/LHS) — đọc Excel tra cứu hồ sơ, điền vào template Word.

Template: templates/Phòng KSNB&HTVH/Bàn giao cho lưu trữ/Bia_ho_so.docx
Toàn bộ nội dung bìa nằm trong VML textbox (w:pict → v:textbox → w:txbxContent),
nên python-docx không thấy paragraph nào ở body — phải duyệt bằng lxml.

Chỉ thay text của các w:t đã xác định; mọi rPr/pPr (font, cỡ chữ, căn lề) giữ nguyên.
"""
import copy
import io
import os
import re
from dataclasses import dataclass
from typing import List

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from backend.core.paths import template_path

# template_path() chứ không phải os.path.join(): thư mục có dấu trên đĩa đang ở
# dạng NFD, ghép chuỗi NFC từ mã nguồn sẽ không khớp — xem backend/core/paths.py
TEMPLATE_PATH = template_path("Phòng KSNB&HTVH", "Bàn giao cho lưu trữ", "Bia_ho_so.docx")

# Nhãn dùng làm mốc định vị trong template — đổi template thì phải đổi ở đây
_LBL_KY_HIEU = "Ký hiệu thông tin"
_LBL_NGAY_MO = "Ngày mở"
_LBL_NGAY_CVKT = "Ngày công việc kết thúc"
_LBL_NGAY_BD = "Ngày bắt đầu"
_LBL_GOM = "Gồm:"
_BARCODE_FONT = "3 of 9 Barcode"

_RX_DATE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")

# Sheet "Data" của file tra cứu (LT_HS_TRACUU_*.xls). Dòng tiêu đề nằm ở dòng 2
# (dòng 1 là tên báo cáo), nhưng dò theo nội dung thay vì cố định số dòng: lệch
# một dòng thì mất đúng một hồ sơ mà không có gì báo.
_SHEET_NAME = "Data"
_HEADER_SCAN_ROWS = 10

# Tên cột cần dùng → thuộc tính của ArchiveCoverRecord
_HDR_TEN_HS = "Tên hồ sơ/ĐVBQ"
_HDR_NGAY_CVKT = "Ngày CVKT"
_HDR_SO_TO = "Số tờ"
_HDR_MA_VACH = "Mã vạch"
_HDR_BAT_BUOC = (_HDR_TEN_HS, _HDR_NGAY_CVKT, _HDR_SO_TO, _HDR_MA_VACH)


class TemplateMismatchError(Exception):
    """Template Word không còn cấu trúc mong đợi — không thể điền dữ liệu."""


@dataclass
class ArchiveCoverRecord:
    ma_vach: str
    ngay_mo: str
    tieu_de: str
    ngay_cvkt: str
    so_to: str = "1"


# ─── Đọc Excel ────────────────────────────────────────────────────────────────

def _txt(v) -> str:
    import pandas as pd
    return "" if v is None or pd.isna(v) else str(v).strip()


def _find_header(df) -> tuple:
    """Trả về (chỉ số dòng tiêu đề, {tên cột: chỉ số cột})."""
    for i in range(min(_HEADER_SCAN_ROWS, len(df))):
        cells = {_txt(v): j for j, v in enumerate(df.iloc[i].tolist())}
        if all(h in cells for h in _HDR_BAT_BUOC):
            return i, cells
    raise ValueError(
        "Không tìm thấy dòng tiêu đề trong sheet 'Data' — cần đủ các cột: "
        + ", ".join(f"'{h}'" for h in _HDR_BAT_BUOC)
    )


def parse_lookup_excel(content: bytes, filename: str = "") -> List[ArchiveCoverRecord]:
    """Đọc file tra cứu hồ sơ (.xls/.xlsx) → danh sách bản ghi bìa."""
    import pandas as pd

    engine = "xlrd" if filename.lower().endswith(".xls") else "openpyxl"
    try:
        df = pd.read_excel(io.BytesIO(content), sheet_name=_SHEET_NAME,
                           header=None, dtype=str, engine=engine)
    except ValueError as e:
        raise ValueError(f"File Excel không có sheet '{_SHEET_NAME}'") from e

    hdr_row, cols = _find_header(df)
    c_ten, c_cvkt = cols[_HDR_TEN_HS], cols[_HDR_NGAY_CVKT]
    c_so_to, c_ma = cols[_HDR_SO_TO], cols[_HDR_MA_VACH]

    records: List[ArchiveCoverRecord] = []
    for _, raw in df.iloc[hdr_row + 1:].iterrows():
        row = raw.tolist()
        ma_vach = _txt(row[c_ma])
        tieu_de = _txt(row[c_ten])
        if not ma_vach and not tieu_de:
            continue

        m = _RX_DATE.search(tieu_de)
        records.append(ArchiveCoverRecord(
            ma_vach=ma_vach,
            ngay_mo=m.group(1) if m else "",
            tieu_de=tieu_de,
            ngay_cvkt=_txt(row[c_cvkt]),
            so_to=_txt(row[c_so_to]) or "1",
        ))
    return records


# ─── Thao tác trên XML của template ───────────────────────────────────────────

def _texts(el) -> List:
    return list(el.iter(qn("w:t")))


def _para_text(p) -> str:
    return "".join(t.text or "" for t in _texts(p))


def _set_text(node, value: str) -> None:
    node.text = value
    node.set(qn("xml:space"), "preserve")


def _set_last(p, value: str, what: str) -> None:
    ts = _texts(p)
    if not ts:
        raise TemplateMismatchError(f"Không tìm thấy ô text để điền '{what}' trong template")
    _set_text(ts[-1], value)


def _set_first_clear_rest(p, value: str, what: str) -> None:
    ts = _texts(p)
    if not ts:
        raise TemplateMismatchError(f"Không tìm thấy ô text để điền '{what}' trong template")
    _set_text(ts[0], value)
    for t in ts[1:]:
        _set_text(t, "")


def _paragraphs(block) -> List:
    """Paragraph lá — w:p không chứa w:p con.

    Nội dung bìa nằm trong textbox, nên w:p ngoài cùng bọc cả tài liệu; nếu lấy cả
    paragraph bọc thì _para_text() trả về toàn bộ text của trang và mọi phép điền
    sẽ nhắm sai chỗ.
    """
    return [p for p in block.iter(qn("w:p")) if len(list(p.iter(qn("w:p")))) == 1]


def _fill_barcode(block, code: str) -> None:
    for r in block.iter(qn("w:r")):
        rpr = r.find(qn("w:rPr"))
        if rpr is None:
            continue
        fonts = rpr.find(qn("w:rFonts"))
        if fonts is not None and fonts.get(qn("w:ascii")) == _BARCODE_FONT:
            ts = _texts(r)
            if ts:
                _set_text(ts[0], f"*{code}*")
                return
    raise TemplateMismatchError(f"Không tìm thấy run dùng font '{_BARCODE_FONT}' trong template")


def _fill_ngay_cvkt(block, value: str) -> None:
    """Ngày CVKT nằm ở ô cùng cột, dòng ngay dưới ô nhãn 'Ngày công việc kết thúc'."""
    for tbl in block.iter(qn("w:tbl")):
        rows = tbl.findall(qn("w:tr"))
        for ri, tr in enumerate(rows):
            cells = tr.findall(qn("w:tc"))
            for ci, tc in enumerate(cells):
                if _LBL_NGAY_CVKT not in "".join(_para_text(p) for p in _paragraphs(tc)):
                    continue
                if ri + 1 >= len(rows):
                    raise TemplateMismatchError(
                        f"Template thiếu dòng giá trị dưới nhãn '{_LBL_NGAY_CVKT}'")
                below = rows[ri + 1].findall(qn("w:tc"))
                if ci >= len(below):
                    raise TemplateMismatchError(
                        f"Template thiếu ô giá trị dưới nhãn '{_LBL_NGAY_CVKT}'")
                ts = _texts(below[ci])
                if not ts:
                    raise TemplateMismatchError(
                        f"Ô giá trị '{_LBL_NGAY_CVKT}' trong template không có sẵn text")
                _set_text(ts[-1], value)
                for t in ts[:-1]:
                    _set_text(t, "")
                return
    raise TemplateMismatchError(f"Không tìm thấy nhãn '{_LBL_NGAY_CVKT}' trong template")


def _fill_so_to(p, value: str) -> None:
    for t in _texts(p):
        if (t.text or "").strip().isdigit():
            _set_text(t, value)
            return
    raise TemplateMismatchError(f"Không tìm thấy số tờ trong dòng '{_LBL_GOM}'")


def _fill_block(block, rec: ArchiveCoverRecord) -> None:
    paras = _paragraphs(block)
    texts = [_para_text(p) for p in paras]

    done = {"ky_hieu": False, "ngay_mo": False, "tieu_de": False, "so_to": False}

    for i, (p, txt) in enumerate(zip(paras, texts)):
        stripped = txt.strip()

        if not done["ky_hieu"] and _LBL_KY_HIEU in txt:
            _set_last(p, rec.ma_vach, _LBL_KY_HIEU)
            done["ky_hieu"] = True
            continue

        if not done["ngay_mo"] and stripped.startswith(_LBL_NGAY_MO):
            _set_last(p, rec.ngay_mo, _LBL_NGAY_MO)
            done["ngay_mo"] = True
            continue

        if not done["so_to"] and stripped.startswith(_LBL_GOM):
            _fill_so_to(p, rec.so_to)
            done["so_to"] = True
            continue

        # Tiêu đề = paragraph có nội dung đứng ngay trước dòng "Ngày bắt đầu"
        if not done["tieu_de"] and stripped:
            nxt = next((t.strip() for t in texts[i + 1:] if t.strip()), "")
            if nxt.startswith(_LBL_NGAY_BD):
                _set_first_clear_rest(p, rec.tieu_de, "tiêu đề hồ sơ")
                done["tieu_de"] = True

    missing = [k for k, v in done.items() if not v]
    if missing:
        raise TemplateMismatchError(
            "Template không còn đúng cấu trúc, thiếu vị trí điền: " + ", ".join(missing))

    _fill_barcode(block, rec.ma_vach)
    _fill_ngay_cvkt(block, rec.ngay_cvkt)


# ─── Sinh file Word ───────────────────────────────────────────────────────────

def _page_break_before(p) -> None:
    pPr = p.find(qn("w:pPr"))
    if pPr is None:
        pPr = OxmlElement("w:pPr")
        p.insert(0, pPr)
    if pPr.find(qn("w:pageBreakBefore")) is None:
        pPr.insert(0, OxmlElement("w:pageBreakBefore"))


def _load_template():
    if not os.path.exists(TEMPLATE_PATH):
        raise FileNotFoundError(f"Không tìm thấy template bìa hồ sơ: {TEMPLATE_PATH}")
    return Document(TEMPLATE_PATH)


def _template_block(body) -> List:
    """Mọi phần tử body trừ sectPr — một trang bìa hoàn chỉnh."""
    return [copy.deepcopy(ch) for ch in body if ch.tag != qn("w:sectPr")]


def generate_covers(records: List[ArchiveCoverRecord]) -> bytes:
    """Một file Word, mỗi hồ sơ một trang."""
    if not records:
        raise ValueError("Không có hồ sơ nào để in bìa")

    doc = _load_template()
    body = doc.element.body
    block = _template_block(body)

    sect = body.find(qn("w:sectPr"))
    for ch in list(body):
        if ch.tag != qn("w:sectPr"):
            body.remove(ch)

    for i, rec in enumerate(records):
        page = [copy.deepcopy(el) for el in block]
        holder = OxmlElement("w:body")          # bọc tạm để duyệt cả trang một lần
        for el in page:
            holder.append(el)
        _fill_block(holder, rec)

        page = list(holder)
        if i > 0 and page and page[0].tag == qn("w:p"):
            _page_break_before(page[0])
        for el in page:
            if sect is not None:
                sect.addprevious(el)
            else:
                body.append(el)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def generate_cover_single(rec: ArchiveCoverRecord) -> bytes:
    doc = _load_template()
    _fill_block(doc.element.body, rec)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _safe_name(s: str, fallback: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n]+', "_", (s or "").strip())
    return s[:80] or fallback


def generate_covers_zip(records: List[ArchiveCoverRecord]) -> bytes:
    """ZIP, mỗi hồ sơ một file .docx đặt tên theo mã vạch."""
    import zipfile

    if not records:
        raise ValueError("Không có hồ sơ nào để in bìa")

    buf = io.BytesIO()
    used: set = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, rec in enumerate(records, 1):
            name = _safe_name(rec.ma_vach, f"bia_{i}")
            if name in used:
                name = f"{name}_{i}"
            used.add(name)
            zf.writestr(f"{name}.docx", generate_cover_single(rec))
    return buf.getvalue()
