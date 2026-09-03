"""Đo bề rộng chữ thật và nén ký tự cho dòng thể thức vừa đúng một dòng.

## Vì sao phải đo, không đoán

Quy định bắt Quốc hiệu, Tiêu ngữ, tên đơn vị… nằm gọn trên dòng của nó. Nhưng
"vừa hay không" phụ thuộc ba thứ cùng lúc: chuỗi chữ, cỡ chữ, và bề rộng ô
chứa nó. Không đo thì không có cách nào biết — và cái giá của việc đoán sai đã
thấy: dòng "NGÂN HÀNG NÔNG NGHIỆP VÀ PHÁT TRIỂN NÔNG THÔN VIỆT NAM" ở cỡ 13
tràn khỏi ô 88,9 mm, Word đẩy chữ "NAM" xuống một dòng riêng — tên nước bị cắt
đôi giữa hai dòng.

Đo bằng chính phông sẽ dùng để in (Times New Roman, đúng biến thể đậm/nghiêng)
qua Pillow. Con số khớp thực tế: chuỗi trên ở cỡ 12 đậm đo được 238,0 pt, ô
khả dụng 241,2 pt — vừa, đúng như mẫu 979 trình bày.

## Vì sao nén ký tự chứ không hạ cỡ chữ

Cỡ chữ do Phụ lục III quy định, hạ xuống là làm sai một thứ đang đúng. Mẫu 979
gặp đúng tình huống này và xử lý bằng nén ký tự: Phụ lục V có dòng tên đơn vị
đầy đủ đặt `w:spacing = -24` (−1,2 pt mỗi ký tự) để cả tên nằm gọn một dòng.
Đây là bắt chước đúng cách mẫu đã làm, không phải sáng tạo thêm.

## Giới hạn

Nén quá tay thì chữ dính vào nhau, đọc còn khó hơn là để xuống dòng. Trần mặc
định lấy đúng mức mẫu 979 dùng (−24). Nén hết trần mà vẫn tràn thì DỪNG và ghi
cảnh báo — không nén tiếp, không tự hạ cỡ chữ.
"""
import logging
import os

from docx.shared import Emu
from docx.oxml.ns import qn

_log = logging.getLogger(__name__)

# Lề trái+phải mặc định của một ô bảng trong Word: 108 dxa mỗi bên.
_LE_O_MAC_DINH_DXA = 108
_DXA_MOI_PT = 20            # w:tcW và w:spacing đều tính bằng 1/20 point

_THU_MUC_FONT = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
_TEP_FONT = {
    (False, False): "times.ttf",
    (True, False): "timesbd.ttf",
    (False, True): "timesi.ttf",
    (True, True): "timesbi.ttf",
}

_bo_nho_font: dict = {}
_da_bao_thieu_font = False


def _font(co_pt: float, dam: bool, nghieng: bool):
    """Đối tượng phông để đo. Trả None khi máy không có Times New Roman."""
    global _da_bao_thieu_font
    khoa = (round(float(co_pt), 1), bool(dam), bool(nghieng))
    if khoa in _bo_nho_font:
        return _bo_nho_font[khoa]
    try:
        from PIL import ImageFont
        duong_dan = os.path.join(_THU_MUC_FONT, _TEP_FONT[(bool(dam), bool(nghieng))])
        # size tính bằng pixel; ở 72 dpi thì 1 px = 1 pt nên bề rộng trả về
        # đọc thẳng ra point, không phải quy đổi.
        f = ImageFont.truetype(duong_dan, max(1, int(round(float(co_pt)))))
    except Exception as e:                                        # noqa: BLE001
        if not _da_bao_thieu_font:
            # Máy chủ thiếu phông thì bỏ hẳn bước nén, KHÔNG đoán bừa bề rộng:
            # đoán sai là nén một dòng vốn đã vừa, chữ dính vào nhau vô cớ.
            _log.warning("Không đọc được phông Times New Roman để đo chữ (%s) — "
                         "bỏ qua bước nén cho vừa dòng", e)
            _da_bao_thieu_font = True
        f = None
    _bo_nho_font[khoa] = f
    return f


def be_rong_pt(txt: str, co_pt: float, dam: bool = False, nghieng: bool = False) -> float | None:
    """Bề rộng chuỗi khi in, tính bằng point. None = không đo được."""
    if not txt:
        return 0.0
    f = _font(co_pt, dam, nghieng)
    if f is None:
        return None
    try:
        return float(f.getlength(txt))
    except Exception as e:                                        # noqa: BLE001
        _log.warning("Đo bề rộng chữ thất bại: %s", e)
        return None


def _vung_noi_dung_pt(doc) -> float | None:
    """Bề rộng giữa hai lề trang, tính bằng point.

    Phải bọc `Emu(...)`: trừ hai `Length` với nhau trong python-docx cho ra
    `int` THƯỜNG, không còn `.pt`. Viết thẳng `(a - b - c).pt` thì ném
    AttributeError, mà chỗ gọi lại bắt `Exception` rộng nên lỗi bị nuốt và hàm
    lặng lẽ trả "không đo được" — bước nén chữ tắt ngóm mà không ai biết.
    """
    try:
        s = doc.sections[0]
        return Emu(s.page_width - s.left_margin - s.right_margin).pt
    except Exception as e:                                        # noqa: BLE001
        _log.warning("Không đọc được bề rộng vùng nội dung: %s", e)
        return None


def _o_bang_cua(p):
    """Phần tử `w:tc` chứa đoạn này, hoặc None nếu đoạn không nằm trong bảng."""
    nut = p._p.getparent()
    for _ in range(12):                     # bảng lồng nhau vài tầng là cùng
        if nut is None:
            return None
        if nut.tag == qn("w:tc"):
            return nut
        nut = nut.getparent()
    return None


def _ty_le_co_bang(o, doc) -> float:
    """Hệ số Word co bảng lại khi tổng bề rộng cột vượt vùng nội dung.

    `w:tcW` chỉ là bề rộng NGƯỜI SOẠN MONG MUỐN. Khi bảng không khai
    `tblLayout="fixed"` (mặc định của Word là autofit) và tổng các cột rộng hơn
    chỗ có thật giữa hai lề, Word thu nhỏ **toàn bộ cột theo cùng một tỷ lệ**
    cho vừa trang. Số trong file giữ nguyên, chỉ bản in là khác.

    Bỏ qua bước này thì bề rộng đo được rộng hơn thực tế, và hậu quả là im
    lặng: hàm gọi kết luận "dòng này vừa rồi" nên không nén, còn Word vẫn đẩy
    chữ cuối xuống dòng dưới. Gặp thật ở chính mẫu 979 — bảng khối đầu khai
    181,1 mm trong khi vùng nội dung chỉ 160,0 mm, ô trái thật chỉ còn 78,5 mm
    chứ không phải 88,9 mm như khai, và chữ "NAM" rơi xuống một dòng riêng.
    """
    tr = o.getparent()
    if tr is None or tr.tag != qn("w:tr"):
        return 1.0
    tbl = tr.getparent()
    if tbl is None or tbl.tag != qn("w:tbl"):
        return 1.0

    # Bảng lồng trong bảng: chỗ chứa nó là một ô, không phải vùng nội dung
    # trang. Không đoán, trả nguyên.
    cha = tbl.getparent()
    if cha is not None and cha.tag == qn("w:tc"):
        return 1.0

    tblPr = tbl.find(qn("w:tblPr"))
    if tblPr is not None:
        lay = tblPr.find(qn("w:tblLayout"))
        if lay is not None and lay.get(qn("w:type")) == "fixed":
            return 1.0                       # bề rộng cố định, Word không co

    tong = 0.0
    for oo in tr.findall(qn("w:tc")):
        tcPr = oo.find(qn("w:tcPr"))
        w = tcPr.find(qn("w:tcW")) if tcPr is not None else None
        if w is None or w.get(qn("w:type")) != "dxa":
            return 1.0                       # thiếu số liệu thì không suy diễn
        try:
            tong += float(w.get(qn("w:w")))
        except (TypeError, ValueError):
            return 1.0
    if tong <= 0:
        return 1.0

    vung = _vung_noi_dung_pt(doc)
    if vung is None:
        return 1.0
    vung *= _DXA_MOI_PT

    if tblPr is not None:
        ind = tblPr.find(qn("w:tblInd"))
        if ind is not None and ind.get(qn("w:type")) == "dxa":
            try:
                vung -= float(ind.get(qn("w:w")))
            except (TypeError, ValueError):
                pass

    return min(1.0, vung / tong) if vung > 0 else 1.0


def be_rong_kha_dung_pt(p, doc) -> float | None:
    """Bề rộng lòng dòng của đoạn, tính bằng point. None = không xác định được.

    Trong ô bảng thì lấy `w:tcW`; ngoài bảng lấy khổ giấy trừ lề trang. Cả hai
    trường hợp đều trừ tiếp phần thụt lề riêng của đoạn.
    """
    o = _o_bang_cua(p)
    if o is not None:
        tcPr = o.find(qn("w:tcPr"))
        tcW = tcPr.find(qn("w:tcW")) if tcPr is not None else None
        if tcW is None or tcW.get(qn("w:type")) != "dxa":
            # Ô khai theo phần trăm hoặc tự co giãn: không quy ra point được
            # nếu không dựng lại toàn bộ thuật toán dàn bảng của Word.
            return None
        try:
            rong = float(tcW.get(qn("w:w"))) / _DXA_MOI_PT
        except (TypeError, ValueError):
            return None
        rong *= _ty_le_co_bang(o, doc)
        rong -= 2 * _LE_O_MAC_DINH_DXA / _DXA_MOI_PT
    else:
        rong = _vung_noi_dung_pt(doc)
        if rong is None:
            return None

    pf = p.paragraph_format
    for phia in (pf.left_indent, pf.right_indent):
        if phia is not None and phia.pt > 0:
            rong -= phia.pt
    return rong if rong > 0 else None


def _dat_nen(run, twip: int) -> None:
    rPr = run._element.get_or_add_rPr()
    cu = rPr.find(qn("w:spacing"))
    if cu is not None:
        rPr.remove(cu)
    if twip:
        from docx.oxml import OxmlElement
        el = OxmlElement("w:spacing")
        el.set(qn("w:val"), str(twip))
        rPr.append(el)


def nen_cho_vua_dong(p, doc, co_pt: float, dam: bool, nghieng: bool,
                     tran_twip: int = 24) -> tuple[bool, bool]:
    """Nén ký tự để đoạn nằm gọn một dòng.

    Trả `(đã_nén, còn_tràn)`:
      * `(False, False)` — vốn đã vừa, hoặc không đo được nên không đụng tới;
      * `(True,  False)` — đã nén và giờ vừa;
      * `(False, True)`  — nén hết trần vẫn không vừa, chưa ghi gì vào file.

    Không tự hạ cỡ chữ khi hết cách: cỡ chữ là thứ Phụ lục III quy định, đổi nó
    là làm sai một chỗ đang đúng để cứu một chỗ đang sai.
    """
    txt = p.text
    if not txt.strip():
        return False, False

    rong = be_rong_kha_dung_pt(p, doc)
    if rong is None:
        return False, False
    can = be_rong_pt(txt, co_pt, dam, nghieng)
    if can is None:
        return False, False

    # Chừa 1pt: bề rộng đo được và bề rộng Word dàn chữ lệch nhau chút ít
    # (kerning, làm tròn). Sát quá thì có file vẫn rớt chữ dù tính ra là vừa.
    thua = can - (rong - 1.0)
    if thua <= 0:
        return False, False

    n = len(txt)
    if n < 2:
        return False, True
    twip = -int(-(-thua * _DXA_MOI_PT // n))        # làm tròn LÊN, tính bằng twip
    if abs(twip) > tran_twip:
        return False, True                          # quá trần: để nguyên, báo lên

    for r in p.runs:
        if r.text:
            _dat_nen(r, twip)
    return True, False
