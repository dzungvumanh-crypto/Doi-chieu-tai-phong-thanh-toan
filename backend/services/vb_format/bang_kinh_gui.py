"""Khối "Kính gửi / Kính trình" dựng bằng bảng hai cột — tính lại bề ngang cột.

## Vì sao người soạn dùng bảng, và vì sao giữ bảng

Điều 15.4.a: gửi một nơi thì "Kính gửi:" và tên nơi nhận nằm trên CÙNG một
dòng; gửi nhiều nơi thì mỗi nơi một dòng, gạch đầu dòng thẳng hàng dưới dấu
hai chấm. Tên nơi nhận dài xuống dòng thì dòng thứ hai phải thụt vào ngang chữ
đầu tên — gõ bằng dấu cách không làm được, nên người soạn kẻ một bảng hai cột
không viền: ô trái "Kính trình:", ô phải tên nơi nhận. Cách đó đúng ý quy định;
gộp về một đoạn là mất chỗ thụt ấy. Giữ bảng, chỉ sửa kích thước.

## Vì sao phải tính lại bề ngang

Bề ngang cột được người soạn kéo cho vừa cỡ chữ CŨ. Chuẩn hoá nâng cỡ chữ lên
14 thì chữ tràn ô: gặp thật (VB goc 23/09/2026, bản gốc cỡ 8) — "Kính / trình:"
gãy làm hai dòng trong ô 70,8 pt, tên người nhận gãy "…Vương Hồng / Lĩnh.",
nhìn như văn bản hỏng.

## Cách tính

* Lề trong ô về 0 — bề ngang cột bằng đúng bề ngang chữ, không phải cộng trừ
  lề mặc định 108 dxa mỗi bên của từng máy.
* Cột trái: gửi MỘT nơi = "Kính trình:" + một dấu cách (đọc liền như gõ tay);
  gửi NHIỀU nơi = "Kính gửi:" sát dấu hai chấm (+1 pt dư) — gạch đầu dòng ở
  cột phải bắt đầu ngay sau dấu hai chấm, lệch ~4 pt so với "dưới dấu hai
  chấm" của Điều 15.4.a. Bản đầu cắt bớt dấu ":" cho gạch nằm đúng dưới nó,
  phản biện dựng PDF bằng Word: "Kính / gửi:" gãy hai dòng — đúng lỗi đang sửa.
  Trong một ô bảng chữ không tràn sang ô bên được, nên 4 pt là giá phải trả.
* Cột phải: dòng dài nhất + dư một chút (Word và Pillow dàn chữ lệch nhau vài
  phần nghìn — thiếu 1 pt là Word đẩy chữ cuối xuống dòng). Không vượt bề ngang
  vùng chữ; dài hơn thì để Word xuống dòng TRONG ô phải — chính việc bảng làm tốt.
* Cả bảng canh giữa trang: Mẫu 06 canh giữa dòng "Kính gửi …".
* Bỏ viền: không mẫu nào của Phụ lục V có khung quanh Kính gửi.

Đo không được (máy thiếu phông) thì không đụng bảng — đoán bề ngang sai là tự
tay làm gãy dòng.
"""
import logging
import re

from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from lxml import etree

from . import do_chu

_log = logging.getLogger(__name__)

_RE_O_DAU = re.compile(r"^\s*(Kính\s+(?:gửi|trình))\s*:\s*$", re.I)
_DU_PT = 2.0                # dư cho cột phải: chênh dàn chữ Word / Pillow
_DU_TY_LE = 0.02
_DU_TRAI_PT = 1.0           # dư cho cột trái ca nhiều nơi (không có dấu cách đệm)


def _kieu_chu(p, hieu_luc_run) -> tuple[float, bool, bool] | None:
    r = next((r for r in p.runs if r.text.strip()), None)
    if r is None:
        return None
    co = hieu_luc_run(r, p, "size")
    if co is None:
        return None
    return co.pt, bool(hieu_luc_run(r, p, "bold")), bool(hieu_luc_run(r, p, "italic"))


def _rong(p, chu: str, hieu_luc_run) -> float | None:
    kieu = _kieu_chu(p, hieu_luc_run)
    if kieu is None:
        return None
    return do_chu.be_rong_pt(chu, *kieu)


def _dat_the(cha, ten: str, xml: str, truoc: tuple[str, ...] = ()) -> None:
    """Thay (hoặc thêm) thẻ con `ten` của `cha`, giữ đúng thứ tự lược đồ."""
    cu = cha.find(qn(ten))
    moi = parse_xml(xml)
    if cu is not None:
        cha.replace(cu, moi)
        return
    moc = next((cha.find(qn(t)) for t in truoc if cha.find(qn(t)) is not None), None)
    if moc is not None:
        moc.addprevious(moi)
    else:
        cha.append(moi)


# Thứ tự thẻ trong w:tblPr theo lược đồ — thẻ chèn sau phải đứng TRƯỚC các thẻ này.
_SAU_TBLW = ("w:jc", "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd",
             "w:tblLayout", "w:tblCellMar", "w:tblLook")
_SAU_JC = _SAU_TBLW[1:]
_SAU_BORDERS = ("w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook")
_SAU_LAYOUT = ("w:tblCellMar", "w:tblLook")


def _bang_cua(p):
    el = p._p.getparent()
    while el is not None and el.tag != qn("w:tbl"):
        el = el.getparent()
    return el


def chuan_bang_kinh_gui(khoi, ma_list: list[str], rong_vung_chu_pt: float,
                        hieu_luc_run) -> int:
    """Tính lại bề ngang bảng Kính gửi / Kính trình. Trả số bảng đã sửa.

    Chỉ nhận bảng đúng dạng: mọi hàng có đúng HAI ô, ô trái của hàng đầu chỉ
    chứa "Kính gửi:" / "Kính trình:". Bảng khác dạng (ô gộp, ba cột, "Kính gửi:
    X" chung một ô) không đoán — để nguyên.
    """
    da_sua = 0
    da_xet: list = []
    for (p, trong_bang), ma in zip(khoi, ma_list):
        if not trong_bang or ma != "kinh_gui_ds" or not _RE_O_DAU.match(p.text or ""):
            continue
        tbl = _bang_cua(p)
        if tbl is None or any(tbl is b for b in da_xet):
            continue
        da_xet.append(tbl)
        hang = tbl.findall(qn("w:tr"))
        if not hang or any(len(h.findall(qn("w:tc"))) != 2 for h in hang):
            continue
        # Ô gộp / lưới khác 2 cột: đặt 2 gridCol đầu là để lệch phần còn lại.
        luoi = tbl.find(qn("w:tblGrid"))
        if (luoi is not None and len(luoi.findall(qn("w:gridCol"))) != 2) or                 any(True for _ in tbl.iter(qn("w:gridSpan"))) or                 any(True for _ in tbl.iter(qn("w:vMerge"))):
            continue
        o_trai = [h.findall(qn("w:tc"))[0] for h in hang]
        o_phai = [h.findall(qn("w:tc"))[1] for h in hang]
        if p._p.getparent() is not o_trai[0]:
            continue

        # ── Đo ──
        # Lấy lại Paragraph trong `khoi` (có part → đọc được style), không dựng mới.
        doan_phai = [q for q, _ in khoi if q.text.strip()
                     and any(q._p.getparent() is o for o in o_phai)]
        nhieu_noi = len(doan_phai) > 1
        chu_trai = _RE_O_DAU.match(p.text).group(1)
        rong_trai = _rong(p, chu_trai + ":" if nhieu_noi else chu_trai + ": ", hieu_luc_run)
        if rong_trai is not None and nhieu_noi:
            rong_trai += _DU_TRAI_PT
        rong_dong = [_rong(q, q.text.strip(), hieu_luc_run) for q in doan_phai]
        if rong_trai is None or not rong_dong or any(r is None for r in rong_dong):
            _log.info("Bảng Kính gửi: không đo được bề ngang chữ — giữ nguyên bảng")
            continue
        rong_phai = max(rong_dong) * (1 + _DU_TY_LE) + _DU_PT
        rong_phai = min(rong_phai, rong_vung_chu_pt - rong_trai)
        if rong_phai <= 0:
            continue
        trai_dxa = int(round(rong_trai * 20))
        phai_dxa = int(round(rong_phai * 20))

        # ── Ghi ──
        # So XML trước/sau: chạy lại trên file đã chuẩn hoá thì mọi số đã đúng,
        # không được báo "đã sửa" lần nữa.
        truoc = etree.tostring(tbl)
        tblPr = tbl.find(qn("w:tblPr"))
        if tblPr is None:
            tblPr = parse_xml(f'<w:tblPr {nsdecls("w")}/>')
            tbl.insert(0, tblPr)
        _dat_the(tblPr, "w:tblW",
                 f'<w:tblW {nsdecls("w")} w:w="{trai_dxa + phai_dxa}" w:type="dxa"/>', _SAU_TBLW)
        _dat_the(tblPr, "w:jc", f'<w:jc {nsdecls("w")} w:val="center"/>', _SAU_JC)
        ind = tblPr.find(qn("w:tblInd"))
        if ind is not None:
            tblPr.remove(ind)
        vien = "".join(f'<w:{c} w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                       for c in ("top", "left", "bottom", "right", "insideH", "insideV"))
        _dat_the(tblPr, "w:tblBorders", f'<w:tblBorders {nsdecls("w")}>{vien}</w:tblBorders>',
                 _SAU_BORDERS)
        _dat_the(tblPr, "w:tblLayout", f'<w:tblLayout {nsdecls("w")} w:type="fixed"/>',
                 _SAU_LAYOUT)
        # Lề ô: chỉ trái/phải về 0, lề trên/dưới tác giả đặt thì giữ.
        mar = tblPr.find(qn("w:tblCellMar"))
        if mar is None:
            _dat_the(tblPr, "w:tblCellMar", f'<w:tblCellMar {nsdecls("w")}/>', ("w:tblLook",))
            mar = tblPr.find(qn("w:tblCellMar"))
        for c in ("w:start", "w:end"):
            el = mar.find(qn(c))
            if el is not None:
                mar.remove(el)
        # Lược đồ: top, left(start), bottom, right(end).
        _dat_the(mar, "w:left", f'<w:left {nsdecls("w")} w:w="0" w:type="dxa"/>',
                 ("w:bottom", "w:right"))
        _dat_the(mar, "w:right", f'<w:right {nsdecls("w")} w:w="0" w:type="dxa"/>')

        if luoi is not None:
            for cot, w in zip(luoi.findall(qn("w:gridCol")), (trai_dxa, phai_dxa)):
                cot.set(qn("w:w"), str(w))
        for o, w in [(o, trai_dxa) for o in o_trai] + [(o, phai_dxa) for o in o_phai]:
            tcPr = o.find(qn("w:tcPr"))
            if tcPr is None:
                tcPr = parse_xml(f'<w:tcPr {nsdecls("w")}/>')
                o.insert(0, tcPr)
            _dat_the(tcPr, "w:tcW", f'<w:tcW {nsdecls("w")} w:w="{w}" w:type="dxa"/>',
                     ("w:gridSpan", "w:hMerge", "w:vMerge", "w:tcBorders", "w:shd",
                      "w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText",
                      "w:vAlign", "w:hideMark"))
            # Lề riêng của ô đè lên lề của bảng — gỡ trái/phải để lề 0 có hiệu lực.
            mar = tcPr.find(qn("w:tcMar"))
            if mar is not None:
                for c in ("w:left", "w:start", "w:right", "w:end"):
                    el = mar.find(qn(c))
                    if el is not None:
                        mar.remove(el)
        da_sua += etree.tostring(tbl) != truoc
    return da_sua
